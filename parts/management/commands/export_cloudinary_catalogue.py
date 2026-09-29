import json
from pathlib import Path

import cloudinary
from cloudinary_storage.storage import MediaCloudinaryStorage
from django.conf import settings
from django.core import serializers
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from parts.models import Category, Part


class Command(BaseCommand):
    """Upload catalogue images and export public product data."""

    help = (
        "Upload local product images to Cloudinary and export "
        "a catalogue fixture without changing the local database."
    )

    def handle(self, *args, **options):
        destination = (
            settings.BASE_DIR
            / "parts"
            / "fixtures"
            / "catalogue_cloudinary.json"
        )

        if destination.exists():
            raise CommandError(
                "The catalogue export already exists. "
                "Stop and check it before exporting again."
            )

        credentials = settings.CLOUDINARY_STORAGE

        if not all(
            credentials.get(key)
            for key in ("CLOUD_NAME", "API_KEY", "API_SECRET")
        ):
            raise CommandError("Cloudinary credentials are incomplete.")

        parts = list(Part.objects.order_by("pk"))
        categories = list(Category.objects.order_by("pk"))

        if not parts:
            raise CommandError("No products were found to export.")

        media_root = Path(settings.MEDIA_ROOT).resolve()
        local_paths = {}

        # Check every file before starting any uploads.
        for part in parts:
            if not part.image:
                continue

            path = (media_root / part.image.name).resolve()

            if not path.is_relative_to(media_root) or not path.is_file():
                raise CommandError(
                    f"Product {part.pk} has a missing or invalid image path."
                )

            local_paths[part.pk] = path

        cloudinary.config(
            cloud_name=credentials["CLOUD_NAME"],
            api_key=credentials["API_KEY"],
            api_secret=credentials["API_SECRET"],
            secure=True,
        )

        storage = MediaCloudinaryStorage()
        image_names = {}

        for part in parts:
            if part.pk not in local_paths:
                continue

            path = local_paths[part.pk]

            try:
                with path.open("rb") as image_file:
                    saved_name = storage.save(
                        f"bimmerhub/parts/product-{part.pk}{path.suffix.lower()}",
                        File(image_file),
                    )

                if len(saved_name) > Part._meta.get_field("image").max_length:
                    raise ValueError("Uploaded image identifier is too long.")

                if not storage.exists(saved_name):
                    raise ValueError("Uploaded image could not be verified.")
            except Exception:
                raise CommandError(
                    f"Image upload or verification failed for product "
                    f"{part.pk}. No fixture was written and the local "
                    f"database is unchanged. Earlier uploads may exist."
                ) from None

            image_names[part.pk] = saved_name
            self.stdout.write(f"Uploaded and verified product {part.pk}")

        # Change image references only in the exported copy.
        records = json.loads(
            serializers.serialize("json", categories + parts)
        )

        for record in records:
            if record["model"] == "parts.part":
                uploaded_name = image_names.get(record["pk"])

                if uploaded_name:
                    record["fields"]["image"] = uploaded_name

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(records, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Exported {len(categories)} categories, "
                f"{len(parts)} products and {len(image_names)} images."
            )
        )
        self.stdout.write(f"Catalogue file: {destination}")
        self.stdout.write("Local database and image files unchanged.")
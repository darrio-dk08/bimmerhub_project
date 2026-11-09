from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import SESSION_KEY, get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs).get("href", ""))


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class AuthenticationTests(TestCase):
    """Exercise real allauth forms, sessions and rendered navigation."""

    password = "Bimmer-Test-739!secure"

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="auth_customer", email="auth@example.com",
            password=cls.password,
        )

    def setUp(self):
        cache.clear()
        self.login = reverse("account_login")
        self.signup = reverse("account_signup")
        self.logout = reverse("account_logout")

    def credentials(self, **extra):
        return {
            "login": self.user.username, "password": self.password, **extra,
        }

    def registration(self, **extra):
        return {
            "username": "new_customer", "email": "new@example.com",
            "password1": self.password, "password2": self.password, **extra,
        }

    def test_anonymous_forms_use_shared_layout(self):
        for url, template in (
            (self.login, "account/login.html"),
            (self.signup, "account/signup.html"),
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertTemplateUsed(response, template)
            self.assertTemplateUsed(response, "base.html")
            self.assertContains(response, 'name="csrfmiddlewaretoken"')
            self.assertContains(response, 'class="auth-card"')

    def test_registration_creates_user_with_hashed_password_and_logs_in(self):
        response = self.client.post(self.signup, self.registration())
        self.assertRedirects(response, reverse("core:home"))
        user = get_user_model().objects.get(username="new_customer")
        self.assertTrue(user.check_password(self.password))
        self.assertNotEqual(user.password, self.password)
        self.assertEqual(self.client.session[SESSION_KEY], str(user.pk))

    def test_registration_rejects_invalid_input(self):
        for changes in (
            {"username": ""}, {"username": self.user.username},
            {"email": "invalid-email"}, {"password2": "different-password"},
            {"password1": "123", "password2": "123"},
        ):
            with self.subTest(changes=changes):
                response = self.client.post(
                    self.signup, self.registration(**changes),
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
                self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_login_with_valid_credentials(self):
        response = self.client.post(self.login, self.credentials())
        self.assertRedirects(response, reverse("core:home"))
        self.assertEqual(self.client.session[SESSION_KEY], str(self.user.pk))

    def test_login_error_is_visible_and_does_not_authenticate(self):
        response = self.client.post(
            self.login, self.credentials(password="wrong-password"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].non_field_errors())
        self.assertContains(response, "errorlist")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_inactive_user_cannot_log_in(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.client.post(self.login, self.credentials())
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_authenticated_users_cannot_open_or_submit_auth_forms(self):
        self.client.force_login(self.user)
        for url, data in (
            (self.login, self.credentials()),
            (self.signup, self.registration()),
        ):
            for method in (self.client.get, self.client.post):
                response = method(url, data)
                self.assertRedirects(response, reverse("core:home"))
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_login_respects_internal_next(self):
        response = self.client.post(self.login, self.credentials(
            next=reverse("garage:vehicle_list"),
        ))
        self.assertRedirects(response, reverse("garage:vehicle_list"))

    def test_login_and_signup_reject_external_next(self):
        for url, data in (
            (self.login, self.credentials(next="https://evil.example/")),
            (self.signup, self.registration(next="//evil.example/")),
        ):
            self.client.logout()
            response = self.client.post(url, data)
            self.assertRedirects(response, reverse("core:home"))

    def test_auth_switch_links_preserve_checkout_destination(self):
        target = reverse("payments:checkout")
        for source, destination in (
            (self.login, self.signup), (self.signup, self.login),
        ):
            response = self.client.get(source, {"next": target})
            parser = LinkParser()
            parser.feed(response.content.decode())
            links = [urlsplit(link) for link in parser.links]
            matches = [link for link in links if link.path == destination
                       and parse_qs(link.query).get("next") == [target]]
            self.assertTrue(matches, "Account switch must preserve next")

    def test_logout_get_does_not_end_session_but_post_does(self):
        response = self.client.post(self.login, self.credentials())
        self.assertEqual(response.status_code, 302)
        response = self.client.get(self.logout)
        self.assertTemplateUsed(response, "account/logout.html")
        self.assertIn(SESSION_KEY, self.client.session)
        self.assertRedirects(
            self.client.post(self.logout), reverse("core:home"),
        )
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_authentication_posts_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        for url, data in (
            (self.login, self.credentials()),
            (self.signup, self.registration()),
        ):
            self.assertEqual(client.post(url, data).status_code, 403)
        client.force_login(self.user)
        self.assertEqual(client.post(self.logout).status_code, 403)
        self.assertIn(SESSION_KEY, client.session)

    def test_protected_pages_redirect_to_login_with_destination(self):
        for name in (
            "garage:vehicle_list", "garage:vehicle_create",
            "payments:checkout", "payments:order_list",
        ):
            target = reverse(name)
            response = self.client.get(target)
            self.assertEqual(response.status_code, 302)
            parsed = urlsplit(response.url)
            self.assertEqual(parsed.path, self.login)
            self.assertEqual(parse_qs(parsed.query)["next"], [target])

    def test_anonymous_home_internal_links_work(self):
        response = self.client.get(reverse("core:home"))
        parser = LinkParser()
        parser.feed(response.content.decode())
        self.assertNotIn("", parser.links)
        for link in set(parser.links):
            if link.startswith("/") and not link.startswith("//"):
                with self.subTest(link=link):
                    self.assertLess(self.client.get(link).status_code, 400)

    def test_authenticated_navigation_contains_working_customer_links(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("core:home"))
        for name in ("garage:vehicle_list", "payments:order_list",
                     "payments:basket_detail", "account_logout"):
            url = reverse(name)
            self.assertContains(response, f'href="{url}"')
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertNotContains(response, f'href="{self.login}"')
        self.assertNotContains(response, f'href="{self.signup}"')

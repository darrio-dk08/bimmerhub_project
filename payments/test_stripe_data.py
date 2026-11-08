import stripe

from django.test import SimpleTestCase

from .stripe_data import stripe_to_dict


class StripeDataTests(SimpleTestCase):
    """Check conversion of real Stripe SDK response objects."""

    def test_sdk_object_and_nested_data_become_dictionaries(self):
        response = stripe.StripeObject.construct_from(
            {
                "id": "evt_test_conversion",
                "livemode": False,
                "data": {
                    "object": {
                        "id": "cs_test_conversion",
                        "metadata": {
                            "order_reference": "test-reference",
                        },
                    },
                },
            },
            None,
        )

        result = stripe_to_dict(response)

        self.assertIsInstance(result, dict)
        self.assertIs(result.get("livemode"), False)

        session = result["data"]["object"]
        self.assertIsInstance(session, dict)
        self.assertEqual(session.get("id"), "cs_test_conversion")
        self.assertEqual(
            session["metadata"].get("order_reference"),
            "test-reference",
        )

    def test_dictionary_input_is_preserved(self):
        response = {"id": "cs_test_dictionary"}

        self.assertIs(stripe_to_dict(response), response)

    def test_invalid_input_is_rejected(self):
        with self.assertRaises(TypeError):
            stripe_to_dict(None)
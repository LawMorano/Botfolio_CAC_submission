import json
import os
import unittest
from unittest.mock import patch

from services import email_service


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return b"OK"


class EmailServiceTests(unittest.TestCase):
    def test_structured_verification_fields_reach_emailjs(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured.update(json.loads(request.data.decode("utf-8")))
            self.assertEqual(timeout, 15)
            return _Response()

        with patch.dict(os.environ, {"EMAILJS_PRIVATE_KEY": "private"}), \
             patch.object(email_service, "SERVICE_ID", "service"), \
             patch.object(email_service, "TEMPLATE_ID", "template"), \
             patch.object(email_service, "PUBLIC_KEY", "public"), \
             patch.object(email_service, "PRIVATE_KEY", "private"), \
             patch.object(email_service.urllib.request, "urlopen", fake_urlopen):
            sent = email_service.send_email(
                to_email="member@example.com", to_name="member",
                subject="Verify your Botfolio email", heading="Verify your email",
                message="Please verify your email address.",
                greeting="Hi member,", intro="Thanks for joining Botfolio.",
                purpose="Please verify your email address.", action_url="https://botfoliohq.com/verify-email/token",
                action_text="Verify Email", security_notice="Ignore this if it was not you.",
                footer="Account creation notice.",
            )

        self.assertTrue(sent)
        self.assertEqual(captured["accessToken"], "private")
        params = captured["template_params"]
        self.assertEqual(params["from_email"], "noreply@botfoliohq.com")
        self.assertEqual(params["from_name"], "Botfolio")
        self.assertEqual(params["greeting"], "Hi member,")
        self.assertEqual(params["action_text"], "Verify Email")
        self.assertEqual(params["footer"], "Account creation notice.")


if __name__ == "__main__":
    unittest.main()

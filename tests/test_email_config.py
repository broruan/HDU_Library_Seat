import unittest
from dataclasses import asdict
from unittest.mock import patch

from hdu_seat.config import EmailSettings, Settings


def valid_email_data(**overrides):
    data = {
        "enabled": True,
        "smtp_host": "smtp.example.test",
        "smtp_port": 465,
        "security": "ssl",
        "username": "sender@example.test",
        "password": "test-app-password",
        "sender": "sender@example.test",
        "recipient": "phone@example.test",
    }
    data.update(overrides)
    return data


def settings_data(**email_overrides):
    return {
        "base_url": "https://example.test",
        "cookie": "sid=test",
        "space_category": {"category_id": 591, "content_id": 3},
        "email": valid_email_data(**email_overrides),
    }


class EmailConfigTests(unittest.TestCase):
    def test_old_config_defaults_to_disabled_email(self):
        data = settings_data()
        del data["email"]
        settings = Settings.from_dict(data)
        self.assertEqual(settings.email, EmailSettings())
        self.assertFalse(settings.email.enabled)

    def test_nested_email_config_survives_serialization(self):
        data = settings_data()
        settings = Settings.from_dict(data)
        saved = asdict(settings)
        restored = Settings.from_dict(saved)
        self.assertEqual(saved["email"], data["email"])
        self.assertEqual(restored.email, settings.email)

    def test_disabled_invalid_smtp_does_not_block_booking(self):
        settings = Settings.from_dict(settings_data(
            enabled=False,
            smtp_host="",
            smtp_port="invalid",
            security="unsupported",
            username="",
            password="",
            sender="",
            recipient="",
        ))
        self.assertFalse(settings.email.enabled)
        self.assertEqual(settings.cookie, "sid=test")

    def test_enabled_email_requires_smtp_and_address_fields(self):
        for field in ("smtp_host", "username", "password", "recipient"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    Settings.from_dict(settings_data(**{field: ""}))

    def test_enabled_email_rejects_invalid_ports(self):
        for port in (0, -1, 65536, "invalid", True, 465.5):
            with self.subTest(port=port):
                with self.assertRaises(ValueError):
                    Settings.from_dict(settings_data(smtp_port=port))

    def test_enabled_email_requires_secure_transport(self):
        for security in ("plain", "none", "unsupported", ""):
            with self.subTest(security=security):
                with self.assertRaises(ValueError):
                    Settings.from_dict(settings_data(security=security))

    def test_supported_secure_transports_and_string_port(self):
        for security, port in (("ssl", "465"), ("starttls", "587")):
            with self.subTest(security=security):
                email = Settings.from_dict(settings_data(security=security, smtp_port=port)).email
                email.validate()
                self.assertEqual(email.smtp_port, int(port))

    def test_sender_can_default_to_email_username(self):
        email = Settings.from_dict(settings_data(sender="")).email
        email.validate()
        self.assertEqual(email.username, "sender@example.test")
        with self.assertRaises(ValueError):
            Settings.from_dict(settings_data(sender="", username="non-email-login"))

    def test_enabled_false_string_is_not_truthy(self):
        email = EmailSettings.from_dict({"enabled": "false", "smtp_port": "bad"})
        self.assertFalse(email.enabled)

    def test_addresses_reject_multiple_recipients_and_header_injection(self):
        for address in (
            "one@example.test,two@example.test",
            "one@example.test;two@example.test",
            "one@example.test\r\nBcc: other@example.test",
            "Display Name <one@example.test>",
        ):
            with self.subTest(address=address):
                with self.assertRaises(ValueError):
                    Settings.from_dict(settings_data(recipient=address))

    def test_smtp_host_rejects_url_and_control_characters(self):
        for host in ("https://smtp.example.test", "smtp.example.test/path", "smtp.example.test\nother"):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    Settings.from_dict(settings_data(smtp_host=host))

    def test_password_is_not_exposed_in_dataclass_repr(self):
        email = EmailSettings.from_dict(valid_email_data())
        self.assertNotIn("test-app-password", repr(email))

    def test_email_config_can_be_loaded_without_booking_cookie(self):
        data = settings_data()
        del data["cookie"]
        with patch.dict("os.environ", {"HDU_LIBRARY_COOKIE": ""}):
            settings = Settings.from_dict(data, require_cookie=False)
        self.assertEqual(settings.cookie, "")
        self.assertTrue(settings.email.enabled)

    def test_bad_config_shape_is_rejected(self):
        with self.assertRaises(ValueError):
            EmailSettings.from_dict("invalid")


if __name__ == "__main__":
    unittest.main()

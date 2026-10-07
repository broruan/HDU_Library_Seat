import smtplib
import ssl
import threading
import unittest
from unittest.mock import Mock, call, patch

from hdu_seat.config import Booking, EmailSettings, Settings, SpaceCategory
from hdu_seat.hunter import Attempt
from hdu_seat.notification import (
    EmailNotificationError,
    EmailNotifier,
    booking_email,
    send_email,
    send_test_email,
)


def email_settings(**overrides):
    values = {
        "enabled": True,
        "smtp_host": "smtp.example.test",
        "smtp_port": 465,
        "security": "ssl",
        "username": "sender@example.test",
        "password": "test-app-password",
        "sender": "sender@example.test",
        "recipient": "phone@example.test",
    }
    values.update(overrides)
    return EmailSettings(**values)


class EmailSenderTests(unittest.TestCase):
    def test_ssl_uses_verified_context_timeout_and_authenticated_message(self):
        connection = Mock()
        connection.send_message.return_value = {}
        context = object()
        with (
            patch("hdu_seat.notification.ssl.create_default_context", return_value=context),
            patch("hdu_seat.notification.smtplib.SMTP_SSL", return_value=connection) as smtp_ssl,
            patch("hdu_seat.notification.smtplib.SMTP") as smtp_plain,
        ):
            send_email(email_settings(), "预约成功", "座位：A-012")
        smtp_ssl.assert_called_once_with("smtp.example.test", 465, timeout=10, context=context)
        smtp_plain.assert_not_called()
        connection.login.assert_called_once_with("sender@example.test", "test-app-password")
        connection.send_message.assert_called_once()
        message = connection.send_message.call_args.args[0]
        self.assertEqual(message["Subject"], "预约成功")
        self.assertEqual(message["From"], "sender@example.test")
        self.assertEqual(message["To"], "phone@example.test")
        self.assertEqual(message.get_content().strip(), "座位：A-012")
        connection.close.assert_called_once()

    def test_starttls_encrypts_before_authentication(self):
        connection = Mock()
        connection.send_message.return_value = {}
        context = object()
        with (
            patch("hdu_seat.notification.ssl.create_default_context", return_value=context),
            patch("hdu_seat.notification.smtplib.SMTP", return_value=connection) as smtp_plain,
            patch("hdu_seat.notification.smtplib.SMTP_SSL") as smtp_ssl,
        ):
            send_email(email_settings(smtp_port=587, security="starttls"), "预约成功", "座位")
        smtp_plain.assert_called_once_with("smtp.example.test", 587, timeout=10)
        smtp_ssl.assert_not_called()
        self.assertEqual(connection.mock_calls[:4], [
            call.ehlo(),
            call.starttls(context=context),
            call.ehlo(),
            call.login("sender@example.test", "test-app-password"),
        ])
        connection.send_message.assert_called_once()

    def test_failed_starttls_never_authenticates(self):
        connection = Mock()
        connection.starttls.side_effect = ssl.SSLError("private TLS server detail")
        with patch("hdu_seat.notification.smtplib.SMTP", return_value=connection):
            with self.assertRaises(EmailNotificationError) as raised:
                send_email(email_settings(security="starttls", smtp_port=587), "成功", "座位")
        connection.login.assert_not_called()
        connection.send_message.assert_not_called()
        self.assertNotIn("private TLS server detail", str(raised.exception))
        self.assertFalse(raised.exception.retryable)

    def test_disabled_notification_can_still_send_test_email(self):
        with patch("hdu_seat.notification.send_email") as send:
            settings = email_settings(enabled=False)
            send_test_email(settings)
        self.assertIs(send.call_args.args[0], settings)
        self.assertIn("测试", send.call_args.args[1])

    def test_disabled_test_email_still_validates_smtp_before_connecting(self):
        with patch("hdu_seat.notification.smtplib.SMTP_SSL") as smtp_ssl:
            with self.assertRaises(EmailNotificationError):
                send_email(EmailSettings(enabled=False), "测试邮件", "测试内容")
        smtp_ssl.assert_not_called()

    def test_empty_sender_defaults_to_email_username(self):
        connection = Mock()
        connection.send_message.return_value = {}
        with patch("hdu_seat.notification.smtplib.SMTP_SSL", return_value=connection):
            send_email(email_settings(sender=""), "成功", "座位")
        self.assertEqual(connection.send_message.call_args.args[0]["From"], "sender@example.test")

    def test_authentication_failure_is_redacted_and_not_retried(self):
        connection = Mock()
        connection.login.side_effect = smtplib.SMTPAuthenticationError(
            535, b"535 rejected test-app-password token=private-token"
        )
        with patch("hdu_seat.notification.smtplib.SMTP_SSL", return_value=connection):
            with self.assertRaises(EmailNotificationError) as raised:
                send_email(email_settings(), "成功", "座位")
        self.assertIn("认证失败", str(raised.exception))
        self.assertNotIn("test-app-password", str(raised.exception))
        self.assertNotIn("private-token", str(raised.exception))
        self.assertFalse(raised.exception.retryable)
        connection.send_message.assert_not_called()
        connection.close.assert_called_once()

    def test_connection_failure_is_redacted_and_retryable(self):
        with patch("hdu_seat.notification.smtplib.SMTP_SSL", side_effect=OSError("private secret-host:465")):
            with self.assertRaises(EmailNotificationError) as raised:
                send_email(email_settings(), "成功", "座位")
        self.assertNotIn("secret-host", str(raised.exception))
        self.assertTrue(raised.exception.retryable)

    def test_refused_recipient_dict_is_delivery_failure(self):
        connection = Mock()
        connection.send_message.return_value = {"phone@example.test": (550, b"private rejection token")}
        with patch("hdu_seat.notification.smtplib.SMTP_SSL", return_value=connection):
            with self.assertRaises(EmailNotificationError) as raised:
                send_email(email_settings(), "成功", "座位")
        self.assertIn("收件邮箱", str(raised.exception))
        self.assertNotIn("private rejection token", str(raised.exception))
        self.assertNotIn("phone@example.test", str(raised.exception))
        self.assertFalse(raised.exception.retryable)

    def test_transient_smtp_response_is_retryable_but_permanent_is_not(self):
        for code, retryable in ((451, True), (550, False)):
            with self.subTest(code=code):
                connection = Mock()
                connection.send_message.side_effect = smtplib.SMTPDataError(code, b"private detail")
                with patch("hdu_seat.notification.smtplib.SMTP_SSL", return_value=connection):
                    with self.assertRaises(EmailNotificationError) as raised:
                        send_email(email_settings(), "成功", "座位")
                self.assertEqual(raised.exception.retryable, retryable)
                self.assertNotIn("private detail", str(raised.exception))

    def test_network_failure_after_data_submission_has_uncertain_result_without_retry(self):
        for error in (TimeoutError("secret timeout"), OSError("secret socket"), smtplib.SMTPServerDisconnected("secret disconnect")):
            with self.subTest(error=type(error).__name__):
                connection = Mock()
                connection.send_message.side_effect = error
                with patch("hdu_seat.notification.smtplib.SMTP_SSL", return_value=connection):
                    with self.assertRaises(EmailNotificationError) as raised:
                        send_email(email_settings(), "成功", "座位")
                self.assertIn("未确认", str(raised.exception))
                self.assertFalse(raised.exception.retryable)
                self.assertNotIn("secret", str(raised.exception))
                connection.send_message.assert_called_once()
    def test_close_failure_after_acceptance_does_not_duplicate_delivery(self):
        connection = Mock()
        connection.send_message.return_value = {}
        connection.close.side_effect = OSError("QUIT failed")
        with patch("hdu_seat.notification.smtplib.SMTP_SSL", return_value=connection):
            send_email(email_settings(), "成功", "座位")
        connection.send_message.assert_called_once()


class BookingEmailTests(unittest.TestCase):
    def test_message_includes_booking_details_without_raw_upstream_response(self):
        settings = Settings(
            base_url="https://example.test",
            cookie="sid=private-cookie",
            space_category=SpaceCategory(591, 3),
            booking=Booking(date="2026-10-08", start_time="08:00", duration_hours=4.5),
            email=email_settings(),
        )
        result = Attempt(
            "2026-10-07T07:59:59+08:00", "reserved",
            "raw response cookie=private-cookie token=private-token",
            {"id": "private-seat-id", "title": "A-012", "floor": 3, "area": "东区"},
        )
        subject, body = booking_email(settings, result)
        self.assertIn("成功", subject)
        for detail in ("A-012", "东区", "2026-10-08", "08:00", "4.5", "北京时间"):
            self.assertIn(detail, body)
        for secret in (result.message, "private-cookie", "private-token", "test-app-password"):
            self.assertNotIn(secret, subject + body)

    def test_immediate_booking_uses_beijing_date_from_timestamp(self):
        settings = Settings("https://example.test", "sid=test", SpaceCategory(591, 3))
        result = Attempt("2026-10-07T17:00:00+00:00", "reserved", "secret", {"name": "A-012", "floor": 3})
        subject, body = booking_email(settings, result)
        self.assertIn("2026-10-08", body)
        self.assertIn("立即预约", body)
        self.assertIn("3楼", body)
        self.assertIn("A-012", body)


class EmailNotifierTests(unittest.TestCase):
    def create_notifier(self, terminal_count=1):
        updates = []
        done = threading.Event()

        def on_status(update):
            updates.append(update)
            if sum(item["status"] in {"sent", "failed"} for item in updates) >= terminal_count:
                done.set()

        return EmailNotifier(on_status, retry_delays=(0, 0)), updates, done

    def test_async_submission_deduplicates_inflight_and_sent_keys(self):
        entered = threading.Event()
        release = threading.Event()

        def sender(*args):
            entered.set()
            if not release.wait(2):
                raise RuntimeError("test did not release sender")

        notifier, updates, done = self.create_notifier()
        with patch("hdu_seat.notification.send_email", side_effect=sender) as send:
            try:
                self.assertTrue(notifier.submit(email_settings(), "成功", "座位", "reservation-1"))
                self.assertTrue(entered.wait(1))
                self.assertFalse(done.is_set())
                self.assertFalse(notifier.submit(email_settings(), "成功", "座位", "reservation-1"))
                release.set()
                self.assertTrue(done.wait(2))
                self.assertFalse(notifier.submit(email_settings(), "成功", "座位", "reservation-1"))
            finally:
                release.set()
                notifier.close(wait=True)
            send.assert_called_once()
        self.assertEqual([item["status"] for item in updates], ["pending", "sending", "sent"])
        for update in updates:
            self.assertIn("message", update)
            self.assertTrue(update["at"])

    def test_transient_delivery_failure_retries_until_success(self):
        notifier, updates, done = self.create_notifier()
        with patch("hdu_seat.notification.send_email", side_effect=[
            EmailNotificationError("暂时失败", retryable=True), None,
        ]) as send:
            try:
                self.assertTrue(notifier.submit(email_settings(), "成功", "座位", "retry"))
                self.assertTrue(done.wait(2))
            finally:
                notifier.close(wait=True)
            self.assertEqual(send.call_count, 2)
        self.assertEqual(updates[-1]["status"], "sent")

    def test_transient_failure_stops_after_three_attempts(self):
        notifier, updates, done = self.create_notifier()
        with patch("hdu_seat.notification.send_email", side_effect=EmailNotificationError("暂时失败", retryable=True)) as send:
            try:
                self.assertTrue(notifier.submit(email_settings(), "成功", "座位", "fail"))
                self.assertTrue(done.wait(2))
                self.assertFalse(notifier.submit(email_settings(), "成功", "座位", "fail"))
            finally:
                notifier.close(wait=True)
            self.assertEqual(send.call_count, 3)
        self.assertEqual(updates[-1]["status"], "failed")

    def test_permanent_failure_does_not_retry_and_next_message_still_sends(self):
        notifier, updates, done = self.create_notifier(terminal_count=2)
        with patch("hdu_seat.notification.send_email", side_effect=[EmailNotificationError("认证失败"), None]) as send:
            try:
                self.assertTrue(notifier.submit(email_settings(), "第一封", "座位", "first"))
                self.assertTrue(notifier.submit(email_settings(), "第二封", "座位", "second"))
                self.assertTrue(done.wait(2))
            finally:
                notifier.close(wait=True)
            self.assertEqual(send.call_count, 2)
        self.assertIn("failed", [item["status"] for item in updates])
        self.assertEqual(updates[-1]["status"], "sent")

    def test_unexpected_failure_is_redacted_and_worker_survives(self):
        notifier, updates, done = self.create_notifier()
        with patch("hdu_seat.notification.send_email", side_effect=RuntimeError("private-token")):
            try:
                self.assertTrue(notifier.submit(email_settings(), "成功", "座位", "unexpected"))
                self.assertTrue(done.wait(2))
            finally:
                notifier.close(wait=True)
        self.assertEqual(updates[-1]["status"], "failed")
        self.assertNotIn("private-token", str(updates))

    def test_disabled_notification_is_not_queued(self):
        notifier, updates, done = self.create_notifier()
        with patch("hdu_seat.notification.send_email") as send:
            try:
                self.assertFalse(notifier.submit(email_settings(enabled=False), "成功", "座位", "disabled"))
            finally:
                notifier.close(wait=True)
            send.assert_not_called()
        self.assertEqual(updates, [])


if __name__ == "__main__":
    unittest.main()


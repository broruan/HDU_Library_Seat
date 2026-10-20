import unittest
from datetime import datetime
from unittest.mock import patch

from hdu_seat.client import BEIJING_TZ, HDUClientError
from hdu_seat.hunter import Attempt
from hdu_seat.server import (
    SeatWebServer,
    dict_to_settings,
    scheduled_start_timestamp,
    settings_to_dict,
    settings_to_nested,
)


class ServerConfigTests(unittest.TestCase):
    def test_roundtrip_preserves_core_fields(self):
        flat = {
            "cookie": "sid=abc",
            "category_id": "591",
            "content_id": "3",
            "date": None,
            "start_time": "08:00",
            "duration_hours": "4",
            "num": "1",
            "seat_ids": ["001", "002"],
            "keywords": ["window"],
            "poll_interval": "3",
            "schedule_at": "2099-09-04T07:59:30",
        }
        settings = dict_to_settings(flat)
        out = settings_to_dict(settings)
        self.assertEqual(out["category_id"], 591)
        self.assertEqual(out["content_id"], 3)
        self.assertEqual(out["seat_ids"], ["001", "002"])
        self.assertEqual(out["duration_hours"], 4.0)
        self.assertEqual(out["schedule_at"], "2099-09-04T07:59:30")

    def test_nested_has_config_shape(self):
        settings = dict_to_settings({"cookie": "sid=abc", "category_id": 591, "content_id": 3})
        nested = settings_to_nested(settings)
        self.assertEqual(nested["space_category"]["category_id"], 591)
        self.assertEqual(nested["space_category"]["content_id"], 3)
        self.assertIn("booking", nested)
        self.assertIn("rule", nested)
        self.assertEqual(nested["schedule_at"], settings.schedule_at)

    def test_numeric_fallbacks(self):
        settings = dict_to_settings({"cookie": "sid=abc", "category_id": "bad", "content_id": "bad"})
        self.assertEqual(settings.space_category.category_id, 591)
        self.assertEqual(settings.space_category.content_id, 3)

    def test_legacy_json_cookie_is_unwrapped(self):
        settings = dict_to_settings({"cookie": '{"cookie": "sid=abc; uid=1"}'})
        self.assertEqual(settings.cookie, "sid=abc; uid=1")

    def test_boolean_and_floor_are_converted(self):
        settings = dict_to_settings({
            "cookie": "sid=abc",
            "preferred_floor": "3",
            "avoid_near_door": "false",
        })
        self.assertEqual(settings.rule.preferred_floor, 3)
        self.assertFalse(settings.rule.avoid_near_door)

    def test_string_false_is_not_truthy(self):
        self.assertFalse(dict_to_settings({"cookie": "sid=abc", "avoid_near_door": "0"}).rule.avoid_near_door)

    def test_live_snapshot_keeps_only_currently_available_seats(self):
        server = SeatWebServer("missing-test-config.json")
        server._update_seats([
            {"id": "1", "title": "001", "area": "二楼", "available": True},
            {"id": "2", "title": "002", "area": "二楼", "available": False},
        ])

        snapshot = server.snapshot()
        self.assertEqual([seat["id"] for seat in snapshot["seats"]], ["1"])
        self.assertEqual(snapshot["seat_revision"], 1)
        self.assertIsNotNone(snapshot["seat_updated_at"])

    def test_scheduled_start_is_interpreted_as_beijing_time(self):
        settings = dict_to_settings({"cookie": "sid=abc", "schedule_at": "2099-09-04T07:59:30"})
        timestamp = scheduled_start_timestamp(settings, now=0)
        expected = datetime(2099, 9, 4, 7, 59, 30, tzinfo=BEIJING_TZ).timestamp()
        self.assertEqual(timestamp, expected)

    def test_past_scheduled_start_is_rejected(self):
        settings = dict_to_settings({"cookie": "sid=abc", "schedule_at": "2000-01-01T00:00"})
        with self.assertRaisesRegex(HDUClientError, "已过去"):
            scheduled_start_timestamp(settings)

    def test_waiting_schedule_can_be_cancelled(self):
        server = SeatWebServer("missing-test-config.json")
        server._persist = lambda _: None
        result = server.start({"cookie": "sid=abc", "schedule_at": "2099-09-04T07:59:30"})
        self.assertTrue(result["waiting"])
        self.assertTrue(server.snapshot()["waiting"])

        server.stop()
        server.worker.join(timeout=1)
        snapshot = server.snapshot()
        self.assertFalse(snapshot["running"])
        self.assertFalse(snapshot["waiting"])
        self.assertEqual(snapshot["last_result"]["message"], "已取消定时抢座")

    def test_running_loop_reloads_saved_seat_selection_each_attempt(self):
        server = SeatWebServer("missing-test-config.json")
        server._persist = lambda _: None
        initial = dict_to_settings({
            "cookie": "sid=abc",
            "seat_ids": ["old-seat"],
            "poll_interval": 0,
            "max_attempts": 2,
        })
        server.settings = initial
        server.running = True
        seen = []

        class FakeHunter:
            def __init__(self, settings, on_seats=None, should_stop=None):
                seen.append(list(settings.rule.seat_ids))

            def run_once(self, dry_run=False):
                if len(seen) == 1:
                    updated = settings_to_dict(initial)
                    updated["seat_ids"] = ["new-seat"]
                    server.save_config(updated)
                    return Attempt("now", "empty", "retry")
                return Attempt("now", "reserved", "ok", {"id": "new-seat"})

        with patch("hdu_seat.server.SeatHunter", FakeHunter):
            server._run_loop(initial)

        self.assertEqual(seen, [["old-seat"], ["new-seat"]])
        self.assertEqual(server.snapshot()["last_result"]["status"], "reserved")

    def test_stop_during_query_prevents_following_reservation(self):
        server = SeatWebServer("missing-test-config.json")
        server.settings = dict_to_settings({"cookie": "sid=abc", "poll_interval": 0})
        server.running = True
        def seats():
            server.stop()
            return [{"id": "A-01", "available": True}]
        try:
            with patch("hdu_seat.hunter.ZhishulibClient") as factory:
                client = factory.return_value
                client.seats.side_effect = seats
                server._run_loop(server.settings)
                client.reserve.assert_not_called()
                client.seats.assert_called_once()
            self.assertFalse(server.snapshot()["running"])
            self.assertEqual(server.snapshot()["last_result"]["status"], "stopped")
        finally:
            server.close()


class ServerEmailConfigTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.temp = tempfile.TemporaryDirectory(prefix="_test_server_email_", dir=Path(__file__).resolve().parent.parent)
        self.server = SeatWebServer(Path(self.temp.name) / "config.json")
        self.server._persist = lambda _: None

    def tearDown(self):
        self.server.notifier.close()
        self.temp.cleanup()

    def email_config(self, **changes):
        values = {
            "email_enabled": True,
            "smtp_host": "smtp.example.test",
            "smtp_port": 465,
            "smtp_security": "ssl",
            "smtp_username": "sender@example.test",
            "smtp_password": "private-authorization-code",
            "email_sender": "sender@example.test",
            "email_recipient": "phone@example.test",
        }
        values.update(changes)
        return values

    def test_email_can_be_saved_before_cookie_is_provided(self):
        result = self.server.save_config(self.email_config())
        self.assertEqual(self.server.settings.cookie, "")
        self.assertTrue(result["email_enabled"])
        self.assertEqual(result["smtp_password"], "")
        self.assertTrue(result["smtp_password_set"])

    def test_public_config_and_status_never_return_smtp_password(self):
        self.server.save_config(self.email_config(cookie="sid=abc"))
        for flat in (settings_to_dict(self.server.settings), self.server.snapshot()["config"]):
            self.assertEqual(flat["smtp_password"], "")
            self.assertTrue(flat["smtp_password_set"])
            self.assertNotIn("private-authorization-code", str(flat))

    def test_empty_password_preserves_saved_authorization_code(self):
        self.server.save_config(self.email_config())
        self.server.save_config(self.email_config(smtp_password=""))
        self.assertEqual(self.server.settings.email.password, "private-authorization-code")
        settings = self.server.use_config(self.email_config(cookie="sid=abc", smtp_password=""))
        self.assertEqual(settings.email.password, "private-authorization-code")

    def test_explicit_password_clear_removes_saved_authorization_code(self):
        self.server.save_config(self.email_config())
        result = self.server.save_config(self.email_config(
            email_enabled=False, smtp_password="", smtp_password_clear=True,
        ))
        self.assertEqual(self.server.settings.email.password, "")
        self.assertFalse(result["smtp_password_set"])

    def test_sender_defaults_to_login_email(self):
        self.server.save_config(self.email_config(email_sender=""))
        with patch("hdu_seat.notification.smtplib.SMTP_SSL") as smtp:
            smtp.return_value.send_message.return_value = {}
            self.server.test_email(self.email_config(email_sender="", smtp_password=""))
        message = smtp.return_value.send_message.call_args.args[0]
        self.assertEqual(message["From"], "sender@example.test")

    def test_enabled_invalid_mail_configuration_is_rejected(self):
        for change in (
            {"smtp_port": "abc"}, {"smtp_port": 0}, {"smtp_port": 65536},
            {"smtp_security": "none"}, {"smtp_host": "https://smtp.example.test"},
            {"email_recipient": "one@example.test,two@example.test"},
            {"email_sender": "sender@example.test\r\nBcc: leak@example.test"},
        ):
            with self.subTest(change=change), self.assertRaises(HDUClientError):
                self.server.save_config(self.email_config(**change))

    def test_disabled_invalid_mail_configuration_does_not_block_booking_config(self):
        flat = self.email_config(
            email_enabled=False, cookie="sid=abc", smtp_host="", smtp_port="bad",
            smtp_security="bad", smtp_password="", email_recipient="",
        )
        self.server.save_config(flat)
        self.assertFalse(self.server.use_config(flat).email.enabled)

    def test_mail_settings_survive_nested_persistence_without_exposing_password_in_flat(self):
        self.server.save_config(self.email_config(cookie="sid=abc"))
        nested = settings_to_nested(self.server.settings)
        self.assertEqual(nested["email"]["password"], "private-authorization-code")
        self.assertEqual(nested["email"]["security"], "ssl")
        from hdu_seat.config import Settings
        restored = Settings.from_dict(nested)
        self.assertEqual(restored.email.password, "private-authorization-code")
        self.assertEqual(settings_to_dict(restored)["smtp_password"], "")

    def test_unrelated_save_preserves_mail_settings(self):
        self.server.save_config(self.email_config(cookie="sid=abc"))
        self.server.save_config({"cookie": "sid=def", "seat_ids": ["008"]})
        self.assertTrue(self.server.settings.email.enabled)
        self.assertEqual(self.server.settings.email.password, "private-authorization-code")
        self.assertEqual(self.server.settings.email.recipient, "phone@example.test")

    def test_cookie_is_still_required_to_query_or_book(self):
        self.server.save_config(self.email_config())
        with self.assertRaisesRegex(HDUClientError, "Cookie"):
            self.server.use_config(self.email_config(smtp_password=""))


class ServerEmailNotificationTests(unittest.TestCase):
    setUp = ServerEmailConfigTests.setUp
    tearDown = ServerEmailConfigTests.tearDown
    email_config = ServerEmailConfigTests.email_config

    def test_test_email_does_not_require_cookie_or_enable_booking_notifications(self):
        with patch("hdu_seat.notification.smtplib.SMTP_SSL") as smtp:
            smtp.return_value.send_message.return_value = {}
            result = self.server.test_email(self.email_config(email_enabled=False))
        self.assertEqual(result["status"], "sent")
        self.assertTrue(result["message"])
        self.assertTrue(result["at"])
        smtp.return_value.login.assert_called_once_with(
            "sender@example.test", "private-authorization-code",
        )
        self.assertFalse(self.server.settings.email.enabled)
        self.assertEqual(self.server.snapshot()["notification"]["status"], "sent")

    def test_test_email_uses_saved_password_when_form_leaves_it_blank(self):
        self.server.save_config(self.email_config())
        with patch("hdu_seat.notification.smtplib.SMTP_SSL") as smtp:
            smtp.return_value.send_message.return_value = {}
            result = self.server.test_email(self.email_config(smtp_password=""))
        self.assertEqual(result["status"], "sent")
        smtp.return_value.login.assert_called_once_with(
            "sender@example.test", "private-authorization-code",
        )

    def test_test_email_failure_is_observable_and_does_not_leak_smtp_response(self):
        import smtplib
        diagnostic = b"authorization=private-authorization-code sender@example.test sid=abc"
        with patch("hdu_seat.notification.smtplib.SMTP_SSL", side_effect=smtplib.SMTPAuthenticationError(535, diagnostic)):
            result = self.server.test_email(self.email_config())
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("private-authorization-code", result["message"])
        self.assertNotIn("sid=abc", result["message"])
        self.assertNotIn("sender@example.test", result["message"])
        self.assertEqual(self.server.snapshot()["notification"]["status"], "failed")

    def test_reserved_submits_only_booking_summary(self):
        self.server.save_config(self.email_config(cookie="sid=abc"))
        from unittest.mock import Mock
        self.server.notifier.submit = Mock(return_value=True)
        raw = "PRIVATE_UPSTREAM_RESPONSE sid=abc AUTHORIZATION_CODE"
        attempt = Attempt("2026-10-07T08:00:00", "reserved", raw, {
            "id": "21", "title": "021", "floor": "3", "area": "三楼东区",
        })
        self.server._handle_result(attempt, self.server.settings, "task-123")
        self.server.notifier.submit.assert_called_once()
        email, subject, body, key = self.server.notifier.submit.call_args.args
        self.assertEqual(key, "task-123")
        self.assertIs(email, self.server.settings.email)
        self.assertIn("021", body)
        self.assertNotIn(raw, body)
        self.assertNotIn("sid=abc", body)
        self.assertEqual(self.server.snapshot()["last_result"]["status"], "reserved")

    def test_non_reserved_attempts_never_submit_notification(self):
        self.server.save_config(self.email_config(cookie="sid=abc"))
        from unittest.mock import Mock
        self.server.notifier.submit = Mock(return_value=True)
        for status in ("dry-run", "empty", "error", "stopped"):
            with self.subTest(status=status):
                result = Attempt("now", status, "message", {"id": "21"})
                self.server._handle_result(result, self.server.settings, f"task-{status}")
        self.server.notifier.submit.assert_not_called()

    def test_disabled_notifications_never_submit_even_when_reserved(self):
        self.server.save_config(self.email_config(cookie="sid=abc", email_enabled=False))
        from unittest.mock import Mock
        self.server.notifier.submit = Mock(return_value=True)
        result = Attempt("now", "reserved", "ok", {"id": "21"})
        self.server._handle_result(result, self.server.settings, "task-disabled")
        self.server.notifier.submit.assert_not_called()

    def test_notification_submission_failure_does_not_change_reservation_result(self):
        self.server.save_config(self.email_config(cookie="sid=abc"))
        from unittest.mock import Mock
        self.server.notifier.submit = Mock(side_effect=RuntimeError("private-authorization-code"))
        result = Attempt("now", "reserved", "ok", {"id": "21"})
        data = self.server._handle_result(result, self.server.settings, "task-submission-error")
        self.assertEqual(data["status"], "reserved")
        state = self.server.snapshot()
        self.assertEqual(state["last_result"]["status"], "reserved")
        self.assertEqual(state["notification"]["status"], "failed")
        self.assertNotIn("private-authorization-code", state["notification"]["message"])

    def test_smtp_retries_only_mail_and_never_reserves_again(self):
        import threading
        self.server.save_config(self.email_config(cookie="sid=abc"))
        self.server.notifier.retry_delays = (0, 0)
        completed = threading.Event()
        previous = self.server.notifier.on_status

        def on_status(status):
            previous(status)
            if status["status"] == "failed":
                completed.set()

        self.server.notifier.on_status = on_status
        result = Attempt("now", "reserved", "ok", {"id": "21"})
        with patch("hdu_seat.notification.smtplib.SMTP_SSL", side_effect=TimeoutError("private-authorization-code")) as smtp:
            with patch("hdu_seat.server.SeatHunter") as hunter:
                hunter.return_value.run_once.return_value = result
                self.server.running = True
                self.server._run_loop(self.server.settings)
                self.assertTrue(completed.wait(timeout=2))
                hunter.return_value.run_once.assert_called_once_with(dry_run=False)
            self.assertEqual(smtp.call_count, 3)
        state = self.server.snapshot()
        self.assertFalse(state["running"])
        self.assertEqual(state["last_result"]["status"], "reserved")
        self.assertEqual(len(state["history"]), 1)
        self.assertEqual(state["notification"]["status"], "failed")
        self.assertNotIn("private-authorization-code", state["notification"]["message"])

    def test_successful_run_once_and_dry_run_use_the_result_handler(self):
        self.server.save_config(self.email_config(cookie="sid=abc"))
        from unittest.mock import Mock
        self.server.notifier.submit = Mock(return_value=True)
        result = Attempt("now", "reserved", "ok", {"id": "21"})
        with patch("hdu_seat.server.SeatHunter") as hunter:
            hunter.return_value.run_once.return_value = result
            data = self.server.run_once(self.server.settings, dry_run=False)
        self.assertEqual(data["status"], "reserved")
        self.server.notifier.submit.assert_called_once()
        self.server.notifier.submit.reset_mock()
        with patch("hdu_seat.server.SeatHunter") as hunter:
            hunter.return_value.run_once.return_value = Attempt("now", "dry-run", "matching", {"id": "21"})
            data = self.server.run_once(self.server.settings, dry_run=True)
            hunter.return_value.run_once.assert_called_once_with(dry_run=True)
        self.assertEqual(data["status"], "dry-run")
        self.server.notifier.submit.assert_not_called()


class ServerEmailHTTPTests(unittest.TestCase):
    def setUp(self):
        import threading
        from hdu_seat.server import create_http_server
        import tempfile
        from pathlib import Path
        self.temp = tempfile.TemporaryDirectory(prefix="_test_server_email_http_", dir=Path(__file__).resolve().parent.parent)
        self.app = SeatWebServer(Path(self.temp.name) / "config.json")
        self.app._persist = lambda _: None
        self.http = create_http_server(self.app, host="127.0.0.1", port=0)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.http.server_port}"

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)
        self.app.notifier.close()
        self.temp.cleanup()

    def request(self, path, body=None):
        import json
        import urllib.error
        import urllib.request
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path, data=data,
            headers={"Content-Type": "application/json"},
            method="GET" if body is None else "POST",
        )
        try:
            response = urllib.request.urlopen(request, timeout=2)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, json.load(response)

    def email_config(self, **changes):
        values = {
            "email_enabled": True, "smtp_host": "smtp.example.test", "smtp_port": 465,
            "smtp_security": "ssl", "smtp_username": "sender@example.test",
            "smtp_password": "private-authorization-code", "email_sender": "sender@example.test",
            "email_recipient": "phone@example.test",
        }
        values.update(changes)
        return values

    def test_email_api_can_save_and_test_without_cookie_and_never_returns_password(self):
        code, saved = self.request("/api/config", self.email_config())
        self.assertEqual(code, 200)
        self.assertEqual(saved["smtp_password"], "")
        self.assertTrue(saved["smtp_password_set"])
        with patch("hdu_seat.notification.smtplib.SMTP_SSL") as smtp:
            smtp.return_value.send_message.return_value = {}
            code, result = self.request("/api/email/test", self.email_config(smtp_password=""))
        self.assertEqual(code, 200)
        self.assertEqual(result["status"], "sent")
        self.assertTrue(result["message"])
        self.assertTrue(result["at"])
        code, state = self.request("/api/status")
        self.assertEqual(code, 200)
        self.assertEqual(state["notification"]["status"], "sent")
        self.assertNotIn("private-authorization-code", str(state))
        code, result = self.request("/api/start", self.email_config(smtp_password=""))
        self.assertEqual(code, 400)
        self.assertIn("Cookie", result["error"])

    def test_mail_credentials_survive_real_save_and_restart_without_cookie(self):
        import json
        self.app._persist = SeatWebServer._persist.__get__(self.app, SeatWebServer)
        code, saved = self.request("/api/config", self.email_config())
        self.assertEqual(code, 200)
        self.assertEqual(saved["smtp_password"], "")
        persisted = json.loads(self.app.config_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["email"]["password"], "private-authorization-code")
        restored = SeatWebServer(self.app.config_path)
        try:
            self.assertEqual(restored.settings.cookie, "")
            self.assertEqual(restored.settings.email.password, "private-authorization-code")
            with patch("hdu_seat.notification.smtplib.SMTP_SSL") as smtp:
                smtp.return_value.send_message.return_value = {}
                result = restored.test_email(self.email_config(smtp_password=""))
            self.assertEqual(result["status"], "sent")
            smtp.return_value.login.assert_called_once_with(
                "sender@example.test", "private-authorization-code",
            )
        finally:
            restored.close()

    def test_configuration_write_failure_is_reported_without_false_saved_state(self):
        self.app._persist = SeatWebServer._persist.__get__(self.app, SeatWebServer)
        with patch("hdu_seat.server.os.replace", side_effect=PermissionError("private-authorization-code sensitive-path")):
            code, result = self.request("/api/config", self.email_config())
        self.assertEqual(code, 400)
        self.assertNotIn("private-authorization-code", str(result))
        self.assertNotIn("sensitive-path", str(result))
        self.assertFalse(self.app.settings.email.enabled)
        self.assertEqual(self.app.settings.email.password, "")

    def test_email_api_auth_failure_contains_no_raw_smtp_diagnostics(self):
        import smtplib
        with patch("hdu_seat.notification.smtplib.SMTP_SSL", side_effect=smtplib.SMTPAuthenticationError(535, b"private-authorization-code sid=abc")):
            code, result = self.request("/api/email/test", self.email_config())
        self.assertIn(code, (200, 400))
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("private-authorization-code", str(result))
        self.assertNotIn("sid=abc", str(result))


if __name__ == "__main__":
    unittest.main()

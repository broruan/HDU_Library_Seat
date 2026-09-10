import unittest
from datetime import datetime
from unittest.mock import patch

from hdu_seat.client import BEIJING_TZ, HDUClientError, ZhishulibClient
from hdu_seat.config import Booking, Settings, SpaceCategory


class ClientTimeTests(unittest.TestCase):
    def test_explicit_time_is_interpreted_as_beijing_time(self):
        settings = Settings(
            base_url="https://example.test",
            cookie="sid=x",
            space_category=SpaceCategory(591, 3),
            booking=Booking(date="2099-09-04", start_time="08:00", duration_hours=4),
        )
        begin, duration = ZhishulibClient(settings)._begin_duration()
        expected = int(datetime(2099, 9, 4, 8, tzinfo=BEIJING_TZ).timestamp())
        self.assertEqual(begin, expected)
        self.assertEqual(duration, 14400)

    def test_ended_explicit_time_is_rejected_locally(self):
        settings = Settings(
            base_url="https://example.test",
            cookie="sid=x",
            space_category=SpaceCategory(591, 3),
            booking=Booking(date="2000-01-01", start_time="08:00"),
        )
        with self.assertRaisesRegex(HDUClientError, "预约时段已结束"):
            ZhishulibClient(settings)._begin_duration()

    def test_started_but_not_ended_time_uses_remaining_window(self):
        settings = Settings(
            base_url="https://example.test",
            cookie="sid=x",
            space_category=SpaceCategory(591, 3),
            booking=Booking(date="2026-09-09", start_time="15:00", duration_hours=4),
        )
        now = int(datetime(2026, 9, 9, 15, 1, 5, tzinfo=BEIJING_TZ).timestamp())
        configured_end = int(datetime(2026, 9, 9, 19, 0, tzinfo=BEIJING_TZ).timestamp())

        with patch("hdu_seat.client.time.time", return_value=now):
            begin, duration = ZhishulibClient(settings)._begin_duration()

        self.assertEqual(begin, now)
        self.assertEqual(duration, configured_end - now)

    def test_non_hour_start_is_rejected(self):
        settings = Settings(
            base_url="https://example.test",
            cookie="sid=x",
            space_category=SpaceCategory(591, 3),
            booking=Booking(date="2099-01-01", start_time="18:33"),
        )
        with self.assertRaisesRegex(HDUClientError, "仅支持整点"):
            ZhishulibClient(settings)._begin_duration()


if __name__ == "__main__":
    unittest.main()

import unittest

from hdu_seat.config import SeatRule
from hdu_seat.selector import choose, matches


class SelectorTests(unittest.TestCase):
    def test_filters_unavailable_and_prefers_lowest_id(self):
        seats = [
            {"id": "2", "title": "002", "state": 2},
            {"id": "3", "title": "003", "state": 1},
            {"id": "1", "title": "001", "state": 0},
        ]
        self.assertEqual(choose(seats, SeatRule())["id"], "1")

    def test_keyword_and_door_rule(self):
        rule = SeatRule(keywords=["window"], avoid_near_door=True)
        self.assertFalse(matches({"id": "1", "title": "window", "available": True, "nearDoor": True}, rule))
        self.assertTrue(matches({"id": "2", "title": "window", "available": True}, rule))

    def test_state_and_available_flags(self):
        self.assertTrue(matches({"id": "1", "state": 2}, SeatRule()))
        self.assertTrue(matches({"id": "0", "state": 0}, SeatRule()))
        self.assertTrue(matches({"id": "2", "available": True}, SeatRule()))
        self.assertFalse(matches({"id": "3", "state": 1}, SeatRule()))

    def test_seat_ids_match_id_or_title(self):
        rule = SeatRule(seat_ids=["001"])
        self.assertTrue(matches({"id": "42", "title": "001", "state": 2}, rule))

    def test_exact_internal_id_overrides_stale_floor_preference(self):
        rule = SeatRule(seat_ids=["62001"], preferred_floor=4)
        self.assertTrue(matches({"id": "62001", "title": "35", "floor": "6", "state": 0}, rule))

    def test_display_number_still_uses_floor_to_disambiguate(self):
        rule = SeatRule(seat_ids=["35"], preferred_floor=4)
        self.assertFalse(matches({"id": "62001", "title": "35", "floor": "6", "state": 0}, rule))
        self.assertTrue(matches({"id": "62002", "title": "35", "floor": "4", "state": 0}, rule))


if __name__ == "__main__":
    unittest.main()

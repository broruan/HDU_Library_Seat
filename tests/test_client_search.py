import unittest

from hdu_seat.client import BOOK_PATH, SEARCH_PATH, ZhishulibClient
from hdu_seat.config import Settings, SpaceCategory


class RecordingClient(ZhishulibClient):
    def __init__(self, response):
        super().__init__(Settings(
            base_url="https://example.test",
            cookie="sid=x",
            space_category=SpaceCategory(591, 3),
        ))
        self.response = response
        self.calls = []

    def _post(self, path, data=None, extra_headers=None):
        self.calls.append((path, data, extra_headers))
        return self.response


def component_response():
    order = {"beginTime": "4102444800", "duration": "3600", "num": "1"}
    user = {"id": "123"}
    room_a = {
        "info": {"title": "A区", "rank": "3"},
        "POIs": [
            {"id": "10", "title": "010", "state": "0"},
            {"id": "11", "title": "011", "state": "1"},
        ],
    }
    room_b = {
        "info": {"title": "B区四楼"},
        "POIs": [{"id": "20", "title": "020", "state": 2, "recommend": True}],
    }
    return {
        "ui_type": "ht.Seat.SysRecommendPage",
        "IsImgCode": "0",
        "data": room_a,
        "content": {"children": [{}, {}, {"children": {
            "seatMap": room_a, "orderInfo": order, "userInfo": user,
        }}]},
        "allContent": {"children": [{}, {}, {"children": {"children": [
            {"seatMap": room_a, "orderInfo": order, "userInfo": user},
            {"seatMap": room_b, "orderInfo": order, "userInfo": user},
        ]}}]},
    }


class ClientSearchTests(unittest.TestCase):
    def test_search_sends_top_level_form_fields(self):
        client = RecordingClient(component_response())
        client.search()

        path, data, _ = client.calls[0]
        self.assertEqual(path, SEARCH_PATH)
        self.assertNotIn("data", data)
        self.assertEqual(data["space_category"], {"category_id": 591, "content_id": 3})
        self.assertIn("beginTime", data)

    def test_component_response_extracts_all_rooms_and_order(self):
        client = RecordingClient(component_response())
        seats = client.seats()

        self.assertEqual([seat["id"] for seat in seats], ["10", "11", "20"])
        self.assertEqual([seat["available"] for seat in seats], [True, False, True])
        self.assertEqual(seats[0]["area"], "A区")
        self.assertEqual(seats[2]["floor"], "4")
        self.assertEqual(client._order["uid"], "123")
        self.assertFalse(client._order["img_code"])

    def test_legacy_data_seat_map_is_still_supported(self):
        client = RecordingClient({"CODE": "ok", "DATA": {
            "seatMap": {"POIs": [{"id": "1", "state": "2"}]},
            "orderInfo": {"beginTime": "4102444800", "duration": "3600", "num": "1"},
            "userInfo": {"id": "123"},
        }})
        self.assertEqual(client.seats()[0]["id"], "1")

    def test_reserve_sends_top_level_form_fields(self):
        client = RecordingClient({"CODE": "ok", "DATA": {"result": "success"}})
        client._order = {
            "begin_time": 4102444800,
            "duration": 3600,
            "num": 1,
            "uid": "123",
            "img_code": False,
        }
        client.reserve({"id": "10"})

        path, data, headers = client.calls[0]
        self.assertEqual(path, BOOK_PATH)
        self.assertNotIn("data", data)
        self.assertEqual(data["seatBookers"], ["123"])
        self.assertEqual(data["seats"], ["10"])
        self.assertIn("Api-Token", headers)


if __name__ == "__main__":
    unittest.main()

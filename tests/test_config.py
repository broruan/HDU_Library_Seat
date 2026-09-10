import os
import shutil
import unittest
from pathlib import Path

from hdu_seat.config import load_settings

# 沙箱下 tempfile.TemporaryDirectory 的 0o700 目录会被文件沙箱拦截，
# 这里改用仓库根目录下用 Path.mkdir 创建的临时目录。
ROOT = Path(__file__).resolve().parent.parent


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self._tmp = ROOT / f"_test_config_{os.getpid()}"
        self._tmp.mkdir(exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write(self, text: str) -> Path:
        path = self._tmp / "config.json"
        path.write_text(text, encoding="utf-8")
        return path

    def test_cookie_can_come_from_environment(self):
        old = os.environ.get("HDU_LIBRARY_COOKIE")
        try:
            os.environ["HDU_LIBRARY_COOKIE"] = "sid=from-env"
            path = self._write(
                '{"base_url":"https://example.test", "space_category":{"category_id":591,"content_id":3},'
                ' "rule":{"keywords":["window"]}}',
            )
            settings = load_settings(path)
            self.assertEqual(settings.cookie, "sid=from-env")
            self.assertEqual(settings.space_category.category_id, 591)
            self.assertEqual(settings.rule.keywords, ["window"])
        finally:
            if old is None:
                os.environ.pop("HDU_LIBRARY_COOKIE", None)
            else:
                os.environ["HDU_LIBRARY_COOKIE"] = old

    def test_space_category_is_required(self):
        path = self._write('{"base_url":"https://example.test", "cookie":"sid=x"}')
        with self.assertRaises(ValueError):
            load_settings(path)


if __name__ == "__main__":
    unittest.main()

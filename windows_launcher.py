"""Entry point for the standalone Windows release."""

import argparse
import os
from pathlib import Path

from hdu_seat.server import serve


def main() -> int:
    parser = argparse.ArgumentParser(description="HDU Library Seat Helper")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    config_path = args.config
    if config_path is None:
        data_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "HDU-Library-Seat"
        data_dir.mkdir(parents=True, exist_ok=True)
        config_path = data_dir / "config.json"
    print("HDU Library Seat Helper / 杭电图书馆座位助手")
    print("浏览器关闭后程序仍会运行。退出请在此窗口按 Ctrl+C，或关闭此窗口。")
    try:
        serve(config_path, port=args.port, open_browser=not args.no_browser)
    except OSError as exc:
        print(f"启动失败: {exc}")
        if not args.no_browser:
            input("按回车退出…")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Desktop entry point for the Ubuntu packages."""

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
        config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        if not config_home.is_absolute():
            config_home = Path.home() / ".config"
        data_dir = config_home / "hdu-library-seat"
        data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        config_path = data_dir / "config.json"
    print("HDU Library Seat Helper / 杭电图书馆座位助手")
    print("关闭浏览器后程序仍会运行。在此终端按 Ctrl+C 可退出。")
    try:
        serve(config_path, port=args.port, open_browser=not args.no_browser)
    except OSError as exc:
        print(f"启动失败: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

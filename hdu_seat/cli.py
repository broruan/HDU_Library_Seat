from __future__ import annotations

import argparse
import json
import logging
import shutil
from pathlib import Path

from .client import HDUClientError, ZhishulibClient
from .config import load_settings
from .hunter import SeatHunter
from .server import serve


def main() -> int:
    parser = argparse.ArgumentParser(description="HDU library seat helper")
    parser.add_argument("-c", "--config", default="config.json")
    parser.add_argument("--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-config", help="从模板创建本地配置文件")
    sub.add_parser("validate-config")
    sub.add_parser("list")
    once = sub.add_parser("once")
    once.add_argument("--dry-run", action="store_true")
    run = sub.add_parser("run")
    run.add_argument("--dry-run", action="store_true")
    web = sub.add_parser("serve", help="启动本地 Web 可视化抢座面板")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")

    if args.command == "init-config":
        target = Path(args.config)
        if target.exists():
            print(f"配置文件已存在，未覆盖: {target}")
            return 1
        template = Path(__file__).resolve().parent.parent / "config.example.json"
        if not template.exists():
            print(f"找不到配置模板: {template}")
            return 1
        shutil.copyfile(template, target)
        print(f"已创建 {target}，请填写 base_url、cookie 和 space_category 后再运行。")
        return 0

    # Web 面板无需预先有合法配置文件：缺失或无效时用默认值启动，在页面上填写即可。
    if args.command == "serve":
        serve(args.config, args.host, args.port)
        return 0

    try:
        settings = load_settings(args.config)
    except FileNotFoundError:
        print(f"找不到配置文件: {args.config}")
        print(f"先运行 `python -m hdu_seat -c {args.config} init-config` 创建模板。")
        return 2
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"配置文件无效: {exc}")
        return 2

    if args.command == "validate-config":
        print(json.dumps({
            "base_url": settings.base_url,
            "cookie": "<configured>",
            "space_category": settings.space_category.__dict__,
            "booking": settings.booking.__dict__,
            "rule": settings.rule.__dict__,
        }, ensure_ascii=False, indent=2))
        return 0

    client = ZhishulibClient(settings)
    if args.command == "list":
        try:
            seats = client.seats()
        except HDUClientError as exc:
            print(f"查询座位失败: {exc}")
            return 1
        print(json.dumps([client.public_seat(x) for x in seats], ensure_ascii=False, indent=2))
    elif args.command in {"once", "run"}:
        result = SeatHunter(settings, client).run(dry_run=args.dry_run, stop_on_success=True)
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
        return 0 if result.status in {"reserved", "dry-run"} else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from .client import HDUClientError, ZhishulibClient
from .config import Settings
from .selector import choose, is_available

log = logging.getLogger(__name__)


@dataclass
class Attempt:
    at: str
    status: str
    message: str
    seat: dict[str, Any] | None = None


class SeatHunter:
    def __init__(
        self,
        settings: Settings,
        client: ZhishulibClient | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        should_stop: Callable[[], bool] | None = None,
        on_seats: Callable[[list[dict[str, Any]]], None] | None = None,
    ):
        self.settings = settings
        self.client = client or ZhishulibClient(settings)
        self.sleeper = sleeper
        self.should_stop = should_stop or (lambda: False)
        self.on_seats = on_seats or (lambda _: None)
        self.history: list[Attempt] = []

    def _record(self, status: str, message: str, seat: dict[str, Any] | None = None) -> None:
        self.history.append(Attempt(datetime.now().isoformat(timespec="seconds"), status, message, seat))

    def run_once(self, dry_run: bool = False) -> Attempt:
        try:
            seats = self.client.seats()
            self.on_seats(seats)
            seat = choose(seats, self.settings.rule)
        except HDUClientError as exc:
            result = Attempt(datetime.now().isoformat(timespec="seconds"), "error", str(exc))
            self.history.append(result)
            return result
        if seat is None:
            available = [candidate for candidate in seats if is_available(candidate)]
            requested = {str(value) for value in self.settings.rule.seat_ids}
            targets = [candidate for candidate in seats if requested and (
                str(candidate.get("id", candidate.get("seatId", candidate.get("seat_id", "")))) in requested
                or str(candidate.get("title", candidate.get("name", candidate.get("label", "")))) in requested
            )]
            floor = self.settings.rule.preferred_floor
            floor_targets = [candidate for candidate in targets if floor is None or str(candidate.get("floor", "")) == str(floor)]
            if floor_targets and not any(is_available(candidate) for candidate in floor_targets):
                areas = "、".join(sorted({str(candidate.get("area") or f"{candidate.get('floor', '?')}楼") for candidate in floor_targets}))
                message = f"目标座位在 {areas} 当前已占用或关闭，将继续重试"
            elif targets and floor is not None and not floor_targets:
                message = f"找到了该座位编号，但不在设置的 {floor} 楼，请检查楼层或点击具体座位卡片"
            elif available:
                message = f"当前有 {len(available)} 个可约座位，但都未命中指定座位或筛选条件"
            elif self.settings.rule.seat_ids:
                message = "指定座位在当前时段不可预约，将继续重试"
            else:
                message = "当前时段没有可预约座位，将继续重试"
            result = Attempt(datetime.now().isoformat(timespec="seconds"), "empty", message)
            self.history.append(result)
            return result
        if dry_run:
            result = Attempt(datetime.now().isoformat(timespec="seconds"), "dry-run", "matching seat found", seat)
            self.history.append(result)
            return result
        try:
            response = self.client.reserve(seat)
            result = Attempt(datetime.now().isoformat(timespec="seconds"), "reserved", str(response), seat)
        except HDUClientError as exc:
            result = Attempt(datetime.now().isoformat(timespec="seconds"), "error", str(exc), seat)
        self.history.append(result)
        return result

    def run(self, dry_run: bool = False, stop_on_success: bool = True) -> Attempt:
        last = Attempt(datetime.now().isoformat(timespec="seconds"), "error", "not started")
        for attempt in range(1, self.settings.max_attempts + 1):
            if self.should_stop():
                last = Attempt(datetime.now().isoformat(timespec="seconds"), "stopped", "手动停止")
                self.history.append(last)
                break
            last = self.run_once(dry_run=dry_run)
            log.info("attempt=%s status=%s message=%s", attempt, last.status, last.message)
            if last.status in {"reserved", "dry-run"} and stop_on_success:
                break
            if attempt < self.settings.max_attempts:
                self.sleeper(self.settings.poll_interval)
        return last

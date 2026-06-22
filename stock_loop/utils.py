from __future__ import annotations

import csv
import fcntl
import json
import math
import shutil
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


class LockUnavailable(RuntimeError):
    pass


@contextmanager
def exclusive_file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as file:
        try:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LockUnavailable("已有一个每日任务正在运行，本次执行已跳过。") from exc
        try:
            file.seek(0)
            file.truncate()
            file.write(str(datetime.now().astimezone()))
            file.flush()
            yield
        finally:
            fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def ensure_project_dirs(root: Path) -> None:
    directories = [
        "data/raw",
        "data/processed",
        "data/market_snapshot",
        "runs",
        "reviews/weekly_review",
        "reviews/monthly_review",
        "reviews/failure_cases",
        "metrics",
        "strategy_versions",
        "output",
    ]
    for relative in directories:
        (root / relative).mkdir(parents=True, exist_ok=True)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def copy_text(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(row.get(key)) for key in fieldnames})


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return value


def safe_float(value: Any, default: float | None = None) -> float | None:
    if value in (None, "", "None", "null", "暂无", "--"):
        return default
    try:
        return float(str(value).replace("%", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def business_days(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def previous_business_day(value: date) -> date:
    current = value
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def markdown_table(headers: list[str], rows: Iterable[Iterable[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        cells = [str("" if item is None else item).replace("|", "\\|").replace("\n", " ") for item in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def pct(value: float | None, digits: int = 2) -> str:
    return "暂无" if value is None else f"{value:.{digits}f}%"


def list_run_dates(root: Path) -> list[date]:
    values: list[date] = []
    for path in (root / "runs").glob("????-??-??"):
        if path.is_dir():
            try:
                values.append(parse_date(path.name))
            except ValueError:
                continue
    return sorted(values)


def now_text() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")

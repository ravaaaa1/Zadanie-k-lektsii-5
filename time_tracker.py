"""Учёт интервалов времени для TaskManager, включая активные таймеры."""
from datetime import datetime, timezone
from collections.abc import Callable
import sqlite3

from task_manager import TaskManager


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TimeTracker:
    """Один активный таймер на задачу. Разные задачи могут идти параллельно."""

    def __init__(self, manager: TaskManager, clock: Callable[[], datetime] = utc_now):
        self.manager = manager
        self.clock = clock
        self.connection = manager.connection
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS time_entries (
                entry_id INTEGER PRIMARY KEY,
                task_id INTEGER NOT NULL REFERENCES tasks(task_id),
                started_at TEXT NOT NULL, stopped_at TEXT,
                CHECK(stopped_at IS NULL OR stopped_at >= started_at));
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_timer
            ON time_entries(task_id) WHERE stopped_at IS NULL;
        """)

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Часы должны возвращать время с часовым поясом")
        return now.astimezone(timezone.utc)

    def start_timer(self, task_id: int) -> int:
        self.manager.get_task(task_id)
        now = self._now()
        try:
            with self.connection:
                row = self.connection.execute(
                    "INSERT INTO time_entries(task_id,started_at) VALUES (?,?)",
                    (task_id, now.isoformat()))
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Таймер задачи {task_id} уже запущен") from error
        return row.lastrowid

    def stop_timer(self, task_id: int) -> float:
        self.manager.get_task(task_id)
        # BEGIN IMMEDIATE prevents competing processes from stopping the same interval.
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute(
                "SELECT * FROM time_entries WHERE task_id=? AND stopped_at IS NULL", (task_id,)).fetchone()
            if row is None:
                raise ValueError(f"Таймер задачи {task_id} не запущен")
            now = self._now()
            duration = (now - datetime.fromisoformat(row['started_at'])).total_seconds()
            if duration < 0:
                raise ValueError("Время остановки раньше времени запуска; проверьте системные часы")
            self.connection.execute("UPDATE time_entries SET stopped_at=? WHERE entry_id=?",
                                    (now.isoformat(), row['entry_id']))
        return duration

    def generate_report(self, task_id: int | None = None) -> dict:
        """Один снимок времени для всех строк. Суммы включают текущий интервал."""
        tasks = [self.manager.get_task(task_id)] if task_id is not None else self.manager.list_tasks()
        now = self._now()
        rows = []
        for task in tasks:
            entries = self.connection.execute(
                "SELECT * FROM time_entries WHERE task_id=? ORDER BY entry_id", (task.task_id,)).fetchall()
            seconds = 0.0
            active = False
            for entry in entries:
                active = active or entry['stopped_at'] is None
                end = datetime.fromisoformat(entry['stopped_at']) if entry['stopped_at'] else now
                duration = (end - datetime.fromisoformat(entry['started_at'])).total_seconds()
                if duration < 0:
                    raise ValueError("Текущее время раньше запуска таймера; проверьте системные часы")
                seconds += duration
            rows.append({"task_id": task.task_id, "title": task.title,
                         "status": task.status.value,
                         "assignee": task.assignee.name if task.assignee else None,
                         "sessions": len(entries), "active": active,
                         "total_seconds": seconds, "total_hours": seconds / 3600})
        return {"generated_at": now.isoformat(), "tasks": rows,
                "total_seconds": sum(row['total_seconds'] for row in rows)}

    def get_total_time(self, task_id: int) -> float:
        return self.generate_report(task_id)['total_seconds']

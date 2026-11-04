"""Модели системы задач из лекции №5."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Priority(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class Status(Enum):
    TODO = "To Do"
    IN_PROGRESS = "In Progress"
    REVIEW = "Review"
    DONE = "Done"


@dataclass(frozen=True)
class User:
    user_id: int
    name: str
    email: str


@dataclass(frozen=True)
class Task:
    task_id: int
    title: str
    description: str
    priority: Priority
    due_date: datetime
    status: Status = Status.TODO
    assignee: User | None = None

    def is_overdue(self) -> bool:
        return self.status != Status.DONE and datetime.now(self.due_date.tzinfo) > self.due_date

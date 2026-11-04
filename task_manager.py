"""Хранилище задач; публичные методы совместимы с примером лекции."""
import sqlite3
from datetime import datetime
from pathlib import Path

from system_design import Priority, Status, Task, User


class TaskManager:
    def __init__(self, database: str | Path = ":memory:"):
        self.connection = sqlite3.connect(database)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE);
            CREATE TABLE IF NOT EXISTS tasks (
                task_id INTEGER PRIMARY KEY, title TEXT NOT NULL,
                description TEXT NOT NULL, priority INTEGER NOT NULL,
                due_date TEXT NOT NULL, status TEXT NOT NULL,
                assignee_id INTEGER REFERENCES users(user_id));
        """)

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def create_user(self, name: str, email: str) -> User:
        name, email = name.strip(), email.strip()
        if not name or not email or "@" not in email:
            raise ValueError("Укажите имя и email с символом @")
        try:
            with self.connection:
                row = self.connection.execute(
                    "INSERT INTO users(name,email) VALUES (?,?)", (name, email))
        except sqlite3.IntegrityError as error:
            raise ValueError("Пользователь с таким email уже существует") from error
        return User(row.lastrowid, name, email)

    def create_task(self, title: str, description: str,
                    priority: Priority, due_date: datetime) -> Task:
        title = title.strip()
        if not title:
            raise ValueError("Название задачи не должно быть пустым")
        if not isinstance(priority, Priority) or not isinstance(due_date, datetime):
            raise ValueError("Некорректный приоритет или срок задачи")
        with self.connection:
            row = self.connection.execute(
                "INSERT INTO tasks(title,description,priority,due_date,status) VALUES (?,?,?,?,?)",
                (title, description, priority.value, due_date.isoformat(), Status.TODO.value))
        return self.get_task(row.lastrowid)

    def get_task(self, task_id: int) -> Task:
        row = self.connection.execute("""
            SELECT t.*,u.name,u.email FROM tasks t
            LEFT JOIN users u ON u.user_id=t.assignee_id WHERE t.task_id=?
        """, (task_id,)).fetchone()
        if row is None:
            raise ValueError(f"Задача {task_id} не найдена")
        user = User(row['assignee_id'], row['name'], row['email']) if row['assignee_id'] else None
        return Task(row['task_id'], row['title'], row['description'], Priority(row['priority']),
                    datetime.fromisoformat(row['due_date']), Status(row['status']), user)

    def list_tasks(self) -> list[Task]:
        return [self.get_task(row[0]) for row in self.connection.execute(
            "SELECT task_id FROM tasks ORDER BY task_id")]

    def assign_task(self, task_id: int, user_id: int) -> bool:
        if not self.connection.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone():
            return False
        with self.connection:
            result = self.connection.execute(
                "UPDATE tasks SET assignee_id=?,status=? WHERE task_id=?",
                (user_id, Status.IN_PROGRESS.value, task_id))
        return result.rowcount == 1

    def update_status(self, task_id: int, status: Status):
        self.get_task(task_id)
        if not isinstance(status, Status):
            raise ValueError("Некорректный статус")
        with self.connection:
            self.connection.execute("UPDATE tasks SET status=? WHERE task_id=?", (status.value, task_id))

    def get_user_tasks(self, user_id: int) -> list[Task]:
        return [t for t in self.list_tasks() if t.assignee and t.assignee.user_id == user_id]

    def get_overdue_tasks(self) -> list[Task]:
        return [t for t in self.list_tasks() if t.is_overdue()]

    def generate_report(self) -> dict:
        tasks = self.list_tasks()
        return {"total_tasks": len(tasks), "overdue_tasks": len(self.get_overdue_tasks()),
                "status_distribution": {s.value: sum(t.status == s for t in tasks) for s in Status}}

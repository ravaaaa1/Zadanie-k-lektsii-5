"""Консольный интерфейс: python main.py --help."""
import argparse
import csv
import io
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from system_design import Priority, Status
from task_manager import TaskManager
from time_tracker import TimeTracker


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Учёт времени задач — задание к лекции 5")
    parser.add_argument('--db', default='tasks.db', help='Файл SQLite (по умолчанию tasks.db)')
    commands = parser.add_subparsers(dest='command', required=True)
    user = commands.add_parser('user', help='Создать пользователя')
    user.add_argument('name')
    user.add_argument('email')
    task = commands.add_parser('task', help='Создать задачу')
    task.add_argument('title')
    task.add_argument('--description', default='')
    task.add_argument('--priority', choices=[p.name for p in Priority], default='MEDIUM')
    task.add_argument('--due', required=True, type=datetime.fromisoformat, help='Срок: ГГГГ-ММ-ДД')
    commands.add_parser('list', help='Показать задачи')
    assign = commands.add_parser('assign', help='Назначить исполнителя')
    assign.add_argument('task_id', type=int)
    assign.add_argument('user_id', type=int)
    status = commands.add_parser('status', help='Изменить статус')
    status.add_argument('task_id', type=int)
    status.add_argument('status', choices=[s.name for s in Status])
    for name in ('start', 'stop'):
        command = commands.add_parser(name, help='Запустить/остановить таймер')
        command.add_argument('task_id', type=int)
    report = commands.add_parser('report', help='Отчёт по времени')
    report.add_argument('--task', type=int)
    report.add_argument('--format', choices=['text', 'json', 'csv'], default='text')
    report.add_argument('--output', type=Path, help='Сохранить отчёт в файл UTF-8')
    return parser


def render_report(report: dict, format_name: str) -> str:
    if format_name == 'json':
        return json.dumps(report, ensure_ascii=False, indent=2)
    if format_name == 'csv':
        stream = io.StringIO(newline='')
        fields = ['task_id', 'title', 'status', 'assignee', 'sessions', 'active', 'total_seconds', 'total_hours']
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(report['tasks'])
        return stream.getvalue()
    lines = [f"Отчёт на {report['generated_at']} (UTC)"]
    for row in report['tasks']:
        lines.append(f"#{row['task_id']} {row['title']}: {row['total_seconds']:.3f} сек.; "
                     f"сеансов: {row['sessions']}; таймер: {'работает' if row['active'] else 'остановлен'}")
    lines.append(f"Всего: {report['total_seconds']:.3f} сек.")
    return '\n'.join(lines)


def main(argv=None) -> int:
    args = make_parser().parse_args(argv)
    try:
        with TaskManager(args.db) as manager:
            tracker = TimeTracker(manager)
            if args.command == 'user':
                print(f"Создан пользователь #{manager.create_user(args.name, args.email).user_id}")
            elif args.command == 'task':
                task = manager.create_task(args.title, args.description, Priority[args.priority], args.due)
                print(f"Создана задача #{task.task_id}: {task.title}")
            elif args.command == 'list':
                for task in manager.list_tasks():
                    print(f"#{task.task_id} {task.title} | {task.status.value} | "
                          f"{task.assignee.name if task.assignee else 'Без исполнителя'}")
            elif args.command == 'assign':
                if not manager.assign_task(args.task_id, args.user_id):
                    raise ValueError('Задача или пользователь не найдены')
                print('Исполнитель назначен')
            elif args.command == 'status':
                manager.update_status(args.task_id, Status[args.status])
                print('Статус обновлён')
            elif args.command == 'start':
                tracker.start_timer(args.task_id)
                print(f'Таймер задачи #{args.task_id} запущен')
            elif args.command == 'stop':
                print(f'Учтено: {tracker.stop_timer(args.task_id):.3f} сек.')
            elif args.command == 'report':
                text = render_report(tracker.generate_report(args.task), args.format)
                if args.output:
                    args.output.write_text(text, encoding='utf-8-sig' if args.format == 'csv' else 'utf-8')
                    print(f'Отчёт сохранён: {args.output}')
                else:
                    print(text)
        return 0
    except (ValueError, sqlite3.Error, OSError) as error:
        print(f'Ошибка: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

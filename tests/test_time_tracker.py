import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path

from main import main, render_report
from system_design import Priority, Status
from task_manager import TaskManager
from time_tracker import TimeTracker


class TimeTrackerTests(unittest.TestCase):
    def setUp(self):
        self.manager = TaskManager()
        self.addCleanup(self.manager.close)
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.tracker = TimeTracker(self.manager, lambda: self.now)
        self.task = self.manager.create_task('Задача', 'Описание', Priority.HIGH, self.now)

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)

    def test_start_stop(self):
        self.tracker.start_timer(1)
        self.advance(12.5)
        self.assertEqual(self.tracker.stop_timer(1), 12.5)
        self.advance(20)
        self.assertEqual(self.tracker.get_total_time(1), 12.5)

    def test_multiple_sessions(self):
        for seconds in (10, 20, 30):
            self.tracker.start_timer(1)
            self.advance(seconds)
            self.tracker.stop_timer(1)
            self.advance(100)
        self.assertEqual(self.tracker.get_total_time(1), 60)
        self.assertEqual(self.tracker.generate_report()['tasks'][0]['sessions'], 3)

    def test_active_session_in_report(self):
        self.tracker.start_timer(1)
        self.advance(3600)
        row = self.tracker.generate_report()['tasks'][0]
        self.assertEqual(row['total_hours'], 1)
        self.assertTrue(row['active'])
        self.assertEqual(self.tracker.get_total_time(1), 3600)

    def test_duplicate_start_does_not_reset_timer(self):
        self.tracker.start_timer(1)
        self.advance(10)
        with self.assertRaises(ValueError):
            self.tracker.start_timer(1)
        self.assertEqual(self.tracker.stop_timer(1), 10)

    def test_stop_without_start(self):
        with self.assertRaises(ValueError):
            self.tracker.stop_timer(1)

    def test_unknown_task(self):
        for operation in (self.tracker.start_timer, self.tracker.stop_timer, self.tracker.get_total_time):
            with self.subTest(operation=operation.__name__), self.assertRaises(ValueError):
                operation(999)

    def test_empty_report(self):
        with TaskManager() as empty:
            report = TimeTracker(empty).generate_report()
        self.assertEqual(report['tasks'], [])
        self.assertEqual(report['total_seconds'], 0)

    def test_task_without_intervals(self):
        self.assertEqual(self.tracker.get_total_time(1), 0)

    def test_independent_tasks_and_filter(self):
        self.manager.create_task('Вторая', '', Priority.LOW, self.now)
        self.tracker.start_timer(1)
        self.advance(10)
        self.tracker.start_timer(2)
        self.advance(20)
        self.assertEqual(self.tracker.generate_report()['total_seconds'], 50)
        report = self.tracker.generate_report(2)
        self.assertEqual(len(report['tasks']), 1)
        self.assertEqual(report['total_seconds'], 20)

    def test_clock_rollback_preserves_active_timer(self):
        self.tracker.start_timer(1)
        self.advance(-10)
        with self.assertRaises(ValueError):
            self.tracker.stop_timer(1)
        with self.assertRaises(ValueError):
            self.tracker.generate_report()
        self.advance(20)
        self.assertEqual(self.tracker.stop_timer(1), 10)

    def test_naive_clock_rejected(self):
        tracker = TimeTracker(self.manager, lambda: datetime(2026, 1, 1))
        with self.assertRaises(ValueError):
            tracker.start_timer(1)

    def test_timezone_normalization(self):
        local = self.now.astimezone(timezone(timedelta(hours=10)))
        tracker = TimeTracker(self.manager, lambda: local)
        tracker.start_timer(1)
        self.advance(30)
        self.assertEqual(self.tracker.stop_timer(1), 30)

    def test_assignment_and_status_in_report(self):
        user = self.manager.create_user('Иван', 'ivan@example.com')
        self.assertTrue(self.manager.assign_task(1, user.user_id))
        self.manager.update_status(1, Status.DONE)
        row = self.tracker.generate_report()['tasks'][0]
        self.assertEqual(row['assignee'], 'Иван')
        self.assertEqual(row['status'], 'Done')
        self.assertEqual(len(self.manager.get_user_tasks(user.user_id)), 1)
        self.assertEqual(self.manager.get_overdue_tasks(), [])

    def test_invalid_assignment(self):
        self.assertFalse(self.manager.assign_task(1, 999))
        user = self.manager.create_user('Иван', 'ivan@example.com')
        self.assertFalse(self.manager.assign_task(999, user.user_id))

    def test_validation(self):
        for name, email in [('', 'a@b'), ('Имя', 'bad')]:
            with self.assertRaises(ValueError):
                self.manager.create_user(name, email)
        self.manager.create_user('Иван', 'i@example.com')
        with self.assertRaises(ValueError):
            self.manager.create_user('Другой', 'i@example.com')
        with self.assertRaises(ValueError):
            self.manager.create_task('  ', '', Priority.LOW, self.now)
        with self.assertRaises(ValueError):
            self.manager.create_task('Имя', '', 'LOW', self.now)
        with self.assertRaises(ValueError):
            self.manager.update_status(1, 'done')

    def test_report_formats(self):
        report = self.tracker.generate_report()
        self.assertEqual(json.loads(render_report(report, 'json')), report)
        rows = list(csv.DictReader(io.StringIO(render_report(report, 'csv'))))
        self.assertEqual(rows[0]['title'], 'Задача')
        self.assertIn('Всего: 0.000', render_report(report, 'text'))

    def test_persistence_and_two_connections(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'tasks.db'
            with TaskManager(database) as first:
                first.create_task('Сохранённая', '', Priority.MEDIUM, self.now)
                TimeTracker(first, lambda: self.now).start_timer(1)
                with TaskManager(database) as second:
                    other = TimeTracker(second, lambda: self.now)
                    with self.assertRaises(ValueError):
                        other.start_timer(1)
            self.advance(42)
            with TaskManager(database) as reopened:
                tracker = TimeTracker(reopened, lambda: self.now)
                self.assertEqual(tracker.stop_timer(1), 42)
                self.assertEqual(tracker.get_total_time(1), 42)


class CLITests(unittest.TestCase):
    def test_full_workflow_and_error_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = ['--db', str(Path(directory) / 'tasks.db')]
            output = Path(directory) / 'report.json'
            commands = [
                ['user', 'Иван', 'ivan@example.com'],
                ['task', 'Проверить программу', '--due', '2026-12-31'],
                ['assign', '1', '1'], ['list'], ['start', '1'], ['stop', '1'],
                ['status', '1', 'DONE'],
                ['report', '--format', 'json', '--output', str(output)],
            ]
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                for command in commands:
                    self.assertEqual(main(prefix + command), 0, command)
                self.assertEqual(main(prefix + ['stop', '1']), 1)
                self.assertEqual(main(prefix + ['assign', '1', '999']), 1)
                self.assertEqual(main(prefix + ['start', '999']), 1)
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(report['tasks'][0]['status'], 'Done')
            self.assertGreaterEqual(report['total_seconds'], 0)


if __name__ == '__main__':
    unittest.main()

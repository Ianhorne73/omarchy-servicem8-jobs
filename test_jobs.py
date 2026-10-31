import datetime as dt
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('jobs', Path(__file__).with_name('jobs.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
NOW = dt.datetime(2026, 10, 31, 10, tzinfo=m.TZ)
A, B, C = ['00000000-0000-4000-8000-' + str(i).zfill(12) for i in range(3)]

class FakeApi:
    def __init__(self, activities=(), allocations=()):
        self.activities, self.allocations = activities, allocations
    def rows(self, resource, expression):
        return self.activities if resource == 'jobactivity' else self.allocations
    def one(self, resource, uid):
        if resource == 'company': return {'name': 'Customer'}
        return {'status': 'Work Order', 'generated_job_id': '123', 'company_uuid': C}

def activity(uid=A, **overrides):
    return dict(job_uuid=uid, staff_uuid=m.STAFF, active=1, activity_was_scheduled=1,
                start_date='2026-10-31 09:00:00', end_date='2026-10-31 10:00:00', **overrides)

class ScheduleTests(unittest.TestCase):
    def test_staff_date_and_recorded_activity_excluded(self):
        good = activity()
        other = {**good, 'staff_uuid': 'someone-else', 'job_uuid': B}
        tomorrow = {**good, 'start_date': '2026-11-01 09:00:00', 'end_date': '2026-11-01 10:00:00'}
        recorded = {**good, 'activity_was_scheduled': 0}
        self.assertEqual(len(m.scheduled_jobs(FakeApi([good, other, tomorrow, recorded]), NOW)), 1)
    def test_overlap_and_deduplicate(self):
        overnight = {**activity(), 'start_date': '2026-10-30 23:00:00', 'end_date': '2026-10-31 01:00:00'}
        result = m.scheduled_jobs(FakeApi([overnight, activity()]), NOW)
        self.assertEqual(len(result), 1)
        self.assertIn('23:00–01:00', result[0]['time'])
        self.assertIn('09:00–10:00', result[0]['time'])
    def test_flexible_carry_forward_completed_expired(self):
        base = dict(job_uuid=A, staff_uuid=m.STAFF, active=1, allocation_date='2026-10-30 09:00:00')
        rows = [base, {**base, 'job_uuid': B, 'completion_timestamp': '2026-10-31 08:00:00'},
                {**base, 'job_uuid': B, 'expiry_timestamp': '2026-10-31 09:00:00'}]
        result = m.scheduled_jobs(FakeApi(allocations=rows), NOW)
        self.assertEqual([j['uuid'] for j in result], [A])
        self.assertIn('carried forward', result[0]['time'])
    def test_utc_to_brisbane(self):
        self.assertEqual(m.parse_date('2026-10-30T15:00:00Z').date(), NOW.date())
        self.assertIsNone(m.parse_date('0000-00-00 00:00:00'))
    def test_pagination(self):
        api = m.Api('test-only')
        with patch.object(api, 'request', side_effect=[([{'a': 1}], A), ([{'a': 2}], None)]) as call:
            self.assertEqual(len(list(api.rows('jobactivity', 'active eq 1'))), 2)
            self.assertEqual(call.call_args.args[1]['cursor'], A)
    def test_cache_date_rollover_and_secret_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            config, state = Path(folder)/'config', Path(folder)/'state'
            m.atomic_json(config/'credentials.json', {'api_key': 'dummy'})
            m.atomic_json(state/'jobs.json', {'date': '1999-01-01', 'jobs': [{'old': True}]})
            self.assertEqual((config/'credentials.json').stat().st_mode & 0o777, 0o600)
            with patch.object(m, 'CONFIG', config), patch.object(m, 'STATE', state), patch.object(m, 'scheduled_jobs', side_effect=OSError):
                result = m.run(force=True)
                self.assertEqual(result['jobs'], [])
                self.assertTrue(result['error'])

class UserSelectionTests(unittest.TestCase):
    def test_selected_staff_filter(self):
        other = {**activity(), 'staff_uuid': B}
        jobs = m.scheduled_jobs(FakeApi([activity(), other]), NOW, B)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['uuid'], A)

    def test_default_persists_and_temporary_switch_does_not_change_it(self):
        with tempfile.TemporaryDirectory() as folder:
            config, state = Path(folder)/'config', Path(folder)/'state'
            example_staff = m.KNOWN_STAFF[1]['uuid']
            with patch.object(m, 'CONFIG', config), patch.object(m, 'STATE', state):
                result = m.run(default_staff=example_staff)
                self.assertEqual(result['default_staff'], example_staff)
                self.assertEqual(result['staff_uuid'], example_staff)
                self.assertEqual(m.run(staff=m.STAFF)['staff_uuid'], m.STAFF)
                self.assertEqual(m.run()['staff_uuid'], example_staff)

    def test_staff_cache_isolation_on_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            config, state = Path(folder)/'config', Path(folder)/'state'
            m.atomic_json(config/'credentials.json', {'api_key': 'dummy'})
            m.atomic_json(state/('jobs-' + m.STAFF + '-' + dt.datetime.now(m.TZ).date().isoformat() + '.json'),
                          {'date': dt.datetime.now(m.TZ).date().isoformat(), 'jobs': [{'other_staff': True}]})
            with patch.object(m, 'CONFIG', config), patch.object(m, 'STATE', state), patch.object(m.Api, 'rows', side_effect=OSError):
                result = m.run(staff=m.KNOWN_STAFF[1]['uuid'])
                self.assertEqual(result['jobs'], [])
                self.assertEqual(result['staff_uuid'], m.KNOWN_STAFF[1]['uuid'])

class DateSelectionTests(unittest.TestCase):
    def test_selected_day_instead_of_today(self):
        tomorrow = {**activity(), 'start_date': '2026-11-01 09:00:00', 'end_date': '2026-11-01 10:00:00', 'job_uuid': B}
        api = FakeApi([activity(), tomorrow])
        result = m.scheduled_jobs(api, NOW, selected_date='2026-11-01')
        self.assertEqual([job['uuid'] for job in result], [B])

    def test_completed_flexible_allocation_visible_on_prior_day(self):
        allocation = dict(job_uuid=A, staff_uuid=m.STAFF, active=1,
                          allocation_date='2026-10-29 09:00:00', completion_timestamp='2026-10-30 16:00:00')
        api = FakeApi(allocations=[allocation])
        self.assertEqual(len(m.scheduled_jobs(api, NOW, selected_date='2026-10-30')), 1)
        self.assertEqual(m.scheduled_jobs(api, NOW), [])

    def test_date_cache_isolation_and_today_default(self):
        with tempfile.TemporaryDirectory() as folder:
            config, state = Path(folder)/'config', Path(folder)/'state'
            m.atomic_json(config/'credentials.json', {'api_key': 'dummy'})
            m.atomic_json(state/('jobs-' + m.STAFF + '-2020-01-01.json'),
                          {'date': '2020-01-01', 'jobs': [{'old': True}], 'fetched_at': dt.datetime.now(m.TZ).timestamp()})
            with patch.object(m, 'CONFIG', config), patch.object(m, 'STATE', state), patch.object(m.Api, 'rows', side_effect=OSError):
                result = m.run(selected_date='2020-01-02')
                self.assertEqual(result['date'], '2020-01-02')
                self.assertEqual(result['jobs'], [])
                self.assertEqual(m.run()['date'], dt.datetime.now(m.TZ).date().isoformat())

    def test_invalid_date_rejected(self):
        with self.assertRaises(ValueError):
            m.run(selected_date='2026-02-30')

if __name__ == '__main__': unittest.main()

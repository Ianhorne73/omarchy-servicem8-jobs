import datetime as dt
import importlib.util
from pathlib import Path
import tempfile
import hashlib
import io
import json
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('jobs', Path(__file__).with_name('jobs.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
# Deterministic schedule fixtures, independent of the test machine timezone.
m.TZ = m.ZoneInfo("Australia/Brisbane")
NOW = dt.datetime(2026, 10, 31, 10, tzinfo=m.TZ)
A, B, C = ['00000000-0000-4000-8000-' + str(i).zfill(12) for i in range(3)]
STAFF = A
PEOPLE = [{'uuid': A, 'name': 'Staff Alpha'}, {'uuid': B, 'name': 'Staff Beta'}]
ACCOUNT = hashlib.sha256(b'dummy').hexdigest()[:24]

def seed(config, default=A):
    m.atomic_json(config/'credentials.json', {'api_key': 'dummy'})
    m.atomic_json(config/'preferences.json', {'account': ACCOUNT, 'staff': PEOPLE, 'default_staff': default})

def cache_path(state, person=A, date=None):
    date = date or dt.datetime.now(m.TZ).date().isoformat()
    return state / ('jobs-' + ACCOUNT + '-' + person + '-' + date + '.json')

class FakeApi:
    def __init__(self, activities=(), allocations=()):
        self.activities, self.allocations = activities, allocations
    def rows(self, resource, expression):
        return self.activities if resource == 'jobactivity' else self.allocations
    def one(self, resource, uid):
        if resource == 'company': return {'name': 'Customer'}
        return {'status': 'Work Order', 'generated_job_id': '123', 'company_uuid': C}

def activity(uid=A, **overrides):
    return dict(job_uuid=uid, staff_uuid=STAFF, active=1, activity_was_scheduled=1,
                start_date='2026-10-31 09:00:00', end_date='2026-10-31 10:00:00', **overrides)

class ScheduleTests(unittest.TestCase):
    def test_staff_date_and_recorded_activity_excluded(self):
        good = activity()
        other = {**good, 'staff_uuid': 'someone-else', 'job_uuid': B}
        tomorrow = {**good, 'start_date': '2026-11-01 09:00:00', 'end_date': '2026-11-01 10:00:00'}
        recorded = {**good, 'activity_was_scheduled': 0}
        self.assertEqual(len(m.scheduled_jobs(FakeApi([good, other, tomorrow, recorded]), NOW, STAFF)), 1)
    def test_overlap_and_deduplicate(self):
        overnight = {**activity(), 'start_date': '2026-10-30 23:00:00', 'end_date': '2026-10-31 01:00:00'}
        result = m.scheduled_jobs(FakeApi([overnight, activity()]), NOW, STAFF)
        self.assertEqual(len(result), 1)
        self.assertIn('23:00–01:00', result[0]['time'])
        self.assertIn('09:00–10:00', result[0]['time'])
        self.assertEqual(result[0]['appointments'][1], {'start': '2026-10-31T09:00:00+10:00', 'end': '2026-10-31T10:00:00+10:00'})
        self.assertEqual(result[0]['starts'], ['2026-10-30T23:00:00+10:00', '2026-10-31T09:00:00+10:00'])
    def test_flexible_carry_forward_completed_expired(self):
        base = dict(job_uuid=A, staff_uuid=STAFF, active=1, allocation_date='2026-10-30 09:00:00')
        rows = [base, {**base, 'job_uuid': B, 'completion_timestamp': '2026-10-31 08:00:00'},
                {**base, 'job_uuid': B, 'expiry_timestamp': '2026-10-31 09:00:00'}]
        result = m.scheduled_jobs(FakeApi(allocations=rows), NOW, STAFF)
        self.assertEqual([j['uuid'] for j in result], [A])
        self.assertIn('carried forward', result[0]['time'])
        self.assertEqual(result[0]['starts'], [])
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
            seed(config)
            m.atomic_json(state/'jobs.json', {'date': '1999-01-01', 'jobs': [{'old': True}]})
            self.assertEqual((config/'credentials.json').stat().st_mode & 0o777, 0o600)
            with patch.object(m, 'CONFIG', config), patch.object(m, 'STATE', state), patch.object(m, 'scheduled_jobs', side_effect=OSError):
                result = m.run(force=True)
                self.assertEqual(result['jobs'], [])
                self.assertTrue(result['error'])

class PhoneTests(unittest.TestCase):
    def test_only_active_site_contacts_and_deduplicated_numbers(self):
        contacts = [
            {'job_uuid': A, 'type': 'JOB', 'first': 'Site', 'mobile': '0400 000 000', 'phone': '0400000000'},
            {'job_uuid': A, 'type': 'BILLING', 'mobile': '0400111111'},
            {'job_uuid': B, 'type': 'JOB', 'mobile': '0400222222'},
            {'job_uuid': A, 'type': 'JOB', 'active': 0, 'mobile': '0400333333'},
        ]
        api = FakeApi()
        with patch.object(api, 'rows', return_value=contacts):
            phones, error = m.job_phones(api, {'uuid': A})
        self.assertEqual(error, '')
        self.assertEqual(phones, [{'number': '0400 000 000', 'label': 'Site · Mobile'}])

    def test_missing_contact_permission_keeps_schedule_available(self):
        api = FakeApi([activity()])
        original = api.rows
        def rows(resource, expression):
            if resource == 'jobcontact':
                raise m.urllib.error.HTTPError('https://example.invalid', 403, 'Forbidden', {}, None)
            return original(resource, expression)
        with patch.object(api, 'rows', side_effect=rows):
            result = m.scheduled_jobs(api, NOW, STAFF)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['phones'], [])
        self.assertIn('Job Contacts read access', result[0]['phone_error'])

    def test_contact_network_failure_is_optional(self):
        api = FakeApi()
        with patch.object(api, 'rows', side_effect=m.urllib.error.URLError('offline')):
            phones, error = m.job_phones(api, {'uuid': A})
        self.assertEqual(phones, [])
        self.assertIn('Refresh', error)

class UserSelectionTests(unittest.TestCase):
    def test_selected_staff_filter(self):
        other = {**activity(), 'staff_uuid': B}
        jobs = m.scheduled_jobs(FakeApi([activity(), other]), NOW, B)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['uuid'], A)

    def test_default_persists_and_temporary_switch_does_not_change_it(self):
        with tempfile.TemporaryDirectory() as folder:
            config, state = Path(folder)/'config', Path(folder)/'state'
            chosen = B
            seed(config)
            with patch.object(m, 'CONFIG', config), patch.object(m, 'STATE', state):
                result = m.run(default_staff=chosen)
                self.assertEqual(result['default_staff'], chosen)
                self.assertEqual(result['staff_uuid'], chosen)
                self.assertEqual(m.run(staff=STAFF)['staff_uuid'], STAFF)
                self.assertEqual(m.run()['staff_uuid'], chosen)

    def test_staff_cache_isolation_on_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            config, state = Path(folder)/'config', Path(folder)/'state'
            seed(config)
            m.atomic_json(cache_path(state),
                          {'date': dt.datetime.now(m.TZ).date().isoformat(), 'jobs': [{'other_staff': True}]})
            with patch.object(m, 'CONFIG', config), patch.object(m, 'STATE', state), patch.object(m.Api, 'rows', side_effect=OSError):
                result = m.run(staff=B)
                self.assertEqual(result['jobs'], [])
                self.assertEqual(result['staff_uuid'], B)

class DateSelectionTests(unittest.TestCase):
    def test_selected_day_instead_of_today(self):
        tomorrow = {**activity(), 'start_date': '2026-11-01 09:00:00', 'end_date': '2026-11-01 10:00:00', 'job_uuid': B}
        api = FakeApi([activity(), tomorrow])
        result = m.scheduled_jobs(api, NOW, STAFF, selected_date='2026-11-01')
        self.assertEqual([job['uuid'] for job in result], [B])

    def test_completed_flexible_allocation_visible_on_prior_day(self):
        allocation = dict(job_uuid=A, staff_uuid=STAFF, active=1,
                          allocation_date='2026-10-29 09:00:00', completion_timestamp='2026-10-30 16:00:00')
        api = FakeApi(allocations=[allocation])
        self.assertEqual(len(m.scheduled_jobs(api, NOW, STAFF, selected_date='2026-10-30')), 1)
        self.assertEqual(m.scheduled_jobs(api, NOW, STAFF), [])

    def test_date_cache_isolation_and_today_default(self):
        with tempfile.TemporaryDirectory() as folder:
            config, state = Path(folder)/'config', Path(folder)/'state'
            seed(config)
            m.atomic_json(cache_path(state, date='2020-01-01'),
                          {'date': '2020-01-01', 'jobs': [{'old': True}], 'fetched_at': dt.datetime.now(m.TZ).timestamp()})
            with patch.object(m, 'CONFIG', config), patch.object(m, 'STATE', state), patch.object(m.Api, 'rows', side_effect=OSError):
                result = m.run(selected_date='2020-01-02')
                self.assertEqual(result['date'], '2020-01-02')
                self.assertEqual(result['jobs'], [])
                self.assertEqual(m.run()['date'], dt.datetime.now(m.TZ).date().isoformat())

    def test_invalid_date_rejected(self):
        with self.assertRaises(ValueError):
            m.run(selected_date='2026-02-30')

class AccountSetupTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.config = Path(self.folder.name)/'config'
        self.state = Path(self.folder.name)/'state'
        for name, value in [('CONFIG', self.config), ('STATE', self.state)]:
            patcher = patch.object(m, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_fresh_install_has_no_staff_or_jobs_and_makes_no_requests(self):
        with patch.object(m.Api, 'request') as request:
            result = m.run()
        self.assertTrue(result['needs_setup'])
        self.assertEqual(result['staff'], [])
        self.assertEqual(result['jobs'], [])
        self.assertEqual(result['staff_uuid'], '')
        request.assert_not_called()

    def test_missing_key_never_shows_old_preferences(self):
        m.atomic_json(self.config/'preferences.json', {'staff': PEOPLE, 'default_staff': A})
        result = m.run()
        self.assertEqual(result['staff'], [])
        self.assertEqual(result['default_staff'], '')

    def test_connect_loads_entered_accounts_staff_and_requests_default(self):
        rows = [{'uuid': B, 'first': 'New', 'last': 'User'}, {'uuid': C, 'first': 'Inactive', 'active': 0}]
        with patch('sys.stdin', io.StringIO('new-key\n')), patch.object(m.Api, 'rows', return_value=iter(rows)), patch.object(m, 'scheduled_jobs') as schedule:
            result = m.run(save=True)
        self.assertFalse(result['needs_setup'])
        self.assertTrue(result['needs_staff'])
        self.assertEqual(result['staff'], [{'uuid': B, 'name': 'New User'}])
        self.assertEqual(result['jobs'], [])
        self.assertEqual(result['default_staff'], '')
        schedule.assert_not_called()
        self.assertEqual((self.config/'credentials.json').stat().st_mode & 0o777, 0o600)

    def test_account_replacement_drops_old_default_and_cache(self):
        seed(self.config)
        m.atomic_json(cache_path(self.state), {'date': dt.datetime.now(m.TZ).date().isoformat(), 'jobs': [{'private': 'old'}]})
        with patch('sys.stdin', io.StringIO('replacement-key\n')), patch.object(m.Api, 'rows', return_value=iter([{'uuid': B, 'first': 'Other'}])):
            result = m.run(save=True, staff=A, default_staff=A)
        self.assertEqual(result['jobs'], [])
        self.assertEqual(result['default_staff'], '')
        self.assertEqual(result['staff_uuid'], '')
        self.assertEqual(result['staff'][0]['uuid'], B)
        self.assertEqual(m.read_json(self.config/'preferences.json')['default_staff'], '')

    def test_rejected_key_keeps_saved_connection_and_displays_no_old_data(self):
        seed(self.config)
        before = (self.config/'preferences.json').read_text()
        with patch('sys.stdin', io.StringIO('bad-key\n')), patch.object(m.Api, 'rows', side_effect=OSError):
            result = m.run(save=True)
        self.assertTrue(result['needs_setup'])
        self.assertEqual(result['staff'], [])
        self.assertEqual(result['jobs'], [])
        self.assertEqual(m.read_json(self.config/'credentials.json')['api_key'], 'dummy')
        self.assertEqual((self.config/'preferences.json').read_text(), before)

    def test_upgrade_preserves_default_only_if_found_in_live_roster(self):
        seed(self.config)
        m.atomic_json(self.config/'preferences.json', {'staff': PEOPLE, 'default_staff': A})
        with patch.object(m.Api, 'rows', return_value=iter([{'uuid': A, 'first': 'Current'}])), patch.object(m, 'scheduled_jobs', return_value=[]):
            result = m.run()
        self.assertEqual(result['default_staff'], A)
        self.assertEqual(result['staff_name'], 'Current')
        self.assertEqual(m.read_json(self.config/'preferences.json')['account'], ACCOUNT)




class AlertTests(unittest.TestCase):
    def job(self, uid=A, time='09:00–10:00'):
        return {'uuid': uid, 'number': '123', 'customer': 'Test client', 'time': time,
                'appointments': [{'start': time, 'end': time}]}

    def test_initial_baseline_and_unchanged_are_silent(self):
        snapshot, events = m.schedule_changes(None, [self.job()])
        self.assertEqual(events, [])
        self.assertEqual(m.schedule_changes(snapshot, [self.job()])[1], [])

    def test_added_moved_removed(self):
        snapshot, _ = m.schedule_changes(None, [self.job()])
        _, events = m.schedule_changes(snapshot, [self.job(time='11:00–12:00'), self.job(B)])
        self.assertEqual([event[1] for event in events], ['Appointment moved', 'New job assigned'])
        _, events = m.schedule_changes(snapshot, [])
        self.assertEqual(events[0][1], 'Job removed from your schedule')

    def test_completed_status_does_not_trigger_schedule_alert(self):
        snapshot, _ = m.schedule_changes(None, [self.job()])
        self.assertEqual(m.schedule_changes(snapshot, [{**self.job(), 'status': 'Completed'}])[1], [])

    def test_notifications_are_deduplicated_under_persisted_baseline(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(m, 'STATE', Path(folder)), patch.object(m.subprocess, 'Popen') as notify, patch.object(m, 'omarchy_session', return_value='shell-session'):
            m.poll_notifications('account', A, '2026-11-05', [self.job()])
            notify.assert_not_called()
            m.poll_notifications('account', A, '2026-11-05', [self.job(B)])
            self.assertEqual(notify.call_count, 2)
            m.poll_notifications('account', A, '2026-11-05', [self.job(B)])
            self.assertEqual(notify.call_count, 2)
            m.poll_notifications('account', A, '2026-11-06', [self.job()])
            self.assertEqual(notify.call_count, 2)

    def test_toggle_persists_and_default_change_resets_baseline(self):
        with tempfile.TemporaryDirectory() as folder:
            config, state = Path(folder)/'config', Path(folder)/'state'
            seed(config)
            with patch.object(m, 'CONFIG', config), patch.object(m, 'STATE', state), patch.object(m, 'scheduled_jobs', return_value=[]):
                self.assertFalse(m.run()['alerts_enabled'])
                self.assertTrue(m.run(alerts='on')['alerts_enabled'])
                self.assertTrue(m.run()['alerts_enabled'])
                baseline = state/('alerts-'+ACCOUNT+'-'+A+'-2000-01-01.json')
                m.atomic_json(baseline, {'jobs': {}})
                self.assertTrue(m.run(default_staff=B)['alerts_enabled'])
                self.assertFalse(baseline.exists())
                self.assertFalse(m.run(alerts='off')['alerts_enabled'])
                self.assertFalse(m.run()['alerts_enabled'])


class AlertSessionTests(unittest.TestCase):
    def test_login_restart_and_resume_do_not_replay(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(m, 'STATE', Path(folder)), patch.object(m.subprocess, 'Popen') as notify, patch.object(m.time, 'time', return_value=1000) as clock:
            first = {'uuid': A, 'number': '1', 'customer': 'Example', 'time': '09:00', 'appointments': []}
            second = {**first, 'time': '10:00'}
            m.poll_notifications('account', A, '2026-11-05', [first], session='login-one')
            clock.return_value = 1060
            m.poll_notifications('account', A, '2026-11-05', [second], session='login-two')
            notify.assert_not_called()
            clock.return_value = 1120
            m.poll_notifications('account', A, '2026-11-05', [first], session='login-two')
            self.assertEqual(notify.call_count, 1)
            clock.return_value = 2000
            m.poll_notifications('account', A, '2026-11-05', [second], session='login-two')
            self.assertEqual(notify.call_count, 1)

    def test_no_alerts_outside_omarchy(self):
        with patch.object(m, 'omarchy_session', return_value=None), patch.object(m.subprocess, 'Popen') as notify, patch.object(m, 'atomic_json') as save:
            m.poll_notifications('account', A, '2026-11-05', [])
            notify.assert_not_called()
            save.assert_not_called()


class WeekTests(unittest.TestCase):
    def test_monday_to_sunday_across_year_boundary(self):
        self.assertEqual(m.week_dates('2027-01-01'), ['2026-12-28', '2026-12-29', '2026-12-30', '2026-12-31', '2027-01-01', '2027-01-02', '2027-01-03'])
        self.assertEqual(m.week_dates('2026-11-08')[0], '2026-11-02')

    def test_week_uses_selected_staff_and_reuses_anchor(self):
        def day(**kwargs):
            return {'date': kwargs['selected_date'], 'staff_uuid': B, 'jobs': [], 'error': '', 'today': '2026-11-05'}
        with patch.object(m, 'run', side_effect=day) as fetch:
            result = m.run_week(staff=B, selected_date='2026-11-05')
        self.assertEqual(len(result['week_days']), 7)
        self.assertEqual(fetch.call_count, 7)
        self.assertTrue(all(call.kwargs['staff'] == B for call in fetch.call_args_list))
        self.assertEqual(result['week_start'], '2026-11-02')
        self.assertEqual(result['week_end'], '2026-11-08')
        self.assertTrue(all(not call.kwargs.get('poll_alerts') for call in fetch.call_args_list))

    def test_setup_does_not_fetch_seven_days(self):
        with patch.object(m, 'run', return_value={'needs_setup': True}) as fetch:
            self.assertEqual(m.run_week(selected_date='2026-11-05')['week_days'], [])
            self.assertEqual(fetch.call_count, 1)


class ReleaseSecurityTests(unittest.TestCase):
    def test_json_storage_repairs_public_directory_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / 'public'
            directory.mkdir(mode=0o755)
            m.atomic_json(directory / 'credentials.json', {'api_key': 'synthetic-key'})
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            self.assertEqual((directory / 'credentials.json').stat().st_mode & 0o777, 0o600)

    def test_api_redirect_refused_without_forwarding_key(self):
        request = m.urllib.request.Request(m.BASE + 'staff.json', headers={'X-API-Key': 'synthetic-key'})
        with self.assertRaises(m.urllib.error.HTTPError):
            m.NoRedirect().redirect_request(request, None, 302, 'Found', {}, 'https://example.invalid')

    def test_configured_timezone_observes_dst(self):
        with patch.dict(m.os.environ, {'TZ': 'Europe/London'}):
            zone = m.local_timezone()
        self.assertEqual(dt.datetime(2026, 1, 1, tzinfo=zone).utcoffset(), dt.timedelta(0))
        self.assertEqual(dt.datetime(2026, 7, 1, tzinfo=zone).utcoffset(), dt.timedelta(hours=1))

    def test_api_key_stays_in_header_and_never_enters_report(self):
        key = 'synthetic-key-for-test'
        opener = unittest.mock.MagicMock()
        response = opener.open.return_value.__enter__.return_value
        response.read.return_value = b'[]'
        response.headers.get.return_value = None
        with patch.object(m.urllib.request, 'build_opener', return_value=opener):
            m.Api(key).request('staff')
        request = opener.open.call_args.args[0]
        self.assertNotIn(key, request.full_url)
        self.assertEqual(request.get_header('X-api-key'), key)
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(m, 'CONFIG', Path(folder)/'config'), patch.object(m, 'STATE', Path(folder)/'state'), patch('sys.stdin', io.StringIO(key+'\n')), patch.object(m, 'staff_list', return_value=PEOPLE):
                report = m.run(save=True)
        self.assertNotIn(key, json.dumps(report))


if __name__ == '__main__':
    unittest.main()

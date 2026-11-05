#!/usr/bin/env python3
"""Read-only ServiceM8 schedule for the Omarchy bar. No third-party dependencies."""
import argparse
import subprocess
import html
import time
import uuid
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Australia/Brisbane')
CONFIG = Path.home() / '.config/omarchy/servicem8'
STATE = Path.home() / '.cache/omarchy/servicem8'
BASE = 'https://api.servicem8.com/api_1.0/'


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Api:
    def __init__(self, key):
        self.key = key

    def request(self, resource, params=None):
        url = BASE + resource + '.json'
        if params:
            url += '?' + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={
            'X-API-Key': self.key, 'Accept': 'application/json',
            'User-Agent': 'Omarchy-My-Jobs/1.0'})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response), response.headers.get('x-next-cursor')

    def one(self, resource, uuid):
        # IDs only, never allow a response field to redirect credentials.
        import uuid as uuid_module
        return self.request(resource + '/' + str(uuid_module.UUID(uuid)))[0]

    def rows(self, resource, expression):
        cursor, seen = '-1', set()
        while cursor:
            if cursor in seen:
                raise ValueError('Repeated pagination cursor')
            seen.add(cursor)
            rows, cursor = self.request(resource, {'$filter': expression, 'cursor': cursor})
            if not isinstance(rows, list):
                raise ValueError('Expected list')
            yield from rows


def parse_date(value):
    try:
        date = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return date.replace(tzinfo=TZ) if date.tzinfo is None else date.astimezone(TZ)
    except ValueError:
        return None


def job_phones(api, job):
    """Only job/site contacts; never substitute a billing contact."""
    numbers = []
    def add(value, label):
        value = str(value or '').strip()
        identity = ''.join(c for c in value if c.isdigit())
        if identity and not any(row['identity'] == identity for row in numbers):
            numbers.append({'number': value, 'label': label, 'identity': identity})
    try:
        for contact in api.rows('jobcontact', f"active eq 1 and job_uuid eq '{job['uuid']}'"):
            if (str(contact.get('active', 1)) != '1' or contact.get('job_uuid') != job['uuid']
                    or str(contact.get('type', '')).upper() not in ('JOB', 'JOB CONTACT')):
                continue
            name = ' '.join(filter(None, [contact.get('first'), contact.get('last')])).strip()
            add(contact.get('mobile'), (name + ' · Mobile').strip(' ·'))
            add(contact.get('phone'), (name + ' · Phone').strip(' ·'))
    except urllib.error.HTTPError as error:
        if error.code == 403:
            return [], 'Phone details need Job Contacts read access in Setup.'
        return [], 'Could not load phone details. Refresh to retry.'
    except (urllib.error.URLError, TimeoutError, OSError):
        return [], 'Could not load phone details. Refresh to retry.'
    for row in numbers:
        row.pop('identity')
    return numbers, ''


def scheduled_jobs(api, now, staff, selected_date=None):
    target = dt.date.fromisoformat(selected_date) if selected_date else now.date()
    start = dt.datetime.combine(target, dt.time.min, tzinfo=TZ)
    allocation_cutoff = now if target == now.date() else start
    end = start + dt.timedelta(days=1)
    prefix = f"active eq 1 and staff_uuid eq '{staff}'"
    # Include appointments overlapping today, including those starting yesterday.
    activities = api.rows('jobactivity', prefix +
        f" and start_date lt '{end:%Y-%m-%d %H:%M:%S}' and end_date gt '{start:%Y-%m-%d %H:%M:%S}'")
    selected = {}
    for activity in activities:
        begins, ends = parse_date(activity.get('start_date')), parse_date(activity.get('end_date'))
        if (str(activity.get('active', 1)) != '1' or activity.get('staff_uuid') != staff
                or str(activity.get('activity_was_scheduled')) != '1'
                or not begins or not ends or not (begins < end and ends > start)):
            continue
        uid = activity['job_uuid']
        item = selected.setdefault(uid, {'uuid': uid, 'times': [], 'starts': [], 'appointments': [], 'sort': begins.isoformat()})
        item['times'].append(f'{begins:%H:%M}–{ends:%H:%M}')
        item['starts'].append(begins.isoformat())
        item['appointments'].append({'start': begins.isoformat(), 'end': ends.isoformat()})
        item['sort'] = min(item['sort'], begins.isoformat())
    allocations = api.rows('joballocation', prefix +
        f" and allocation_date lt '{end:%Y-%m-%d %H:%M:%S}'")
    for allocation in allocations:
        begins = parse_date(allocation.get('allocation_date'))
        # Pending allocations carry forward until completed or expired.
        completed = parse_date(allocation.get('completion_timestamp'))
        expired = parse_date(allocation.get('expiry_timestamp'))
        if (str(allocation.get('active', 1)) != '1' or allocation.get('staff_uuid') != staff
                or not begins or begins >= end or (completed and completed <= allocation_cutoff)
                or (expired and expired <= allocation_cutoff)):
            continue
        uid = allocation['job_uuid']
        if uid not in selected:
            selected[uid] = {'uuid': uid, 'times': ['Flexible' if begins >= start else 'Flexible · carried forward'],
                             'starts': [], 'appointments': [], 'sort': end.isoformat()}
    customers = {}
    jobs = []
    for item in selected.values():
        job = api.one('job', item['uuid'])
        if str(job.get('active', 1)) != '1' or job.get('status') == 'Unsuccessful':
            continue
        company = job.get('company_uuid')
        if company and company not in customers:
            customers[company] = api.one('company', company).get('name', '')
        phones, phone_error = job_phones(api, {**job, 'uuid': item['uuid']})
        item.update(phones=phones, phone_error=phone_error, number=str(job.get('generated_job_id', '')), customer=customers.get(company, ''),
                    address=job.get('job_address', ''), description=job.get('job_description', ''),
                    status=job.get('status', ''), time=' · '.join(sorted(set(item.pop('times')))))
        jobs.append(item)
    return sorted(jobs, key=lambda job: (job['sort'], job['number']))


def friendly_error(error):
    if isinstance(error, urllib.error.HTTPError):
        return {401: 'API key was rejected. Check the key in Setup.',
                403: 'API key needs read access to staff, schedules, jobs and customers.',
                429: 'ServiceM8 rate limit reached. Try again in a few minutes.'}.get(
                    error.code, f'ServiceM8 returned HTTP {error.code}. Try again shortly.')
    if isinstance(error, (urllib.error.URLError, TimeoutError, OSError)):
        return 'Could not reach ServiceM8. Check your connection and refresh.'
    return 'Could not load the schedule. Please refresh or check API access.'


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def staff_list(api):
    people = []
    for person in api.rows('staff', 'active eq 1'):
        if str(person.get('active', 1)) != '1':
            continue
        people.append({'uuid': str(uuid.UUID(person['uuid'])),
                       'name': ' '.join(filter(None, [person.get('first'), person.get('last')])).strip() or 'Staff member'})
    return sorted(people, key=lambda person: person['name'].casefold())


def schedule_changes(previous, jobs):
    current = {job['uuid']: {'number': job.get('number', ''), 'customer': job.get('customer', ''),
               'time': job.get('time', ''), 'appointments': sorted(job.get('appointments', []), key=lambda slot: slot['start'])}
               for job in jobs}
    events = []
    if previous is not None:
        for uid, job in current.items():
            if uid not in previous:
                events.append((uid, 'New job assigned', job, "Today: " + job['time']))
            elif job['appointments'] != previous[uid].get('appointments', []) or job['time'] != previous[uid].get('time'):
                events.append((uid, 'Appointment moved', job, previous[uid].get('time', '') + ' → ' + job['time']))
        for uid, job in previous.items():
            if uid not in current:
                events.append((uid, 'Job removed from your schedule', job, 'No longer on today’s schedule'))
    return current, events


def omarchy_session():
    """Only the widget's live Omarchy Quickshell parent may poll alerts."""
    try:
        parent = Path('/proc') / str(os.getppid())
        command = (parent / 'cmdline').read_bytes().replace(b'\0', b' ')
        executable = (parent / 'exe').resolve().name
        if 'quickshell' not in executable or b'omarchy' not in command:
            return None
        # Boot ID + parent start ticks prevents PID reuse across logins/reboots.
        start = (parent / 'stat').read_text().rsplit(')', 1)[1].split()[19]
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        return boot + ':' + str(os.getppid()) + ':' + start
    except (OSError, IndexError):
        return None


def alert_baseline_needed(previous, session, now):
    gap = now - previous.get('last_poll', 0)
    return previous.get('session') != session or gap < 0 or gap > 180


def poll_notifications(account, staff, date, jobs, session=None):
    session = session or omarchy_session()
    if not session:
        return
    path = STATE / ('alerts-' + account + '-' + staff + '-' + date + '.json')
    previous = read_json(path)
    now = time.time()
    baseline = None if alert_baseline_needed(previous, session, now) else previous.get('jobs')
    current, events = schedule_changes(baseline, jobs)
    # The lock covers comparison and persistence across every monitor.
    atomic_json(path, {'jobs': current, 'session': session, 'last_poll': now})
    for uid, title, job, detail in events:
        body = '#' + job['number'] + ' · ' + job['customer'] + '\n' + detail
        try:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--notify-job',
                              str(uuid.UUID(uid)), '--notification-title', title,
                              '--notification-body', body], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass


def notification_action(uid, title, body):
    uid = str(uuid.UUID(uid))
    result = subprocess.run(['notify-send', '--app-name=ServiceM8', '--icon=appointment-soon',
                             '--action=default=Open job', '--wait', '--expire-time=10000',
                             '--', html.escape('ServiceM8 · ' + title), html.escape(body)],
                            capture_output=True, text=True, timeout=120)
    if result.stdout.strip() == 'default':
        subprocess.Popen(['xdg-open', 'https://go.servicem8.com/OpenJob/' + uid],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run(force=False, save=False, staff=None, default_staff=None, selected_date=None, alerts=None, poll_alerts=False):
    session = omarchy_session() if poll_alerts else None
    poll_alerts = poll_alerts and bool(session)
    now = dt.datetime.now(TZ)
    date = dt.date.fromisoformat(selected_date).isoformat() if selected_date else now.date().isoformat()
    blank = {'today': now.date().isoformat(), 'date': date, 'jobs': [], 'staff': [],
             'staff_uuid': '', 'staff_name': '', 'default_staff': '',
             'needs_setup': False, 'needs_staff': False, 'alerts_enabled': False, 'error': ''}
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / 'refresh.lock').open('a') as lock:
        os.chmod(STATE / 'refresh.lock', 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        stored_key = read_json(CONFIG / 'credentials.json').get('api_key', '')
        key = sys.stdin.readline().strip() if save else stored_key
        if not key:
            return {**blank, 'needs_setup': True,
                    'error': 'Enter an API key.' if save else 'Connect ServiceM8 in Setup.'}
        # Scope both preferences and job caches to the entered credential. An
        # account change must never reuse another account's staff or jobs.
        account = hashlib.sha256(key.encode()).hexdigest()[:24]
        preferences = read_json(CONFIG / 'preferences.json')
        known_account = preferences.get('account')
        if known_account != account:
            # Preserve existing local defaults during the upgrade, but never
            # when a new key is replacing the saved account.
            if known_account is not None or (save and key != stored_key):
                preferences = {}
        if save and key != stored_key:
            staff = default_staff = None
        people = preferences.get('staff', [])
        cache = {}
        metadata = dict(blank)
        try:
            api = Api(key)
            if save or force or not people or known_account != account:
                people = staff_list(api)
            ids = {person['uuid'] for person in people}
            default = preferences.get('default_staff', '')
            if default not in ids:
                default = ''
            if default_staff:
                proposed = str(uuid.UUID(default_staff))
                if proposed not in ids:
                    raise ValueError('Staff member is not part of this account')
                default = proposed
            selected = str(uuid.UUID(staff)) if staff else default
            if selected and selected not in ids:
                selected = ''
            metadata.update(staff=people, default_staff=default, staff_uuid=selected,
                            staff_name=next((person['name'] for person in people if person['uuid'] == selected), ''),
                            needs_staff=not bool(selected))
            enabled = bool(preferences.get('alerts_enabled', False))
            if default != preferences.get('default_staff', ''):
                for baseline in STATE.glob('alerts-' + account + '-*.json'):
                    baseline.unlink(missing_ok=True)
            if alerts is not None:
                enabled = alerts == 'on'
                # Enabling always starts with a fresh baseline, with no catch-up alerts.
                for baseline in STATE.glob('alerts-' + account + '-*.json'):
                    baseline.unlink(missing_ok=True)
            metadata['alerts_enabled'] = enabled
            preferences = {'account': account, 'staff': people, 'default_staff': default, 'alerts_enabled': enabled}
            if save:
                # Listing staff validates against the entered account without
                # relying on an ID belonging to the plugin's author.
                atomic_json(CONFIG / 'credentials.json', {'api_key': key})
            atomic_json(CONFIG / 'preferences.json', preferences)
            if not selected:
                return {**metadata, 'error': '' if people else 'No active staff found in this ServiceM8 account.'}
            cache_path = STATE / ('jobs-' + account + '-' + selected + '-' + date + '.json')
            cache = read_json(cache_path)
            if cache.get('date') != date:
                cache = {}
            needs_baseline = poll_alerts and enabled and alert_baseline_needed(read_json(STATE / ('alerts-' + account + '-' + selected + '-' + date + '.json')), session, time.time())
            if not needs_baseline and not force and not save and cache and all('appointments' in job and 'phones' in job for job in cache.get('jobs', [])) and now.timestamp() - cache.get('fetched_at', 0) < 240:
                if poll_alerts and enabled and selected == default and date == now.date().isoformat():
                    poll_notifications(account, selected, date, cache.get('jobs', []), session)
                return {**cache, **{k: v for k, v in metadata.items() if k != 'jobs'}}
            jobs = scheduled_jobs(api, now, selected, date)
            result = {**metadata, 'jobs': jobs, 'fetched_at': now.timestamp(), 'updated': now.strftime('%H:%M')}
            atomic_json(cache_path, result)
            if poll_alerts and enabled and selected == default and date == now.date().isoformat():
                poll_notifications(account, selected, date, jobs, session)
            return result
        except Exception as error:
            if save:
                return {**blank, 'needs_setup': True, 'error': friendly_error(error)}
            return {**cache, **{k: v for k, v in metadata.items() if k != 'jobs'},
                    'jobs': cache.get('jobs', []), 'error': friendly_error(error)}


def week_dates(selected_date):
    anchor = dt.date.fromisoformat(selected_date)
    monday = anchor - dt.timedelta(days=anchor.weekday())
    return [(monday + dt.timedelta(days=offset)).isoformat() for offset in range(7)]


def run_week(force=False, staff=None, selected_date=None):
    anchor = selected_date or dt.datetime.now(TZ).date().isoformat()
    base = run(force=force, staff=staff, selected_date=anchor)
    if base.get('needs_setup') or base.get('needs_staff'):
        return {**base, 'week_days': []}
    days = []
    for date in week_dates(anchor):
        day = base if date == anchor else run(force=force, staff=base['staff_uuid'], selected_date=date)
        days.append({'date': date, 'jobs': day.get('jobs', []), 'error': day.get('error', ''),
                     'updated': day.get('updated', '')})
    return {**base, 'week_days': days, 'week_start': days[0]['date'], 'week_end': days[-1]['date']}


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--save-key', action='store_true')
    parser.add_argument('--staff')
    parser.add_argument('--date', type=lambda value: dt.date.fromisoformat(value).isoformat())
    parser.add_argument('--set-default')
    parser.add_argument('--set-alerts', choices=['on', 'off'])
    parser.add_argument('--poll-alerts', action='store_true')
    parser.add_argument('--week', action='store_true')
    parser.add_argument('--notify-job')
    parser.add_argument('--notification-title', default='Schedule updated')
    parser.add_argument('--notification-body', default='')
    args = parser.parse_args()
    if args.notify_job:
        notification_action(args.notify_job, args.notification_title, args.notification_body)
        sys.exit(0)
    if args.week:
        print(json.dumps(run_week(force=args.force, staff=args.staff, selected_date=args.date)))
        sys.exit(0)
    print(json.dumps(run(force=args.force, save=args.save_key, staff=args.staff, default_staff=args.set_default, selected_date=args.date, alerts=args.set_alerts, poll_alerts=args.poll_alerts)))

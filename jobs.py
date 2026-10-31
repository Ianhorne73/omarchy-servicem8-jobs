#!/usr/bin/env python3
"""Read-only ServiceM8 schedule for the Omarchy bar. No third-party dependencies."""
import argparse
import uuid
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

STAFF = '00000000-0000-4000-8000-000000000101'
KNOWN_STAFF = [
    {'uuid': STAFF, 'name': 'Example Staff'},
    {'uuid': '00000000-0000-4000-8000-000000000102', 'name': 'Example Staff Two'},
    {'uuid': '00000000-0000-4000-8000-000000000103', 'name': 'Example Staff Three'},
]
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


def scheduled_jobs(api, now, staff=STAFF, selected_date=None):
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
        item = selected.setdefault(uid, {'uuid': uid, 'times': [], 'sort': begins.isoformat()})
        item['times'].append(f'{begins:%H:%M}–{ends:%H:%M}')
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
                             'sort': end.isoformat()}
    customers = {}
    jobs = []
    for item in selected.values():
        job = api.one('job', item['uuid'])
        if str(job.get('active', 1)) != '1' or job.get('status') == 'Unsuccessful':
            continue
        company = job.get('company_uuid')
        if company and company not in customers:
            customers[company] = api.one('company', company).get('name', '')
        item.update(number=str(job.get('generated_job_id', '')), customer=customers.get(company, ''),
                    address=job.get('job_address', ''), description=job.get('job_description', ''),
                    status=job.get('status', ''), time=' · '.join(sorted(set(item.pop('times')))))
        jobs.append(item)
    return sorted(jobs, key=lambda job: (job['sort'], job['number']))


def friendly_error(error):
    if isinstance(error, urllib.error.HTTPError):
        return {401: 'API key was rejected. Check the key in Setup.',
                403: 'API key needs read access to schedules, jobs and customers.',
                429: 'ServiceM8 rate limit reached. Try again in a few minutes.'}.get(
                    error.code, f'ServiceM8 returned HTTP {error.code}. Try again shortly.')
    if isinstance(error, (urllib.error.URLError, TimeoutError, OSError)):
        return 'Could not reach ServiceM8. Check your connection and refresh.'
    return 'Could not load the schedule. Please refresh or check API access.'


def run(force=False, save=False, staff=None, default_staff=None, selected_date=None):
    now = dt.datetime.now(TZ)
    date = dt.date.fromisoformat(selected_date).isoformat() if selected_date else now.date().isoformat()
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / 'refresh.lock').open('a') as lock:
        os.chmod(STATE / 'refresh.lock', 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            preferences = json.loads((CONFIG / 'preferences.json').read_text())
        except (OSError, ValueError):
            preferences = {}
        people = preferences.get('staff', KNOWN_STAFF)
        if default_staff:
            default_staff = str(uuid.UUID(default_staff))
            if default_staff not in [person['uuid'] for person in people]:
                raise ValueError('Unknown staff member')
            preferences['default_staff'] = default_staff
            atomic_json(CONFIG / 'preferences.json', preferences)
        default = preferences.get('default_staff', STAFF)
        staff = str(uuid.UUID(staff or default))
        metadata = {'today': now.date().isoformat(), 'staff': people, 'staff_uuid': staff, 'default_staff': default,
                    'staff_name': next((person['name'] for person in people if person['uuid'] == staff), 'Staff member')}
        cache_path = STATE / ('jobs-' + staff + '-' + date + '.json')
        try:
            cache = json.loads(cache_path.read_text())
        except (OSError, ValueError):
            cache = {}
        if cache.get('date') != date:
            cache = {}
        if save:
            key = sys.stdin.readline().strip()
            if not key:
                return {**metadata, 'date': date, 'jobs': [], 'needs_setup': True, 'error': 'Enter an API key.'}
        else:
            try:
                key = json.loads((CONFIG / 'credentials.json').read_text())['api_key']
            except (OSError, ValueError, KeyError):
                return {**metadata, 'date': date, 'jobs': [], 'needs_setup': True, 'error': 'Connect ServiceM8 in Setup.'}
        if not force and not save and cache and now.timestamp() - cache.get('fetched_at', 0) < 240:
            return {**cache, **metadata}
        try:
            api = Api(key)
            if save:
                api.one('staff', STAFF)
            # Refresh the staff menu when fetching schedules; a restricted key
            # may still read jobs even when it cannot list staff.
            try:
                people = [{'uuid': str(uuid.UUID(person['uuid'])),
                           'name': (person.get('first') or '') + ' ' + (person.get('last') or '')}
                          for person in api.rows('staff', 'active eq 1')]
                people = [{**person, 'name': person['name'].strip() or 'Staff member'} for person in people]
                if people:
                    preferences['staff'] = sorted(people, key=lambda person: person['name'])
                    atomic_json(CONFIG / 'preferences.json', preferences)
                    metadata['staff'] = preferences['staff']
                    metadata['staff_name'] = next((person['name'] for person in people if person['uuid'] == staff), metadata['staff_name'])
            except (OSError, ValueError, KeyError):
                pass
            jobs = scheduled_jobs(api, now, staff, date)
            if save:
                atomic_json(CONFIG / 'credentials.json', {'api_key': key})
            result = {**metadata, 'date': date, 'jobs': jobs, 'fetched_at': now.timestamp(),
                      'updated': now.strftime('%H:%M'), 'needs_setup': False, 'error': ''}
            atomic_json(cache_path, result)
            return result
        except Exception as error:
            return {**cache, **metadata, 'date': date, 'jobs': cache.get('jobs', []),
                    'needs_setup': save, 'error': friendly_error(error)}


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--save-key', action='store_true')
    parser.add_argument('--staff')
    parser.add_argument('--date', type=lambda value: dt.date.fromisoformat(value).isoformat())
    parser.add_argument('--set-default')
    args = parser.parse_args()
    print(json.dumps(run(force=args.force, save=args.save_key, staff=args.staff, default_staff=args.set_default, selected_date=args.date)))

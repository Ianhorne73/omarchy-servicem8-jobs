"""Synthetic regression tests: no ServiceM8 account or desktop session needed."""
import ctypes
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import jobs
import notifications

ROOT = Path(__file__).resolve().parent
UID = '00000000-0000-4000-8000-000000000001'
PAYLOAD = {'uuid': UID, 'title': 'New job assigned',
           'body': '#PRIVATE-123 · Zoë & <Test>\n09:00–10:00\n--option ; $(echo unsafe)'}


class NotificationTransportTests(unittest.TestCase):
    def test_private_payload_only_uses_pipe_and_closes_stdin(self):
        class Pipe(io.StringIO):
            def close(self):
                self.sent = self.getvalue()
                super().close()
        pipe = Pipe()
        child = MagicMock(stdin=pipe)
        event = (UID, PAYLOAD['title'], {'number': 'PRIVATE-123', 'customer': 'Zoë & <Test>'},
                 '09:00–10:00\n--option ; $(echo unsafe)')
        with tempfile.TemporaryDirectory() as folder, patch.object(jobs, 'STATE', Path(folder)), \
                patch.object(jobs, 'schedule_changes', return_value=({}, [event])), \
                patch.object(jobs.subprocess, 'Popen', return_value=child) as launch:
            jobs.poll_notifications('account', UID, '2026-11-08', [], session='test-session')
        command = launch.call_args.args[0]
        self.assertEqual(command, [sys.executable, str(ROOT / 'jobs.py'), '--notify-job'])
        self.assertEqual(json.loads(pipe.sent), PAYLOAD)
        self.assertTrue(pipe.closed)
        self.assertEqual(launch.call_args.kwargs['stdin'], subprocess.PIPE)
        self.assertTrue(launch.call_args.kwargs['start_new_session'])
        self.assertNotIn('env', launch.call_args.kwargs)
        child.wait.assert_not_called()
        child.communicate.assert_not_called()

    def test_spawn_or_pipe_failure_does_not_break_schedule_poll(self):
        event = (UID, 'New job assigned', {'number': '1', 'customer': 'Synthetic'}, 'Today')
        child = MagicMock()
        child.stdin.write.side_effect = BrokenPipeError()
        for error in (FileNotFoundError(), None):
            with self.subTest(stage='spawn' if error else 'write'), tempfile.TemporaryDirectory() as folder, \
                    patch.object(jobs, 'STATE', Path(folder)), \
                    patch.object(jobs, 'schedule_changes', return_value=({}, [event])), \
                    patch.object(jobs.subprocess, 'Popen', side_effect=error, return_value=child):
                jobs.poll_notifications('account', UID, '2026-11-08', [], session='test-session')

    def test_oversized_notification_never_spawns_helper(self):
        event = (UID, 'New job assigned', {'number': '1', 'customer': 'x' * jobs.MAX_NOTIFICATION_INPUT}, 'Today')
        with tempfile.TemporaryDirectory() as folder, patch.object(jobs, 'STATE', Path(folder)), \
                patch.object(jobs, 'schedule_changes', return_value=({}, [event])), \
                patch.object(jobs.subprocess, 'Popen') as launch:
            jobs.poll_notifications('account', UID, '2026-11-08', [], session='test-session')
        launch.assert_not_called()

    def test_stdin_round_trips_unicode_and_markup(self):
        with patch.object(jobs.sys, 'stdin', io.StringIO(json.dumps(PAYLOAD))), \
                patch.object(jobs, 'show_notification', return_value=False) as show, \
                patch.object(jobs.subprocess, 'Popen') as launch:
            self.assertTrue(jobs.notification_from_stdin())
        show.assert_called_once_with('ServiceM8 · New job assigned', jobs.html.escape(PAYLOAD['body']))
        launch.assert_not_called()

    def test_invalid_payloads_are_silent_and_do_not_notify(self):
        invalid = ['', '{', '[]', 'null', '{}', json.dumps({**PAYLOAD, 'uuid': 'invalid'}),
                   json.dumps({**PAYLOAD, 'title': 1}), json.dumps({**PAYLOAD, 'body': 'bad\0text'}),
                   json.dumps({**PAYLOAD, 'extra': 'unrecognized'}), 'x' * (jobs.MAX_NOTIFICATION_INPUT + 1)]
        for raw in invalid:
            with self.subTest(raw=raw[:80]), patch.object(jobs.sys, 'stdin', io.StringIO(raw)), \
                    patch.object(jobs, 'show_notification') as show, \
                    patch.object(jobs.sys, 'stdout', io.StringIO()) as stdout, \
                    patch.object(jobs.sys, 'stderr', io.StringIO()) as stderr:
                self.assertFalse(jobs.notification_from_stdin())
                show.assert_not_called()
                self.assertEqual(stdout.getvalue() + stderr.getvalue(), '')

    def test_open_job_only_after_explicit_action(self):
        for clicked in (False, True):
            with self.subTest(clicked=clicked), patch.object(jobs, 'show_notification', return_value=clicked), \
                    patch.object(jobs.subprocess, 'Popen') as launch:
                jobs.notification_action(UID, PAYLOAD['title'], PAYLOAD['body'])
            if clicked:
                self.assertEqual(launch.call_args.args[0],
                                 ['xdg-open', 'https://go.servicem8.com/OpenJob/' + UID])
            else:
                launch.assert_not_called()

    def test_cli_rejects_bad_stdin_without_echoing_it(self):
        result = subprocess.run([sys.executable, str(ROOT / 'jobs.py'), '--notify-job'],
                                input=PAYLOAD['body'], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout + result.stderr, '')

    def test_unencodable_unicode_does_not_leak_in_errors(self):
        result = subprocess.run([sys.executable, str(ROOT / 'jobs.py'), '--notify-job'],
                                input=json.dumps({**PAYLOAD, 'body': '\ud800'}), text=True,
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout + result.stderr, '')


class LibnotifyTests(unittest.TestCase):
    def setUp(self):
        self.notify, self.glib, self.gobject = (MagicMock() for _ in range(3))
        self.notify.notify_init.return_value = 1
        self.notify.notify_notification_new.return_value = 101
        self.notify.notify_notification_show.return_value = 1
        self.glib.g_main_loop_new.return_value = 102
        self.glib.g_timeout_add_seconds.return_value = 103
        self.gobject.g_signal_connect_data.return_value = 104
        loader = patch.object(notifications, '_libraries', return_value=(self.notify, self.glib, self.gobject))
        loader.start()
        self.addCleanup(loader.stop)

    def run_event(self, event):
        def dispatch(loop):
            if event in ('default', 'unknown'):
                callback = self.notify.notify_notification_add_action.call_args.args[3]
                callback(101, event.encode(), None)
            elif event == 'closed':
                self.gobject.g_signal_connect_data.call_args.args[2](101, None)
            else:
                self.assertEqual(self.glib.g_timeout_add_seconds.call_args.args[0], 120)
                self.assertEqual(self.glib.g_timeout_add_seconds.call_args.args[1](None), 0)
        self.glib.g_main_loop_run.side_effect = dispatch
        result = notifications.show_notification('Title', PAYLOAD['body'])
        self.notify.notify_notification_new.assert_called_once_with(
            b'Title', PAYLOAD['body'].encode('utf-8'), b'appointment-soon')
        self.notify.notify_notification_set_timeout.assert_called_once_with(101, 10000)
        self.glib.g_main_loop_quit.assert_called_once_with(102)
        self.gobject.g_signal_handler_disconnect.assert_called_once_with(101, 104)
        self.gobject.g_object_unref.assert_called_once_with(101)
        self.glib.g_main_loop_unref.assert_called_once_with(102)
        self.notify.notify_uninit.assert_called_once_with()
        return result

    def test_default_action(self):
        self.assertTrue(self.run_event('default'))
        self.glib.g_source_remove.assert_called_once_with(103)

    def test_unknown_action_does_not_open(self):
        self.assertFalse(self.run_event('unknown'))

    def test_closed_notification(self):
        self.assertFalse(self.run_event('closed'))

    def test_timeout_is_bounded_and_not_removed_twice(self):
        self.assertFalse(self.run_event('timeout'))
        self.glib.g_source_remove.assert_not_called()

    def test_show_failure_frees_error_and_never_waits(self):
        def fail(_notification, error):
            ctypes.cast(error, ctypes.POINTER(ctypes.c_void_p))[0] = 999
            return 0
        self.notify.notify_notification_show.side_effect = fail
        self.assertFalse(notifications.show_notification('Title', 'Body'))
        self.glib.g_error_free.assert_called_once()
        self.glib.g_main_loop_run.assert_not_called()
        self.gobject.g_object_unref.assert_called_once_with(101)
        self.notify.notify_uninit.assert_called_once_with()

    def test_early_close_never_enters_main_loop(self):
        def close_during_show(_notification, _error):
            self.gobject.g_signal_connect_data.call_args.args[2](101, None)
            return 1
        self.notify.notify_notification_show.side_effect = close_during_show
        self.assertFalse(notifications.show_notification('Title', 'Body'))
        self.glib.g_main_loop_run.assert_not_called()
        self.glib.g_source_remove.assert_called_once_with(103)

    def test_missing_library_does_not_fall_back_to_subprocess(self):
        with patch.object(notifications, '_libraries', side_effect=OSError), \
                patch.object(subprocess, 'Popen') as launch:
            self.assertFalse(notifications.show_notification('Title', 'Body'))
        launch.assert_not_called()

    def test_failed_init_does_not_use_notification(self):
        self.notify.notify_init.return_value = 0
        self.assertFalse(notifications.show_notification('Title', 'Body'))
        self.notify.notify_notification_new.assert_not_called()

    def test_invalid_c_strings_are_rejected(self):
        for body in (None, 7, 'bad\0text'):
            with self.subTest(body=body):
                self.assertFalse(notifications.show_notification('Title', body))
        self.notify.notify_init.assert_not_called()


class ClipboardTests(unittest.TestCase):
    def test_wl_copy_has_constant_arguments(self):
        source = (ROOT / 'BarWidget.qml').read_text()
        block = source.split('id: copier', 1)[1].split('Timer { id: copyFeedback', 1)[0]
        self.assertIn('command: ["wl-copy"]', block)
        self.assertNotRegex(source, r'\["wl-copy",')
        self.assertNotIn('execDetached', block)
        self.assertNotIn('startDetached', block)

    @unittest.skipUnless(shutil.which('node'), 'Node needed to exercise extracted QML JavaScript')
    def test_clipboard_exact_bytes_eof_repeated_click_and_feedback(self):
        source = (ROOT / 'BarWidget.qml').read_text()
        copy_function = re.search(r'function copyText\(value, label\) \{(.*?)\n    \}', source, re.S).group(1)
        block = source.split('id: copier', 1)[1].split('Timer { id: copyFeedback', 1)[0]
        started = re.search(r'onStarted: \{(.*?)\n        \}', block, re.S).group(1)
        exited = re.search(r'onExited: function\(code, status\) \{(.*?)\n        \}', block, re.S).group(1)
        harness = r'''
const assert = require('node:assert/strict');
const root = {lastCopiedText: '', copyMessage: ''};
const copyFeedback = {restart() {}};
const copier = {running: false, stdinEnabled: false, value: '', label: '', writes: [],
    write(value) { this.writes.push(value); }};
function copyText(value, label) {
COPY
}
function start() { with (copier) {
START
} }
function exit(code) { with (copier) {
EXIT
} copier.running = false; }
const values = ['--address with \\"quotes\\"\n雪 & ; $(touch nope)', '+61 0400 000 000', '', 'job-123'];
for (const value of values) {
    copyText(value, 'Value');
    assert.equal(copier.stdinEnabled, true);
    copyText('ignored rapid click', 'Other');
    assert.equal(copier.value, value);
    start();
    assert.equal(copier.writes.at(-1), value);
    assert.equal(copier.stdinEnabled, false);
    exit(0);
    assert.equal(root.lastCopiedText, value);
    assert.equal(copier.value, '');
    assert.equal(root.copyMessage, 'Value copied');
}
copyText('failed value', 'Value'); start(); exit(1);
assert.equal(root.lastCopiedText, '');
assert.equal(copier.value, '');
assert.equal(root.copyMessage, 'Could not copy to clipboard');
'''.replace('COPY', copy_function).replace('START', started).replace('EXIT', exited)
        result = subprocess.run(['node', '--input-type=commonjs'], input=harness, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()

"""Real libnotify regression checks on a fresh, isolated D-Bus session.

Only synthetic fixtures are used. A temporary xdg-open stub prevents browser
launches, and no connection is made to the user's desktop notification bus.
"""
import html
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent
SYSTEM_PYTHON = '/usr/bin/python3'
UID = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
TITLE = 'Synthetic <schedule> update'
BODY = 'PRIVATE_TEST_SENTINEL & synthetic customer\n09:00 → 10:00'
INTERFACE = 'org.freedesktop.Notifications'
OBJECT_PATH = '/org/freedesktop/Notifications'
XML = '''<node><interface name="org.freedesktop.Notifications">
<method name="GetCapabilities"><arg type="as" direction="out"/></method>
<method name="GetServerInformation">
<arg type="s" direction="out"/><arg type="s" direction="out"/>
<arg type="s" direction="out"/><arg type="s" direction="out"/>
</method>
<method name="Notify">
<arg type="s" direction="in"/><arg type="u" direction="in"/>
<arg type="s" direction="in"/><arg type="s" direction="in"/>
<arg type="s" direction="in"/><arg type="as" direction="in"/>
<arg type="a{sv}" direction="in"/><arg type="i" direction="in"/>
<arg type="u" direction="out"/>
</method>
<method name="CloseNotification"><arg type="u" direction="in"/></method>
<signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
<signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
</interface></node>'''


def run_scenario(scenario):
    # This entry point is invoked only inside dbus-run-session by the tests.
    from gi.repository import Gio, GLib
    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    reply = connection.call_sync(
        'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
        'RequestName', GLib.Variant('(su)', (INTERFACE, 4)),
        GLib.VariantType.new('(u)'), Gio.DBusCallFlags.NONE, 5000, None)
    assert reply.unpack() == (1,), 'Could not own isolated notification service'
    received = []
    closes = []

    def method_call(_connection, _sender, _path, _interface, method, parameters, invocation):
        if method == 'GetCapabilities':
            invocation.return_value(GLib.Variant('(as)', (['actions', 'body', 'body-markup'],)))
        elif method == 'GetServerInformation':
            invocation.return_value(GLib.Variant('(ssss)', ('Synthetic test', 'Tests', '1', '1.2')))
        elif method == 'Notify':
            received.append(parameters.unpack())
            if scenario == 'show_error':
                invocation.return_dbus_error('org.freedesktop.DBus.Error.Failed', 'Synthetic failure')
            else:
                invocation.return_value(GLib.Variant('(u)', (42,)))
        elif method == 'CloseNotification':
            closes.append(parameters.unpack())
            invocation.return_value(GLib.Variant('()', ()))
        else:
            invocation.return_dbus_error('org.freedesktop.DBus.Error.UnknownMethod', 'Unsupported')

    info = Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0]
    registration = connection.register_object(OBJECT_PATH, info, method_call, None, None)
    helper = None
    with tempfile.TemporaryDirectory(prefix='notification-integration-') as folder:
        folder = Path(folder)
        opened = folder / 'opened.json'
        stub = folder / 'xdg-open'
        stub.write_text('#!' + SYSTEM_PYTHON + '\nimport json, os, sys\n'
                        'from pathlib import Path\n'
                        'Path(os.environ["TEST_OPENED_PATH"]).write_text(json.dumps(sys.argv[1:]))\n')
        stub.chmod(0o700)
        env = dict(os.environ, PATH=str(folder), TEST_OPENED_PATH=str(opened))
        payload = json.dumps({'uuid': UID, 'title': TITLE, 'body': BODY})
        try:
            helper = subprocess.Popen(
                [SYSTEM_PYTHON, str(ROOT / 'jobs.py'), '--notify-job'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', env=env)
            helper.stdin.write(payload)
            helper.stdin.close()
            helper.stdin = None
            context = GLib.MainContext.default()

            def wait_until(predicate):
                deadline = time.monotonic() + 8
                while not predicate():
                    if time.monotonic() >= deadline:
                        raise AssertionError('Timed out waiting for isolated notification helper')
                    while context.pending():
                        context.iteration(False)
                    time.sleep(0.005)

            wait_until(lambda: bool(received))
            app, replacement, icon, title, body, actions, hints, timeout = received[0]
            assert app == 'ServiceM8', app
            assert icon == 'appointment-soon', icon
            assert title == html.escape('ServiceM8 · ' + TITLE), title
            assert body == html.escape(BODY), body
            assert actions == ['default', 'Open job'], actions
            assert timeout == 10000, timeout
            if scenario != 'show_error':
                assert helper.poll() is None, 'Helper should wait for notification action'
                command = Path('/proc', str(helper.pid), 'cmdline').read_bytes()
                environment = Path('/proc', str(helper.pid), 'environ').read_bytes()
                for private in (UID, TITLE, BODY, 'PRIVATE_TEST_SENTINEL'):
                    assert private.encode() not in command, 'Private data in argv'
                    assert private.encode() not in environment, 'Private data in environment'
                assert command.split(b'\0')[:-1] == [
                    SYSTEM_PYTHON.encode(), str(ROOT / 'jobs.py').encode(), b'--notify-job']
                if scenario == 'action':
                    signal, value = 'ActionInvoked', GLib.Variant('(us)', (42, 'default'))
                else:
                    signal, value = 'NotificationClosed', GLib.Variant('(uu)', (42, 2))
                connection.emit_signal(None, OBJECT_PATH, INTERFACE, signal, value)
                connection.flush_sync(None)
            wait_until(lambda: helper.poll() is not None)
            stdout, stderr = helper.communicate(timeout=2)
            assert helper.returncode == 0, (helper.returncode, stderr)
            assert not stdout, stdout
            assert 'PRIVATE_TEST_SENTINEL' not in stderr, stderr
            if scenario == 'action':
                wait_until(opened.exists)
                assert json.loads(opened.read_text()) == ['https://go.servicem8.com/OpenJob/' + UID]
                assert closes == [(42,)], closes
            else:
                assert not opened.exists(), 'Dismissal/failure must not open a browser'
        finally:
            if helper is not None and helper.poll() is None:
                helper.kill()
                helper.communicate(timeout=2)
            connection.unregister_object(registration)


class NotificationIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('dbus-run-session') or not Path('/proc/self/cmdline').exists():
            raise unittest.SkipTest('Requires dbus-run-session and Linux /proc')
        try:
            result = subprocess.run([SYSTEM_PYTHON, '-c',
                'from gi.repository import Gio, GLib; import ctypes; ctypes.CDLL("libnotify.so.4")'],
                capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            raise unittest.SkipTest('Requires system Python with GI/Gio and libnotify')
        if result.returncode:
            raise unittest.SkipTest('Requires system Python with GI/Gio and libnotify')
        env = dict(os.environ)
        for key in ('DBUS_SESSION_BUS_ADDRESS', 'DBUS_STARTER_ADDRESS', 'DBUS_STARTER_BUS_TYPE'):
            env.pop(key, None)
        with tempfile.TemporaryDirectory(prefix='notification-test-probe-') as runtime:
            env['XDG_RUNTIME_DIR'] = runtime
            try:
                probe = subprocess.run(
                    ['dbus-run-session', '--', SYSTEM_PYTHON, '-c', 'pass'],
                    env=env, capture_output=True, text=True, timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                raise unittest.SkipTest('Cannot start an isolated D-Bus session')
        if probe.returncode:
            raise unittest.SkipTest('Cannot start an isolated D-Bus session: ' + probe.stderr.strip())

    def scenario(self, name):
        env = dict(os.environ)
        # dbus-run-session supplies its own new bus address. Remove inherited
        # desktop addresses as an additional guard against accidental fallback.
        for key in ('DBUS_SESSION_BUS_ADDRESS', 'DBUS_STARTER_ADDRESS', 'DBUS_STARTER_BUS_TYPE'):
            env.pop(key, None)
        with tempfile.TemporaryDirectory(prefix='notification-test-runtime-') as runtime:
            env['XDG_RUNTIME_DIR'] = runtime
            result = subprocess.run(
                ['dbus-run-session', '--', SYSTEM_PYTHON, str(Path(__file__).resolve()), '--scenario', name],
                capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_libnotify_default_action_and_private_transport(self):
        self.scenario('action')

    def test_real_libnotify_close_without_action(self):
        self.scenario('closed')

    def test_real_libnotify_show_failure_does_not_open_browser(self):
        self.scenario('show_error')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--scenario':
        run_scenario(sys.argv[2])
    else:
        unittest.main()

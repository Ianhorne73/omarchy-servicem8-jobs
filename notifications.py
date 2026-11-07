"""Private desktop notifications using the system libnotify, not subprocess argv.

ctypes keeps Python dependency-free while retaining libnotify's session-bus
transport, markup, expiry and Open job action. No customer text is passed to a
command, environment variable, log or temporary file by this module.
"""
import ctypes as c


ActionCallback = c.CFUNCTYPE(None, c.c_void_p, c.c_char_p, c.c_void_p)
ClosedCallback = c.CFUNCTYPE(None, c.c_void_p, c.c_void_p)
TimeoutCallback = c.CFUNCTYPE(c.c_int, c.c_void_p)


def _libraries():
    notify = c.CDLL('libnotify.so.4')
    glib = c.CDLL('libglib-2.0.so.0')
    gobject = c.CDLL('libgobject-2.0.so.0')

    def bind(library, name, result, *arguments):
        function = getattr(library, name)
        function.restype = result
        function.argtypes = list(arguments)

    bind(notify, 'notify_init', c.c_int, c.c_char_p)
    bind(notify, 'notify_uninit', None)
    bind(notify, 'notify_notification_new', c.c_void_p, c.c_char_p, c.c_char_p, c.c_char_p)
    bind(notify, 'notify_notification_set_timeout', None, c.c_void_p, c.c_int)
    bind(notify, 'notify_notification_add_action', None, c.c_void_p, c.c_char_p,
         c.c_char_p, ActionCallback, c.c_void_p, c.c_void_p)
    bind(notify, 'notify_notification_show', c.c_int, c.c_void_p, c.POINTER(c.c_void_p))
    bind(notify, 'notify_notification_close', c.c_int, c.c_void_p, c.POINTER(c.c_void_p))
    bind(glib, 'g_main_loop_new', c.c_void_p, c.c_void_p, c.c_int)
    bind(glib, 'g_main_loop_run', None, c.c_void_p)
    bind(glib, 'g_main_loop_quit', None, c.c_void_p)
    bind(glib, 'g_main_loop_unref', None, c.c_void_p)
    bind(glib, 'g_timeout_add_seconds', c.c_uint, c.c_uint, TimeoutCallback, c.c_void_p)
    bind(glib, 'g_source_remove', c.c_int, c.c_uint)
    bind(glib, 'g_error_free', None, c.c_void_p)
    bind(gobject, 'g_signal_connect_data', c.c_ulong, c.c_void_p, c.c_char_p,
         ClosedCallback, c.c_void_p, c.c_void_p, c.c_int)
    bind(gobject, 'g_signal_handler_disconnect', None, c.c_void_p, c.c_ulong)
    bind(gobject, 'g_object_unref', None, c.c_void_p)
    return notify, glib, gobject


def show_notification(title, body):
    """Return True only for an explicit Open job action; fail closed otherwise."""
    if any(not isinstance(value, str) or '\0' in value for value in (title, body)):
        return False
    try:
        notify, glib, gobject = _libraries()
    except (OSError, AttributeError):
        return False
    if not notify.notify_init(b'ServiceM8'):
        return False
    loop = notification = None
    handler = timer = 0
    selected = finished = False
    try:
        loop = glib.g_main_loop_new(None, False)
        notification = notify.notify_notification_new(
            title.encode('utf-8'), body.encode('utf-8'), b'appointment-soon')
        if not loop or not notification:
            return False

        def finish():
            nonlocal finished
            finished = True
            glib.g_main_loop_quit(loop)

        @ActionCallback
        def action(_notification, name, _data):
            nonlocal selected
            selected = name == b'default'
            finish()

        @ClosedCallback
        def closed(_notification, _data):
            finish()

        @TimeoutCallback
        def expired(_data):
            nonlocal timer
            timer = 0  # GLib removes a source returning False itself.
            finish()
            return False

        # Keep the callback objects alive until after their notification is freed.
        notify.notify_notification_add_action(notification, b'default', b'Open job', action, None, None)
        handler = gobject.g_signal_connect_data(notification, b'closed', closed, None, None, 0)
        notify.notify_notification_set_timeout(notification, 10000)
        error = c.c_void_p()
        shown = notify.notify_notification_show(notification, c.byref(error))
        if error.value:
            glib.g_error_free(error)
        if not shown:
            return False
        # Some notification servers ignore the requested display timeout.
        timer = glib.g_timeout_add_seconds(120, expired, None)
        if not finished:
            glib.g_main_loop_run(loop)
        notify.notify_notification_close(notification, None)
        return selected
    finally:
        if timer:
            glib.g_source_remove(timer)
        if notification:
            if handler:
                gobject.g_signal_handler_disconnect(notification, handler)
            gobject.g_object_unref(notification)
        if loop:
            glib.g_main_loop_unref(loop)
        notify.notify_uninit()

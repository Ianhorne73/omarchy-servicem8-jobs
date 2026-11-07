# My Jobs Today

A ServiceM8 schedule widget for the Omarchy Quickshell bar. Browse a staff member’s jobs by day or week, open jobs in ServiceM8, copy job details, and optionally receive schedule alerts. This is an independent integration.

## Requirements

- Omarchy with the Quickshell shell and `bar-widget` plugin support (Quattro); this is not a Waybar module.
- Python 3.9+ with system timezone data, Git for installation, and an internet connection to ServiceM8.
- Your own ServiceM8 account and API key with read access to Staff, Job Activities (schedules), Job Allocations, Jobs and Companies (customers). Job Contacts read access enables site contact phone numbers; missing contact permission does not hide jobs.
- Optional: `wl-copy` (wl-clipboard) for clipboard actions, the system `libnotify` library for alerts, and `xdg-open` (xdg-utils) for notification links. Alerts use Python's built-in ctypes and libnotify directly, with no extra Python packages. Job and map links open in your default browser.

## Install

Install disabled so you can review the downloaded code, then explicitly enable it:

```bash
omarchy plugin add https://github.com/Ianhorne73/omarchy-servicem8-jobs.git
omarchy plugin enable servicem8.jobs --section right
```

The plugin installs under `~/.config/omarchy/plugins/servicem8.jobs/`. Omarchy manages the bar entry; there is no custom install script, privileged command or background service. Enabling explicitly adds the widget to your bar. No existing configuration is replaced by this repository.

For manual installation, copy `manifest.json`, `BarWidget.qml`, `jobs.py`, `notifications.py`, `schedule-icon.svg` and `monochrome.frag.qsb` into that folder. Back up `~/.config/omarchy/shell.json` before adding `{ "id": "servicem8.jobs" }` to a bar layout section.

## First connection

1. Click the schedule icon. A fresh installation displays Setup with no staff or jobs.
2. Create an API key in ServiceM8 → Settings → API Keys with the read permissions above.
3. Paste it into Setup and choose **Connect ServiceM8**. The widget validates staff access before saving it.
4. Choose a person from the API-provided staff list and click **Set default** to remember the selection. Switching the dropdown alone is temporary.

Every user supplies their own key; no account names, staff IDs or credentials are bundled. A saved key is reused on later loads. Setup can replace it; replacing the key resets the staff selection, while rejected keys leave the saved connection intact.

## Use

Day and Week controls browse the schedule; arrows step one day or seven days respectively. Enter a date, use the calendar, or choose Today. Closing the panel returns to today and the default staff member. Week view runs Monday–Sunday, including empty days and per-day errors. Historical dates show currently available records and current status, not an audit snapshot.

Scheduled appointments overlapping the selected day and pending flexible allocations appear together. Multiple appointments for one job share a card. Completed scheduled jobs stay visible. Current and Next labels reflect appointment times, not check-in status. The bar displays the next upcoming appointment today, or a job count otherwise.

Click a job to open it in ServiceM8. Cards offer Maps, Copy address, Copy job number and site contact phone actions; billing contacts are excluded. Long descriptions expand inline.

The widget checks every minute and refreshes API data every four minutes. Right-click or Refresh forces a fetch. Multiple monitors share private caches and a lock. On errors, only cached data for the selected account, staff member and date may remain visible, with the error and last update time.

Dates use a valid `TZ` environment timezone when set, otherwise Linux’s `/etc/localtime`, falling back to UTC. Daylight saving is handled automatically. Restart the shell after changing the system timezone.

Schedule alerts are off by default. Enabling them tracks new, moved and removed jobs for today and the saved default person, even while browsing another person or date. Each login, default change, new day or polling gap longer than three minutes establishes a silent baseline. Alerts run only while the widget is loaded in Omarchy; there are no queued catch-up notifications.

## Update and remove

```bash
omarchy plugin update servicem8.jobs
omarchy plugin disable servicem8.jobs
omarchy plugin remove servicem8.jobs
```

Update shows changes for review. Disable hides the widget; remove deletes the installed plugin. Saved credentials and customer caches remain so reinstalling can reuse them. To erase those too, remove these two directories after disabling the widget:

- `~/.config/omarchy/servicem8/` — API key and preferences.
- `~/.cache/omarchy/servicem8/` — staff/date caches, locks and alert state.

These data directories are shared by all installations of this widget. Manual installations must also remove their bar entry and plugin folder. Older manual installations using the previous plugin identifier must switch to `servicem8.jobs`; do not enable both copies. The data directory remains unchanged.

## Privacy

The API key is stored locally in plaintext in `~/.config/omarchy/servicem8/credentials.json` with owner-only permissions (0600); configuration and cache directories use 0700. It is passed to the helper through standard input, never command-line arguments, and sent in an HTTPS header only to the ServiceM8 API. API redirects are refused. Preferences and job caches are scoped to the connected credential.

Local data includes staff names, customer details, addresses, descriptions and site contact phone numbers. No analytics or developer server is used. Map actions send the chosen address to Google Maps. Desktop alerts may display customer/job information. Clipboard actions place the chosen value on your clipboard.

Notification payloads (including the job identifier) reach the detached helper through a private standard-input pipe. The helper sends display text directly to the desktop notification service using libnotify; it does not invoke `notify-send`. Clipboard values reach `wl-copy` through standard input, with no added newline. Neither path puts customer text in process arguments, environment variables or temporary files. Notification history and clipboard managers may retain the displayed/copied data according to desktop settings. Clicking **Open job** intentionally opens its UUID-based ServiceM8 URL using `xdg-open`.

Repository history uses synthetic staff examples and generic contributor identities. No embedded API key was found in the reviewed revisions. This cannot erase third-party copies of previously published history.

## Development and validation

```bash
python3 -m unittest discover -s . -p 'test_*.py' -v
omarchy plugin validate .
python3 build_release.py
```

The unit tests use synthetic fixtures and make no ServiceM8 requests. Clipboard JavaScript tests additionally use Node when available. The optional real-notification integration tests need Linux `/proc`, `dbus-run-session`, system Python with PyGObject/Gio, libnotify, and permission to create a private Unix socket. They use an isolated notification service and a stub browser, never the desktop notification service. Missing prerequisites produce an explicit skip; a skipped integration test is not a desktop validation pass.

The release ZIP in `dist/` includes an explicit file allowlist and excludes Git metadata, local account settings, caches and development previews. Never publish a copy of your installed configuration directory.

To rebuild the monochrome tint shader:

```bash
/usr/lib/qt6/bin/qsb --glsl "100 es,120,150" --hlsl 50 --msl 12 -o monochrome.frag.qsb monochrome.frag
```

ServiceM8 API references: [authentication](https://developer.servicem8.com/docs/authentication), [job activities](https://developer.servicem8.com/reference/listjobactivities), [job allocations](https://developer.servicem8.com/reference/listjoballocations), and [pagination](https://developer.servicem8.com/docs/pagination).

## License and marketplace

Code and the original schedule icon are covered by the [MIT license](LICENSE). ServiceM8 is a trademark of its respective owner; this project does not claim affiliation or endorsement. No ServiceM8 logo is distributed in the current release.

Prepared for the [Omarchy plugin marketplace](https://plugins.omarchy.org/publish.html). Submit this repository with category **Productivity**, tags **Bar** and **Quickshell**, and the maintainer notes below. The marketplace reviews listings; it does not certify plugin security.

### Submission details

- Repository: `https://github.com/Ianhorne73/omarchy-servicem8-jobs`
- Plugin ID: `servicem8.jobs`
- Title: `[Plugin]: My Jobs Today — ServiceM8 schedule`
- Category: Productivity
- Tags: Bar, Quickshell
- Preview: omitted (optional); no customer screenshots are supplied.
- Maintainer notes: ServiceM8 day/week schedule bar widget. Requires Omarchy Quickshell with bar-widget support, Python 3.9+, system timezone data and the user’s own ServiceM8 API key. Read access to Staff, Job Activities, Job Allocations, Jobs and Companies; Job Contacts is optional for phone details. Optional wl-clipboard, libnotify and xdg-utils. First use requires account setup and staff selection. Alerts default off. No custom installation hooks, elevated privileges or background service. MIT code and original schedule icon. Installation, removal, local credential storage and cache deletion are documented above.

Open the [submission form](https://github.com/omacom/omarchy-plugin-marketplace/issues/new?template=submit-plugin.yml), select the values above, and complete its required ownership/configuration/license acknowledgements. A public repository is required. Preparing this repository does not create the submission issue.

## Changes in 1.5.5

Fixes the marketplace review's process-command-line exposure: schedule alerts use private stdin and direct libnotify calls, and all clipboard actions use stdin. Adds regression coverage for notification transport, invalid input, action/close/timeout behavior, and clipboard command construction.

## Changes in 1.5.4

Adds the original schedule icon, default right-bar placement, and complete marketplace installation, removal, dependency, privacy and submission documentation. Version 1.5.3 introduced system timezone support and stronger credential storage/redirect protection; earlier versions added day/week browsing, contact actions and optional schedule alerts.

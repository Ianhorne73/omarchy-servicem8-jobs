# My Jobs Today

An Omarchy bar widget showing ServiceM8 jobs assigned to the selected staff member, using Australia/Brisbane dates. It reads scheduled appointments overlapping today and pending flexible allocations available today (including carried-forward allocations). Multiple appointments for the same job appear in one card. Completed scheduled jobs remain visible with their status.

Choose a person from the staff dropdown. **Set default** saves that person for future opens and restarts; simply switching the dropdown is temporary. Example Staff is the initial default. Staff choices refresh from ServiceM8 when staff read access is available, with the current account roster as a fallback. Preferences are stored in `~/.config/omarchy/servicem8/preferences.json`; each person has a separate job cache.

Click the **ServiceM8 icon → Setup**, paste a ServiceM8 API key, then choose **Connect ServiceM8**. Create the key in ServiceM8 Settings → API Keys with read access to schedules, jobs and customers. The key is validated before being saved. No key is included in this project or passed in command-line arguments. Credentials are stored in `~/.config/omarchy/servicem8/credentials.json` with mode 0600. Cached job data lives in `~/.cache/omarchy/servicem8/` with private permissions.

The widget checks every minute, fetching fresh data every four minutes. Opening the popup uses the cache when fresh. Refresh or right-click forces a fetch. Multiple monitors share the cache and a file lock. Errors retain only the current day's cached list, with the last update time. Click a card to open its job in ServiceM8. Setup can replace the key later.

Installed files: `~/.config/omarchy/plugins/servicem8.jobs/`. The bar entry is in `~/.config/omarchy/shell.json`; a timestamped backup is created at installation. Remove that entry to hide the widget.

Run backend checks with `python -m unittest discover -s . -p 'test_*.py' -v`.

API references: https://developer.servicem8.com/docs/authentication, https://developer.servicem8.com/reference/listjobactivities, https://developer.servicem8.com/reference/listjoballocations, https://developer.servicem8.com/docs/pagination.

Date selection: enter YYYY-MM-DD and press Enter or Go, use the previous/next day arrows, or choose Today. Closing the panel restores today and the default staff member. The bar tooltip and popup show the selected date. Caches are separated by staff and date. Past dates show currently available ServiceM8 records and current job status, not an audit snapshot.

The date controls are ordered Previous day → Date → Next day → Go → Calendar → Today. The calendar supports month navigation and loads jobs when a day is clicked. The monochrome ServiceM8 bar mark follows the desktop foreground colour.

To install on another Omarchy machine, copy `BarWidget.qml`, `jobs.py`, `manifest.json`, `servicem8-icon.png`, and `monochrome.frag.qsb` into `~/.config/omarchy/plugins/servicem8.jobs/`, then add `{ "id": "servicem8.jobs" }` to a bar layout section in `~/.config/omarchy/shell.json`. Connect your own API key through Setup. To rebuild the shader, run `/usr/lib/qt6/bin/qsb --glsl "100 es,120,150" --hlsl 50 --msl 12 -o monochrome.frag.qsb monochrome.frag`.

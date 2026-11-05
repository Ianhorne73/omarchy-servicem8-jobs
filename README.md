# My Jobs Today

An Omarchy bar widget showing ServiceM8 jobs assigned to the selected staff member, using Australia/Brisbane dates. It reads scheduled appointments overlapping today and pending flexible allocations available today (including carried-forward allocations). Multiple appointments for the same job appear in one card. Completed scheduled jobs remain visible with their status.

Choose a person from the staff dropdown. **Set default** saves that person for future opens and restarts; simply switching the dropdown is temporary. A fresh installation has no staff, default user or jobs. Connecting an API key loads active staff from that account; choose a person and click **Set default**. Staff read access is required. Preferences are stored in `~/.config/omarchy/servicem8/preferences.json`; each account, person and date has a separate job cache. Replacing the API key resets the staff selection and default; rejected keys leave the saved connection intact.

Click the **ServiceM8 icon → Setup**, paste a ServiceM8 API key, then choose **Connect ServiceM8**. Create the key in ServiceM8 Settings → API Keys with read access to staff, schedules, jobs and customers. The key is validated before being saved. No key is included in this project or passed in command-line arguments. Credentials are stored in `~/.config/omarchy/servicem8/credentials.json` with mode 0600. Cached job data lives in `~/.cache/omarchy/servicem8/` with private permissions.

The widget checks every minute, fetching fresh data every four minutes. Opening the popup uses the cache when fresh. Refresh or right-click forces a fetch. Multiple monitors share the cache and a file lock. Errors retain only the current day's cached list, with the last update time. Click a card to open its job in ServiceM8. Setup can replace the key later.

Installed files: `~/.config/omarchy/plugins/servicem8.jobs/`. The bar entry is in `~/.config/omarchy/shell.json`; a timestamped backup is created at installation. Remove that entry to hide the widget.

Run backend checks with `python -m unittest discover -s . -p 'test_*.py' -v`.

API references: https://developer.servicem8.com/docs/authentication, https://developer.servicem8.com/reference/listjobactivities, https://developer.servicem8.com/reference/listjoballocations, https://developer.servicem8.com/docs/pagination.

Date selection: enter YYYY-MM-DD and press Enter or Go, use the previous/next day arrows, or choose Today. Closing the panel restores today and the default staff member. The bar tooltip and popup show the selected date. Caches are separated by staff and date. Past dates show currently available ServiceM8 records and current job status, not an audit snapshot.

The date controls are ordered Previous day → Date → Next day → Go → Calendar → Today. The calendar supports month navigation and loads jobs when a day is clicked. The monochrome ServiceM8 bar mark follows the desktop foreground colour.

To install on another Omarchy machine, copy `BarWidget.qml`, `jobs.py`, `manifest.json`, `servicem8-icon.png`, and `monochrome.frag.qsb` into `~/.config/omarchy/plugins/servicem8.jobs/`, then add `{ "id": "servicem8.jobs" }` to a bar layout section in `~/.config/omarchy/shell.json`. Connect your own API key through Setup. To rebuild the shader, run `/usr/lib/qt6/bin/qsb --glsl "100 es,120,150" --hlsl 50 --msl 12 -o monochrome.frag.qsb monochrome.frag`.

No account staff names or IDs, keys, preferences, or cached jobs are shipped. The `servicem8.jobs` plugin ID and author metadata identify the plugin maintainer, not a required ServiceM8 account. Existing local settings migrate only after their staff ID is found in the connected account. This update does not publish to any add-on store. Schedule dates currently use Australia/Brisbane time.

The bar shows the next future scheduled appointment time for today (Brisbane time), excluding completed and unsuccessful jobs. When no upcoming appointment remains, or browsing another date, it shows the job count. Flexible allocations have no appointment time. Each job card includes Maps, Copy address and Copy job # actions; clicking the card itself still opens ServiceM8. Clipboard actions require `wl-copy`.

Version 1.3 adds job/site contact phone numbers with Copy actions (requires Job Contacts read permission; billing contacts are excluded), expandable long descriptions, and Current / Next labels on today’s active job cards. “Current · scheduled” is based on the appointment time, not check-in status. Phone lookup errors do not hide the schedule.

Version 1.3.1 places compact copy icons beside job numbers, addresses and phone numbers, with hover labels and a brief checkmark after copying. Maps opens from the arrow beside the address.

Version 1.3.2 replaces the full description button with a compact Show more / Show less text action, underlined on hover or keyboard focus.

Version 1.4 adds a Schedule alerts on/off switch in the popup. Alerts are off by default and the preference is saved locally. Notifications cover new jobs, changed appointment times, and jobs removed from today’s schedule for the saved default staff member, even while browsing another date/person. Enabling alerts, changing the default person, or starting a new day establishes a fresh silent baseline. Shared state prevents duplicate notifications across monitors or restarts. Updates follow the four-minute data refresh; the widget must be running. Notifications include an Open job action and require notify-send.

Version 1.4.1 limits alert polling to the live Omarchy Quickshell process. Each shell session/login starts with a fresh, silent baseline fetched from ServiceM8. Polling gaps longer than three minutes (including suspend/offline periods) also reset the baseline silently, so changes from downtime are not replayed. The on/off preference survives login. No background service or queued catch-up notifications are installed.

Version 1.5 adds Day / Week controls. Day remains the default when reopening. Week covers Monday–Sunday around the selected date for the selected staff member, highlights today, and shows empty days and per-day errors explicitly. Arrows step seven days in Week view; Today returns to the current week. Click a week entry to open its ServiceM8 job. Week uses the existing private per-day caches; alerts remain limited to today and the saved default person.

Version 1.5.2 unifies header controls with compact rounded buttons, subtle borders, and consistent fields and alert switch styling. Week headings use uppercase day names, a separate date line, stronger backgrounds and dividers to separate them from job entries.

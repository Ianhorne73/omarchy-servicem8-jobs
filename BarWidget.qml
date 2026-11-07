import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui as Ui

Ui.BarWidget {
    id: root
    moduleName: "servicem8.jobs"
    property var report: ({ jobs: [], needs_setup: false, error: "" })
    property double clockNow: Date.now()
    readonly property var nextJob: {
        var next = null
        if (report.date !== report.today || report.error) return null
        for (var i = 0; i < report.jobs.length; i++) {
            var job = report.jobs[i]
            if (job.status === "Completed" || job.status === "Unsuccessful") continue
            var starts = job.starts || []
            for (var j = 0; j < starts.length; j++) {
                var stamp = Date.parse(starts[j])
                if (stamp >= clockNow && (!next || stamp < next.stamp))
                    next = { stamp: stamp, time: starts[j].slice(11, 16), job: job }
            }
        }
        return next
    }
    function appointmentLabel(job) {
        if (report.date !== report.today || report.error || job.status === "Completed" || job.status === "Unsuccessful") return ""
        var slots = job.appointments || []
        for (var i = 0; i < slots.length; i++) {
            if (Date.parse(slots[i].start) <= clockNow && clockNow < Date.parse(slots[i].end)) return "Current · scheduled"
        }
        return nextJob && nextJob.job.uuid === job.uuid ? "Next" : ""
    }
    property string lastCopiedText: ""
    component InlineAction: ToolButton {
        property string hint: ""
        property string copyValue: ""
        text: copyValue && root.lastCopiedText === copyValue && root.copyMessage ? "✓" : "⧉"
        implicitWidth: 28
        implicitHeight: 28
        padding: 3
        font.pixelSize: 16
        hoverEnabled: true
        Accessible.name: hint
        ToolTip.visible: hovered
        ToolTip.delay: 500
        ToolTip.text: hint
    }
    component HeaderButton: Button {
        id: control
        implicitHeight: 32
        implicitWidth: Math.max(32, implicitContentWidth + 22)
        padding: 8
        hoverEnabled: true
        contentItem: Text {
            text: control.text
            color: root.ink
            opacity: control.enabled ? 1 : 0.4
            font.pixelSize: control.font.pixelSize
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        font.pixelSize: 12
        background: Rectangle {
            radius: 7
            color: Qt.rgba(root.ink.r, root.ink.g, root.ink.b, control.down || control.checked ? 0.18 : control.hovered ? 0.12 : 0.06)
            border.width: 1
            border.color: Qt.rgba(root.ink.r, root.ink.g, root.ink.b, control.activeFocus ? 0.65 : 0.12)
            Behavior on color { ColorAnimation { duration: 120 } }
        }
    }
    component HeaderField: TextField {
        id: field
        implicitHeight: 32
        leftPadding: 10
        rightPadding: 10
        color: root.ink
        placeholderTextColor: Qt.rgba(root.ink.r, root.ink.g, root.ink.b, 0.5)
        font.pixelSize: 12
        background: Rectangle {
            radius: 7
            color: Qt.rgba(root.ink.r, root.ink.g, root.ink.b, 0.035)
            border.width: 1
            border.color: Qt.rgba(root.ink.r, root.ink.g, root.ink.b, field.activeFocus ? 0.65 : 0.14)
        }
    }
    property string copyMessage: ""
    function copyText(value, label) {
        if (copier.running) return
        copier.value = String(value)
        copier.label = label
        copier.stdinEnabled = true
        copier.running = true
    }
    property bool weekMode: false
    property string selectedStaff: ""
    property string selectedDate: ""
    property string dateError: ""
    property bool calendarVisible: false
    property date calendarMonth: new Date()
    property bool opened: false
    property bool setupVisible: false
    readonly property bool busy: fetcher.running || saver.running || defaultSaver.running || alertSaver.running
    readonly property string helper: Qt.resolvedUrl("jobs.py").toString().replace(/^file:\/\//, "")
    readonly property color ink: bar ? bar.foreground : "#eeeeee"
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight

    function refresh(force) {
        if (busy) return
        fetcher.command = ["python3", root.helper].concat(root.selectedStaff ? ["--staff", root.selectedStaff] : []).concat(root.selectedDate ? ["--date", root.selectedDate] : []).concat(root.weekMode ? ["--week"] : []).concat(force ? ["--force"] : [])
        fetcher.running = true
    }
    function acceptReport(data) {
        try {
            root.report = JSON.parse(data)
            if (root.opened) root.selectedStaff = root.report.staff_uuid || ""
            dateField.text = root.report.date || ""
            if (!root.opened && (root.report.date !== root.report.today || root.report.staff_uuid !== root.report.default_staff)) Qt.callLater(function() { root.refresh(false) })
            if (!root.report.needs_setup) root.setupVisible = false
            if (root.weekMode && !root.report.week_days && !root.report.needs_setup && !root.report.needs_staff) Qt.callLater(function() { root.refresh(false) })
        } catch (e) {
            root.report = { jobs: [], error: "Could not read the schedule. Please refresh.", needs_setup: false }
        }
    }
    function open() { opened = true; refresh(false) }
    function close() { weekMode = false; calendarVisible = false; opened = false; apiKey.text = ""; selectedStaff = ""; selectedDate = ""; dateError = ""; refresh(false) }
    function closeForPopoutSwitch() { close() }
    function toggle() { if (opened) close(); else open() }
    function chooseDate(value) {
        if (busy) return
        if (value !== "") {
            var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
            var parsed = match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]), 12) : null
            if (!parsed || parsed.getFullYear() !== Number(match[1]) || parsed.getMonth() !== Number(match[2]) - 1 || parsed.getDate() !== Number(match[3])) {
                dateError = "Enter a valid date as YYYY-MM-DD."
                return
            }
        }
        calendarVisible = false
        dateError = ""
        selectedDate = value
        root.report = Object.assign({}, root.report, { jobs: [], updated: "", error: "", date: value })
        refresh(false)
    }
    function showCalendar() {
        var parts = (root.report.date || "").split("-")
        calendarMonth = parts.length === 3 ? new Date(Number(parts[0]), Number(parts[1]) - 1, 1, 12) : new Date()
        calendarVisible = !calendarVisible
    }
    function moveMonth(delta) {
        calendarMonth = new Date(calendarMonth.getFullYear(), calendarMonth.getMonth() + delta, 1, 12)
    }
    function calendarDay(index) {
        var first = new Date(calendarMonth.getFullYear(), calendarMonth.getMonth(), 1, 12)
        var offset = (first.getDay() + 6) % 7
        return new Date(first.getFullYear(), first.getMonth(), 1 - offset + index, 12)
    }
    function dateLabel(value) {
        var parts = (value || "").split("-")
        if (parts.length !== 3) return value || "Today"
        var date = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]), 12)
        return Qt.formatDate(date, "dddd, d MMMM yyyy")
    }
    function stepDate(days) {
        var parts = (root.report.date || dateField.text).split("-")
        if (parts.length !== 3) return
        var date = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]) + days, 12)
        chooseDate(Qt.formatDate(date, "yyyy-MM-dd"))
    }
    function makeDefault() {
        if (busy || !root.report.staff_uuid) return
        defaultSaver.command = ["python3", root.helper, "--staff", root.report.staff_uuid, "--set-default", root.report.staff_uuid].concat(root.selectedDate ? ["--date", root.selectedDate] : [])
        defaultSaver.running = true
    }
    function setAlerts(enabled) {
        if (busy) return
        alertSaver.command = ["python3", root.helper, "--set-alerts", enabled ? "on" : "off"].concat(root.selectedStaff ? ["--staff", root.selectedStaff] : []).concat(root.selectedDate ? ["--date", root.selectedDate] : [])
        alertSaver.running = true
    }
    function pollAlerts() {
        if (!alertPoller.running && !alertSaver.running) alertPoller.running = true
    }
    function saveKey() {
        if (busy || !apiKey.text.trim()) return
        saver.secret = apiKey.text.trim()
        apiKey.text = ""
        saver.running = true
    }
    Component.onCompleted: { refresh(false); pollAlerts() }
    Timer { interval: 60000; running: true; repeat: true; onTriggered: { root.clockNow = Date.now(); root.refresh(false); root.pollAlerts() } }
    Process {
        id: alertSaver
        stdout: StdioCollector { onStreamFinished: { root.acceptReport(text); root.pollAlerts() } }
    }
    Process {
        id: alertPoller
        command: ["python3", root.helper, "--poll-alerts"]
    }
    Process {
        id: copier
        property string value: ""
        property string label: ""
        command: ["wl-copy"]
        onStarted: {
            write(value)
            stdinEnabled = false // Close after queued bytes are written: wl-copy reads to EOF.
        }
        onExited: function(code, status) {
            root.lastCopiedText = code === 0 ? value : ""
            value = ""
            root.copyMessage = code === 0 ? label + " copied" : "Could not copy to clipboard"
            copyFeedback.restart()
        }
    }
    Timer { id: copyFeedback; interval: 2500; onTriggered: root.copyMessage = "" }
    Process {
        id: fetcher
        stdout: StdioCollector { onStreamFinished: root.acceptReport(text) }
    }
    Process {
        id: saver
        property string secret: ""
        command: ["python3", root.helper, "--save-key"].concat(root.selectedStaff ? ["--staff", root.selectedStaff] : []).concat(root.selectedDate ? ["--date", root.selectedDate] : [])
        stdinEnabled: true
        onStarted: { write(secret + "\n"); secret = "" }
        stdout: StdioCollector { onStreamFinished: root.acceptReport(text) }
    }
    Process {
        id: defaultSaver
        stdout: StdioCollector { onStreamFinished: root.acceptReport(text) }
    }
    Ui.WidgetButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        text: root.report.needs_setup ? "Setup" : root.report.needs_staff ? "—" : root.report.error ? "!" : root.busy && !root.report.updated ? "…" : (root.nextJob ? root.nextJob.time : String(root.report.jobs.length))
        labelVisible: false
        fixedWidth: root.vertical ? -1 : logoRow.implicitWidth + Style.space(17)
        fixedHeight: root.vertical ? logoRow.implicitHeight + Style.space(12) : -1
        Row {
            id: logoRow
            anchors.centerIn: parent
            spacing: Style.space(6)
            Image {
                source: Qt.resolvedUrl("schedule-icon.svg")
                width: Style.space(18)
                height: width
                anchors.verticalCenter: parent.verticalCenter
                fillMode: Image.PreserveAspectFit
                smooth: true
                layer.enabled: true
                layer.effect: ShaderEffect {
                    property color tint: button.foreground
                    fragmentShader: Qt.resolvedUrl("monochrome.frag.qsb")
                }
            }
            Text {
                text: button.text
                textFormat: Text.PlainText
                color: button.foreground
                font.family: button.fontFamily
                font.pixelSize: button.fontSize
                anchors.verticalCenter: parent.verticalCenter
            }
        }
        tooltipText: "ServiceM8 jobs · " + root.dateLabel(root.report.date) + " · " + (root.report.staff_name || "Choose staff") + (root.nextJob ? "\nNext: " + root.nextJob.time + " · " + root.nextJob.job.customer : "") + "\n" + root.report.jobs.length + " jobs · Click to view · Right-click to refresh"
        onPressed: function(b) { if (b === Qt.RightButton || b === Qt.MiddleButton) root.refresh(true); else root.toggle() }
    }
    Ui.KeyboardPanel {
        id: panel
        anchorItem: button
        bar: root.bar
        owner: root
        open: root.opened
        contentWidth: panel.fittedContentWidth(Style.space(470))
        contentHeight: panel.fittedContentHeight(Style.space(root.weekMode ? 650 : 540))
        focusTarget: content

        FocusScope {
            id: content
            anchors.fill: parent
            Keys.onEscapePressed: { if (root.calendarVisible) root.calendarVisible = false; else root.close() }
            Column {
                id: header
                width: parent.width
                spacing: 8
                Text { text: root.weekMode ? "My Jobs · Week" : root.selectedDate ? "My Jobs" : "My Jobs Today"; color: root.ink; font.pixelSize: 23; font.bold: true }
                Text { width: parent.width; text: (root.report.staff_name || "Choose staff") + " · " + root.dateLabel(root.report.date) + " · Local time"; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: root.ink; opacity: 0.7; font.pixelSize: 12 }
                Row {
                    width: parent.width
                    spacing: 8
                    ComboBox {
                        id: staffPicker
                        implicitHeight: 32
                        leftPadding: 10
                        rightPadding: 28
                        font.pixelSize: 12
                        contentItem: Text {
                            text: staffPicker.displayText
                            color: root.ink
                            opacity: staffPicker.enabled ? 1 : 0.4
                            font.pixelSize: 12
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                        }
                        indicator: Text {
                            x: staffPicker.width - width - 10
                            anchors.verticalCenter: parent.verticalCenter
                            text: "⌄"; color: root.ink; opacity: 0.65
                        }
                        background: Rectangle {
                            radius: 7
                            color: Qt.rgba(root.ink.r, root.ink.g, root.ink.b, 0.04)
                            border.width: 1
                            border.color: Qt.rgba(root.ink.r, root.ink.g, root.ink.b, staffPicker.activeFocus ? 0.65 : 0.14)
                        }
                        displayText: currentIndex < 0 ? "Choose staff member…" : currentText
                        width: parent.width - defaultButton.width - 8
                        model: root.report.staff || []
                        textRole: "name"
                        enabled: !root.busy && (root.report.staff || []).length > 0
                        currentIndex: {
                            var people = root.report.staff || []
                            for (var i = 0; i < people.length; i++)
                                if (people[i].uuid === root.report.staff_uuid) return i
                            return -1
                        }
                        onActivated: function(index) {
                            root.selectedStaff = root.report.staff[index].uuid
                            // Clear the previous person's cards before fetching.
                            root.report = Object.assign({}, root.report, { jobs: [], updated: "", error: "", staff_uuid: root.selectedStaff, staff_name: root.report.staff[index].name })
                            root.refresh(false)
                        }
                    }
                    HeaderButton {
                        id: defaultButton
                        text: root.report.staff_uuid === root.report.default_staff ? "Default ✓" : "Set default"
                        enabled: !root.busy && !!root.report.staff_uuid && root.report.staff_uuid !== root.report.default_staff
                        onClicked: root.makeDefault()
                    }
                }
                Row {
                    width: parent.width
                    spacing: 6
                    HeaderButton { id: previousDay; implicitWidth: 30; text: "‹"; enabled: !root.busy; onClicked: root.stepDate(root.weekMode ? -7 : -1); Accessible.name: root.weekMode ? "Previous week" : "Previous day" }
                    HeaderField {
                        id: dateField
                        width: parent.width - previousDay.width - goDate.width - nextDay.width - todayButton.width - calendarButton.width - 30
                        placeholderText: "YYYY-MM-DD"
                        selectByMouse: true
                        enabled: !root.busy
                        onAccepted: root.chooseDate(text.trim())
                        Accessible.name: "Job date, YYYY-MM-DD"
                    }
                    HeaderButton { id: nextDay; implicitWidth: 30; text: "›"; enabled: !root.busy; onClicked: root.stepDate(root.weekMode ? 7 : 1); Accessible.name: root.weekMode ? "Next week" : "Next day" }
                    HeaderButton { id: goDate; implicitWidth: 42; text: "Go"; enabled: !root.busy; onClicked: root.chooseDate(dateField.text.trim()) }
                    HeaderButton { id: calendarButton; implicitWidth: previousDay.implicitWidth; implicitHeight: previousDay.implicitHeight; width: previousDay.width; height: previousDay.height; padding: 0; font.pixelSize: Math.round(previousDay.font.pixelSize * 0.8); text: "▦"; enabled: !root.busy; onClicked: root.showCalendar(); Accessible.name: "Choose date from calendar" }
                    HeaderButton { id: todayButton; implicitWidth: 62; text: "Today"; enabled: !root.busy; onClicked: root.chooseDate("") }
                }
                Rectangle {
                    width: 148
                    height: 32
                    radius: 8
                    color: Qt.rgba(root.ink.r, root.ink.g, root.ink.b, 0.06)
                    border.width: 1
                    border.color: Qt.rgba(root.ink.r, root.ink.g, root.ink.b, 0.12)
                    Row {
                        anchors.fill: parent
                        anchors.margins: 3
                        spacing: 2
                        Repeater {
                            model: ["Day", "Week"]
                            delegate: ToolButton {
                                id: viewSegment
                                required property int index
                                required property string modelData
                                readonly property bool selected: root.weekMode === (index === 1)
                                width: 70
                                height: 26
                                padding: 0
                                enabled: !root.busy
                                hoverEnabled: true
                                Accessible.name: modelData + " view"
                                Accessible.checkable: true
                                Accessible.checked: selected
                                background: Rectangle {
                                    radius: 5
                                    color: Qt.rgba(root.ink.r, root.ink.g, root.ink.b, viewSegment.selected ? 0.15 : viewSegment.hovered || viewSegment.activeFocus ? 0.08 : 0)
                                    border.width: viewSegment.activeFocus ? 1 : 0
                                    border.color: root.ink
                                    Behavior on color { ColorAnimation { duration: 120 } }
                                }
                                contentItem: Text {
                                    text: viewSegment.modelData
                                    color: root.ink
                                    opacity: viewSegment.enabled ? (viewSegment.selected ? 1 : 0.65) : 0.4
                                    font.pixelSize: 12
                                    font.bold: viewSegment.selected
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                                onClicked: {
                                    if (selected) return
                                    root.weekMode = index === 1
                                    root.refresh(false)
                                }
                            }
                        }
                    }
                }
                Text { visible: root.dateError !== ""; text: root.dateError; color: root.ink; font.pixelSize: 12 }
                Row {
                    spacing: 8
                    HeaderButton { text: root.busy ? "Loading…" : "Refresh"; enabled: !root.busy; onClicked: root.refresh(true) }
                    HeaderButton { text: "Setup"; onClicked: root.setupVisible = !root.setupVisible }
                    HeaderButton { text: "ServiceM8"; onClicked: Qt.openUrlExternally("https://go.servicem8.com/") }
                }
                Switch {
                    id: alertSwitch
                    implicitHeight: 30
                    padding: 0
                    spacing: 8
                    hoverEnabled: true
                    indicator: Rectangle {
                        implicitWidth: 30
                        implicitHeight: 17
                        x: 0
                        y: (alertSwitch.height - height) / 2
                        radius: 9
                        color: Qt.rgba(root.ink.r, root.ink.g, root.ink.b, alertSwitch.checked ? 0.3 : 0.08)
                        border.width: 1
                        border.color: Qt.rgba(root.ink.r, root.ink.g, root.ink.b, alertSwitch.activeFocus ? 0.7 : 0.2)
                        opacity: alertSwitch.enabled ? 1 : 0.4
                        Rectangle {
                            width: 11; height: 11; radius: 6
                            y: 3
                            x: alertSwitch.checked ? 16 : 3
                            color: root.ink
                            opacity: alertSwitch.checked ? 1 : 0.5
                            Behavior on x { NumberAnimation { duration: 120 } }
                        }
                    }
                    contentItem: Text {
                        leftPadding: 38
                        text: alertSwitch.text
                        color: root.ink
                        opacity: alertSwitch.enabled ? 0.85 : 0.4
                        font.pixelSize: 12
                        verticalAlignment: Text.AlignVCenter
                    }
                    text: "Schedule alerts " + (checked ? "on" : "off")
                    checked: !!root.report.alerts_enabled
                    enabled: !root.busy && !!root.report.default_staff && !root.report.needs_setup
                    onClicked: root.setAlerts(!root.report.alerts_enabled)
                    ToolTip.visible: hovered
                    ToolTip.text: "Today’s schedule changes for your default staff member"
                }
                Text {
                    width: parent.width
                    visible: text !== ""
                    text: root.copyMessage || root.report.error || (root.report.needs_staff ? "Choose a staff member, then Set default to remember your choice." : root.report.updated ? "Updated " + root.report.updated + " · refreshes every 4 minutes" : "")
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: root.ink
                    opacity: 0.8
                    font.pixelSize: 12
                }
                Column {
                    width: parent.width
                    visible: root.setupVisible || root.report.needs_setup
                    spacing: 8
                    Text {
                        width: parent.width
                        text: "Create a key in ServiceM8 → Settings → API Keys, with read access to staff, schedules, jobs, customers and Job Contacts. Paste it below."
                        textFormat: Text.PlainText
                        color: root.ink; wrapMode: Text.Wrap; font.pixelSize: 13
                    }
                    HeaderField {
                        id: apiKey
                        width: parent.width
                        placeholderText: "ServiceM8 API key"
                        echoMode: TextInput.Password
                        selectByMouse: true
                        onAccepted: root.saveKey()
                    }
                    HeaderButton { text: root.busy ? "Connecting…" : "Connect ServiceM8"; enabled: !root.busy && apiKey.text.trim() !== ""; onClicked: root.saveKey() }
                    Text { width: parent.width; text: "Stored privately on this computer. The widget only reads jobs."; color: root.ink; opacity: 0.7; wrapMode: Text.Wrap; font.pixelSize: 11 }
                }
            }
            Column {
                id: calendar
                visible: root.calendarVisible
                anchors { top: header.bottom; topMargin: 14; left: parent.left; right: parent.right }
                spacing: 6
                Row {
                    width: parent.width
                    HeaderButton { id: prevMonth; implicitWidth: 36; text: "‹"; onClicked: root.moveMonth(-1); Accessible.name: "Previous month" }
                    Text {
                        width: parent.width - prevMonth.width - nextMonth.width
                        height: prevMonth.height
                        text: Qt.formatDate(root.calendarMonth, "MMMM yyyy")
                        color: root.ink
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        font.pixelSize: 16
                    }
                    HeaderButton { id: nextMonth; implicitWidth: 36; text: "›"; onClicked: root.moveMonth(1); Accessible.name: "Next month" }
                }
                Row {
                    width: parent.width
                    Repeater {
                        model: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                        delegate: Text {
                            required property string modelData
                            width: calendar.width / 7
                            text: modelData
                            color: root.ink
                            opacity: 0.7
                            horizontalAlignment: Text.AlignHCenter
                            font.pixelSize: 12
                        }
                    }
                }
                Grid {
                    width: parent.width
                    columns: 7
                    Repeater {
                        model: 42
                        delegate: HeaderButton {
                            required property int index
                            readonly property date day: root.calendarDay(index)
                            readonly property string isoDate: Qt.formatDate(day, "yyyy-MM-dd")
                            width: calendar.width / 7
                            height: Style.space(33)
                            text: String(day.getDate())
                            flat: true
                            highlighted: isoDate === root.report.date
                            opacity: day.getMonth() === root.calendarMonth.getMonth() ? 1 : 0.4
                            enabled: !root.busy
                            Accessible.name: Qt.formatDate(day, "dddd d MMMM yyyy")
                            onClicked: root.chooseDate(isoDate)
                        }
                    }
                }
            }
            Flickable {
                visible: !root.calendarVisible && root.weekMode
                anchors { top: header.bottom; topMargin: 14; bottom: parent.bottom; left: parent.left; right: parent.right }
                contentHeight: weekColumn.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                Column {
                    id: weekColumn
                    width: parent.width
                    spacing: 18
                    Text {
                        visible: root.busy
                        text: "Loading week…"
                        color: root.ink
                    }
                    Repeater {
                        model: root.busy ? [] : root.report.week_days || []
                        delegate: Column {
                            id: dayGroup
                            required property var modelData
                            width: weekColumn.width
                            spacing: 5
                            Rectangle {
                                width: parent.width
                                height: dayHeading.implicitHeight + 20
                                radius: 6
                                color: Qt.rgba(root.ink.r, root.ink.g, root.ink.b, dayGroup.modelData.date === root.report.today ? 0.20 : 0.11)
                                Rectangle {
                                    width: 3
                                    anchors { left: parent.left; top: parent.top; bottom: parent.bottom; margins: 5 }
                                    radius: 2
                                    color: root.ink
                                    opacity: dayGroup.modelData.date === root.report.today ? 0.9 : 0.35
                                }
                                Column {
                                    id: dayHeading
                                    x: 14; y: 10
                                    width: parent.width - 28
                                    spacing: 3
                                    Text {
                                        width: parent.width
                                        text: root.dateLabel(dayGroup.modelData.date).split(",")[0].toUpperCase() + (dayGroup.modelData.date === root.report.today ? " · TODAY" : "")
                                        color: root.ink; font.bold: true; font.pixelSize: 15; font.letterSpacing: 1; wrapMode: Text.Wrap
                                    }
                                    Text {
                                        width: parent.width
                                        text: root.dateLabel(dayGroup.modelData.date).split(",").slice(1).join(",").trim()
                                        color: root.ink; opacity: 0.75; font.pixelSize: 11
                                    }
                                }
                                Rectangle {
                                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                                    height: 1
                                    color: root.ink
                                    opacity: 0.18
                                }
                            }
                            Text {
                                width: parent.width
                                visible: !!dayGroup.modelData.error || dayGroup.modelData.jobs.length === 0
                                text: dayGroup.modelData.error || "No jobs scheduled"
                                textFormat: Text.PlainText
                                color: root.ink; opacity: 0.7; font.pixelSize: 12; wrapMode: Text.Wrap
                            }
                            Repeater {
                                model: dayGroup.modelData.jobs
                                delegate: ToolButton {
                                    id: weekJob
                                    required property var modelData
                                    width: dayGroup.width
                                    padding: 8
                                    hoverEnabled: true
                                    background: Rectangle {
                                        radius: 5
                                        color: Qt.rgba(root.ink.r, root.ink.g, root.ink.b, weekJob.hovered ? 0.12 : 0.04)
                                    }
                                    contentItem: Column {
                                        spacing: 3
                                        Text { width: parent.width; text: modelData.time + " · " + modelData.status; textFormat: Text.PlainText; color: root.ink; font.pixelSize: 12; wrapMode: Text.Wrap }
                                        Text { width: parent.width; text: "#" + modelData.number + " · " + modelData.customer; textFormat: Text.PlainText; color: root.ink; font.pixelSize: 14; font.bold: true; wrapMode: Text.Wrap }
                                    }
                                    Accessible.name: "View job " + modelData.number + " on " + dayGroup.modelData.date
                                    onClicked: Qt.openUrlExternally("https://go.servicem8.com/OpenJob/" + encodeURIComponent(modelData.uuid))
                                }
                            }
                        }
                    }
                }
            }
            Flickable {
                visible: !root.calendarVisible && !root.weekMode
                anchors { top: header.bottom; topMargin: 14; bottom: parent.bottom; left: parent.left; right: parent.right }
                contentHeight: jobsColumn.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                Column {
                    id: jobsColumn
                    width: parent.width
                    spacing: 10
                    Text {
                        visible: root.report.jobs.length === 0 && !root.report.needs_setup && !root.report.needs_staff && !root.report.error && !root.busy
                        text: "No jobs assigned for " + (root.report.date || "this date") + "."
                        color: root.ink
                        font.pixelSize: 15
                    }
                    Repeater {
                        model: root.report.jobs
                        delegate: Rectangle {
                            id: card
                            required property var modelData
                            property bool descriptionExpanded: false
                            width: jobsColumn.width
                            height: details.implicitHeight + 24
                            radius: 8
                            color: Qt.rgba(root.ink.r, root.ink.g, root.ink.b, jobMouse.containsMouse ? 0.12 : 0.06)
                            Column {
                                id: details
                                z: 1
                                x: 12; y: 12
                                width: parent.width - 24
                                spacing: 5
                                Text {
                                    visible: text !== ""
                                    text: root.appointmentLabel(card.modelData)
                                    color: root.ink; font.bold: true; font.pixelSize: 12
                                }
                                Text { width: parent.width; text: card.modelData.time + "   ·   " + card.modelData.status; textFormat: Text.PlainText; color: root.ink; font.pixelSize: 12; wrapMode: Text.Wrap }
                                Row {
                                    width: parent.width
                                    spacing: 5
                                    Row {
                                        id: jobNumberRow
                                        spacing: 3
                                        visible: !!card.modelData.number
                                        Text {
                                            text: "#" + card.modelData.number
                                            anchors.verticalCenter: parent.verticalCenter
                                            color: root.ink; font.bold: true; font.pixelSize: 16
                                            textFormat: Text.PlainText
                                        }
                                        InlineAction {
                                            hint: "Copy job number"
                                            copyValue: card.modelData.number || ""
                                            enabled: !copier.running
                                            onClicked: root.copyText(copyValue, "Job number")
                                        }
                                    }
                                    Text {
                                        width: parent.width - (jobNumberRow.visible ? jobNumberRow.width + 5 : 0)
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: card.modelData.customer
                                        textFormat: Text.PlainText
                                        color: root.ink; font.bold: true; font.pixelSize: 16; wrapMode: Text.Wrap
                                    }
                                }
                                Row {
                                    width: parent.width
                                    spacing: 3
                                    visible: !!card.modelData.address
                                    Text {
                                        width: Math.min(implicitWidth, parent.width - copyAddress.width - mapsAction.width - 6)
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: card.modelData.address
                                        textFormat: Text.PlainText
                                        color: root.ink; font.pixelSize: 13; wrapMode: Text.Wrap
                                    }
                                    InlineAction {
                                        id: copyAddress
                                        hint: "Copy address"
                                        copyValue: card.modelData.address || ""
                                        enabled: !copier.running
                                        onClicked: root.copyText(copyValue, "Address")
                                    }
                                    InlineAction {
                                        id: mapsAction
                                        text: "↗"
                                        hint: "Open address in Maps"
                                        onClicked: Qt.openUrlExternally("https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent(card.modelData.address))
                                    }
                                }
                                Repeater {
                                    model: card.modelData.phones || []
                                    delegate: Row {
                                        required property var modelData
                                        width: details.width
                                        spacing: 8
                                        Text {
                                            width: Math.min(implicitWidth, parent.width - copyPhone.width - 8)
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: modelData.label + ": " + modelData.number
                                            textFormat: Text.PlainText
                                            color: root.ink; font.pixelSize: 12; wrapMode: Text.Wrap
                                        }
                                        InlineAction {
                                            id: copyPhone
                                            hint: "Copy phone number"
                                            copyValue: modelData.number
                                            enabled: !copier.running
                                            onClicked: root.copyText(modelData.number, "Phone number")
                                            Accessible.name: "Copy phone number"
                                        }
                                    }
                                }
                                Text {
                                    width: parent.width
                                    visible: text !== ""
                                    text: card.modelData.phone_error || (!(card.modelData.phones || []).length ? "No job contact phone number" : "")
                                    textFormat: Text.PlainText
                                    color: root.ink; opacity: 0.7; font.pixelSize: 11; wrapMode: Text.Wrap
                                }
                                Text { id: description; width: parent.width; visible: text !== ""; text: card.modelData.description; textFormat: Text.PlainText; color: root.ink; opacity: 0.75; font.pixelSize: 12; wrapMode: Text.Wrap; maximumLineCount: card.descriptionExpanded ? 2147483647 : 4; elide: card.descriptionExpanded ? Text.ElideNone : Text.ElideRight }
                                ToolButton {
                                    id: descriptionToggle
                                    visible: card.descriptionExpanded || description.truncated
                                    text: card.descriptionExpanded ? "Show less ▴" : "Show more ▾"
                                    padding: 0
                                    topPadding: 3
                                    bottomPadding: 3
                                    hoverEnabled: true
                                    background: Item {}
                                    contentItem: Text {
                                        text: descriptionToggle.text
                                        color: root.ink
                                        opacity: descriptionToggle.hovered || descriptionToggle.activeFocus ? 1 : 0.75
                                        font.pixelSize: 12
                                        font.underline: descriptionToggle.hovered || descriptionToggle.activeFocus
                                    }
                                    Accessible.name: card.descriptionExpanded ? "Collapse job description" : "Read full job description"
                                    onClicked: card.descriptionExpanded = !card.descriptionExpanded
                                }
                            }
                            MouseArea { id: jobMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Qt.openUrlExternally("https://go.servicem8.com/OpenJob/" + encodeURIComponent(card.modelData.uuid)) }
                        }
                    }
                }
            }
        }
    }
}

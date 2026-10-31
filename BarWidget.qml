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
    property string selectedStaff: ""
    property string selectedDate: ""
    property string dateError: ""
    property bool calendarVisible: false
    property date calendarMonth: new Date()
    property bool opened: false
    property bool setupVisible: false
    readonly property bool busy: fetcher.running || saver.running || defaultSaver.running
    readonly property string helper: Qt.resolvedUrl("jobs.py").toString().replace(/^file:\/\//, "")
    readonly property color ink: bar ? bar.foreground : "#eeeeee"
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight

    function refresh(force) {
        if (busy) return
        fetcher.command = ["python3", root.helper].concat(root.selectedStaff ? ["--staff", root.selectedStaff] : []).concat(root.selectedDate ? ["--date", root.selectedDate] : []).concat(force ? ["--force"] : [])
        fetcher.running = true
    }
    function acceptReport(data) {
        try {
            root.report = JSON.parse(data)
            if (root.opened) root.selectedStaff = root.report.staff_uuid || ""
            dateField.text = root.report.date || ""
            if (!root.opened && (root.report.date !== root.report.today || root.report.staff_uuid !== root.report.default_staff)) Qt.callLater(function() { root.refresh(false) })
            if (!root.report.needs_setup) root.setupVisible = false
        } catch (e) {
            root.report = { jobs: [], error: "Could not read the schedule. Please refresh.", needs_setup: false }
        }
    }
    function open() { opened = true; refresh(false) }
    function close() { calendarVisible = false; opened = false; apiKey.text = ""; selectedStaff = ""; selectedDate = ""; dateError = ""; refresh(false) }
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
    function saveKey() {
        if (busy || !apiKey.text.trim()) return
        saver.secret = apiKey.text.trim()
        apiKey.text = ""
        saver.running = true
    }
    Component.onCompleted: refresh(false)
    Timer { interval: 60000; running: true; repeat: true; onTriggered: root.refresh(false) }
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
        text: root.report.needs_setup ? "Setup" : root.report.needs_staff ? "—" : root.report.error ? "!" : root.busy && !root.report.updated ? "…" : String(root.report.jobs.length)
        labelVisible: false
        fixedWidth: root.vertical ? -1 : logoRow.implicitWidth + Style.space(17)
        fixedHeight: root.vertical ? logoRow.implicitHeight + Style.space(12) : -1
        Row {
            id: logoRow
            anchors.centerIn: parent
            spacing: Style.space(6)
            Image {
                source: Qt.resolvedUrl("servicem8-icon.png")
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
        tooltipText: "ServiceM8 jobs · " + (root.report.date || "Today") + " · " + (root.report.staff_name || "Choose staff") + "\nClick to view · Right-click to refresh"
        onPressed: function(b) { if (b === Qt.RightButton || b === Qt.MiddleButton) root.refresh(true); else root.toggle() }
    }
    Ui.KeyboardPanel {
        id: panel
        anchorItem: button
        bar: root.bar
        owner: root
        open: root.opened
        contentWidth: panel.fittedContentWidth(Style.space(470))
        contentHeight: panel.fittedContentHeight(Style.space(540))
        focusTarget: content

        FocusScope {
            id: content
            anchors.fill: parent
            Keys.onEscapePressed: { if (root.calendarVisible) root.calendarVisible = false; else root.close() }
            Column {
                id: header
                width: parent.width
                spacing: 8
                Text { text: root.selectedDate ? "My Jobs · " + root.selectedDate : "My Jobs Today"; color: root.ink; font.pixelSize: 23; font.bold: true }
                Text { text: (root.report.staff_name || "Choose staff") + " · " + (root.report.date || "") + " · Brisbane time"; color: root.ink; opacity: 0.7; font.pixelSize: 12 }
                Row {
                    width: parent.width
                    spacing: 8
                    ComboBox {
                        id: staffPicker
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
                    Button {
                        id: defaultButton
                        text: root.report.staff_uuid === root.report.default_staff ? "Default ✓" : "Set default"
                        enabled: !root.busy && !!root.report.staff_uuid && root.report.staff_uuid !== root.report.default_staff
                        onClicked: root.makeDefault()
                    }
                }
                Row {
                    width: parent.width
                    spacing: 6
                    Button { id: previousDay; implicitWidth: 30; text: "‹"; enabled: !root.busy; onClicked: root.stepDate(-1); Accessible.name: "Previous day" }
                    TextField {
                        id: dateField
                        width: parent.width - previousDay.width - goDate.width - nextDay.width - todayButton.width - calendarButton.width - 30
                        placeholderText: "YYYY-MM-DD"
                        selectByMouse: true
                        enabled: !root.busy
                        onAccepted: root.chooseDate(text.trim())
                        Accessible.name: "Job date, YYYY-MM-DD"
                    }
                    Button { id: nextDay; implicitWidth: 30; text: "›"; enabled: !root.busy; onClicked: root.stepDate(1); Accessible.name: "Next day" }
                    Button { id: goDate; implicitWidth: 42; text: "Go"; enabled: !root.busy; onClicked: root.chooseDate(dateField.text.trim()) }
                    Button { id: calendarButton; implicitWidth: previousDay.implicitWidth; implicitHeight: previousDay.implicitHeight; width: previousDay.width; height: previousDay.height; padding: 0; font.pixelSize: Math.round(previousDay.font.pixelSize * 0.8); text: "▦"; enabled: !root.busy; onClicked: root.showCalendar(); Accessible.name: "Choose date from calendar" }
                    Button { id: todayButton; implicitWidth: 62; text: "Today"; enabled: !root.busy; onClicked: root.chooseDate("") }
                }
                Text { visible: root.dateError !== ""; text: root.dateError; color: root.ink; font.pixelSize: 12 }
                Row {
                    spacing: 8
                    Button { text: root.busy ? "Loading…" : "Refresh"; enabled: !root.busy; onClicked: root.refresh(true) }
                    Button { text: "Setup"; onClicked: root.setupVisible = !root.setupVisible }
                    Button { text: "ServiceM8"; onClicked: Qt.openUrlExternally("https://go.servicem8.com/") }
                }
                Text {
                    width: parent.width
                    visible: text !== ""
                    text: root.report.error || (root.report.needs_staff ? "Choose a staff member, then Set default to remember your choice." : root.report.updated ? "Updated " + root.report.updated + " · refreshes every 4 minutes" : "")
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
                        text: "Create a key in ServiceM8 → Settings → API Keys, with read access to staff, schedules, jobs and customers. Paste it below."
                        textFormat: Text.PlainText
                        color: root.ink; wrapMode: Text.Wrap; font.pixelSize: 13
                    }
                    TextField {
                        id: apiKey
                        width: parent.width
                        placeholderText: "ServiceM8 API key"
                        echoMode: TextInput.Password
                        selectByMouse: true
                        onAccepted: root.saveKey()
                    }
                    Button { text: root.busy ? "Connecting…" : "Connect ServiceM8"; enabled: !root.busy && apiKey.text.trim() !== ""; onClicked: root.saveKey() }
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
                    Button { id: prevMonth; implicitWidth: 36; text: "‹"; onClicked: root.moveMonth(-1); Accessible.name: "Previous month" }
                    Text {
                        width: parent.width - prevMonth.width - nextMonth.width
                        height: prevMonth.height
                        text: Qt.formatDate(root.calendarMonth, "MMMM yyyy")
                        color: root.ink
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        font.pixelSize: 16
                    }
                    Button { id: nextMonth; implicitWidth: 36; text: "›"; onClicked: root.moveMonth(1); Accessible.name: "Next month" }
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
                        delegate: Button {
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
                visible: !root.calendarVisible
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
                            width: jobsColumn.width
                            height: details.implicitHeight + 24
                            radius: 8
                            color: Qt.rgba(root.ink.r, root.ink.g, root.ink.b, jobMouse.containsMouse ? 0.12 : 0.06)
                            Column {
                                id: details
                                x: 12; y: 12
                                width: parent.width - 24
                                spacing: 5
                                Text { width: parent.width; text: card.modelData.time + "   ·   " + card.modelData.status; textFormat: Text.PlainText; color: root.ink; font.pixelSize: 12; wrapMode: Text.Wrap }
                                Text { width: parent.width; text: (card.modelData.number ? "#" + card.modelData.number + "  " : "") + card.modelData.customer; textFormat: Text.PlainText; color: root.ink; font.bold: true; font.pixelSize: 16; wrapMode: Text.Wrap }
                                Text { width: parent.width; visible: text !== ""; text: card.modelData.address; textFormat: Text.PlainText; color: root.ink; font.pixelSize: 13; wrapMode: Text.Wrap }
                                Text { width: parent.width; visible: text !== ""; text: card.modelData.description; textFormat: Text.PlainText; color: root.ink; opacity: 0.75; font.pixelSize: 12; wrapMode: Text.Wrap; maximumLineCount: 4; elide: Text.ElideRight }
                            }
                            MouseArea { id: jobMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Qt.openUrlExternally("https://go.servicem8.com/OpenJob/" + encodeURIComponent(card.modelData.uuid)) }
                        }
                    }
                }
            }
        }
    }
}

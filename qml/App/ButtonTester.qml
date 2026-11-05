import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts

Window {
    id: tester
    title: "Button test · clicks / hold"
    width: 460; height: 620
    minimumWidth: 400; minimumHeight: 400
    color: Theme.bg
    property var releases: ({})
    property var records: ({})
    property bool incomplete: false
    property real now: Date.now()
    readonly property bool available: bridge.connected && bridge.modeOk
                                     && (!bridge.hasConfigSession || bridge.configClaimed)
    readonly property bool capturing: visible && active && available
    readonly property string source: bridge.selectedController + ":" + bridge.activeProfile
    onCapturingChanged: {
        releases = ({})
        if (!capturing) {
            var next = Object.assign({}, records)
            for (var key in next) {
                if (next[key].held)
                    next[key] = Object.assign({}, next[key], {held: false, paused: true,
                                              holdMs: Math.max(0, Date.now() - next[key].receivedAt)})
            }
            records = next
        }
        bridge.setButtonCapture(capturing)
    }
    onSourceChanged: reset()
    onAvailableChanged: if (!available) reset()
    Component.onDestruction: bridge.setButtonCapture(false)

    function reset() {
        bridge.setButtonCapture(false)
        releases = ({}); records = ({}); incomplete = false
        if (capturing) bridge.setButtonCapture(true)
    }
    function recordButton(key, down, when) {
        var next = Object.assign({}, records), previous = records[key]
        if (!down) {
            var up = Object.assign({}, releases); up[key] = when; releases = up
            if (previous && previous.held) {
                next[key] = Object.assign({}, previous, {held: false,
                                          holdMs: Math.max(0, when - previous.pressedAt)})
                records = next
            }
            return
        }
        var gap = releases[key] === undefined ? -1 : when - releases[key]
        var rapid = gap >= 0 && gap <= 20
        now = Date.now()
        next[key] = {count: (previous ? previous.count : 0) + 1, gap: gap, rapid: rapid,
                     held: true, pressedAt: when, receivedAt: now, holdMs: 0, paused: false,
                     breaks: (previous ? previous.breaks : 0) + (rapid ? 1 : 0)}
        records = next
    }
    function duration(ms) { return ms < 1000 ? Math.round(ms) + " ms" : (ms / 1000).toFixed(2) + " s" }
    Timer {
        interval: 50; repeat: true
        running: tester.capturing && Object.keys(tester.records).some(function(k) { return tester.records[k].held })
        onTriggered: tester.now = Date.now()
    }
    Connections {
        target: bridge; enabled: tester.capturing
        function onButtonTransition(key, down, when) { tester.recordButton(key, down, when) }
        function onButtonCaptureOverflow() { tester.incomplete = true }
    }

    ColumnLayout {
        anchors.fill: parent; anchors.margins: 20; spacing: 14
        Text {
            Layout.fillWidth: true; wrapMode: Text.WordWrap
            text: "ABXY · D-pad · LB/RB. Each new press adds 1. Hold a button to check its timer and short interruptions."
            color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
        }
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true; wrapMode: Text.WordWrap
                text: tester.incomplete ? "Events lost — reset and repeat."
                      : !tester.available ? "Connect the controller and enable configuration if required."
                      : tester.capturing ? "Recording" : "Paused · focus this window to record."
                color: tester.incomplete ? Theme.warn : Theme.textDim
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
            }
            PillButton { label: "Reset"; onClicked: tester.reset() }
        }
        ListView {
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; spacing: 4; model: Object.keys(tester.records)
            QQC.ScrollBar.vertical: QQC.ScrollBar {}
            delegate: Rectangle {
                id: row
                required property string modelData
                readonly property var stats: tester.records[modelData] || ({count: 0, gap: -1, rapid: false})
                width: ListView.view.width; height: 58; radius: 6
                color: Theme.card
                RowLayout {
                    anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                    anchors.margins: 12; height: 18
                    Text {
                        Layout.fillWidth: true
                        text: modelData.replace("dpad_", "D-pad ").toUpperCase(); color: Theme.text
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                    }
                    Text {
                        Layout.preferredWidth: 40
                        horizontalAlignment: Text.AlignRight
                        text: stats.count; color: Theme.text
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                    }
                    Text {
                        Layout.preferredWidth: 166
                        horizontalAlignment: Text.AlignRight
                        text: stats.rapid ? "Double click · " + Math.round(stats.gap) + " ms" : "OK"
                        color: stats.rapid ? Theme.warn : Theme.ok
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                    }
                }
                Text {
                    anchors.left: parent.left; anchors.leftMargin: 12
                    anchors.bottom: parent.bottom; anchors.bottomMargin: 8
                    text: (row.stats.held ? "Held " + tester.duration(Math.max(0, tester.now - row.stats.receivedAt))
                                         : (row.stats.paused ? "Paused after " : "Released · held ") + tester.duration(row.stats.holdMs || 0))
                          + " · short breaks: " + (row.stats.breaks || 0)
                    color: row.stats.breaks ? Theme.warn : row.stats.held ? Theme.accent : Theme.textDim
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
            }
        }
        Text {
            Layout.fillWidth: true; wrapMode: Text.WordWrap
            text: "A release → press gap up to 20 ms is flagged and counted as a short break. Firmware may hide bounce."
            color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
        }
    }
}

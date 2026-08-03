import QtQuick
import QtQuick.Window
import QtQuick.Controls as QQC
import App 1.0

// Diagnostics — a small separate window (opened from Settings, or from the
// device-access banner). Runs the shared "doctor" engine off-thread and shows
// the report: environment, hidapi backend, udev-rule state, and a per-device
// open ladder (stat → os.open → hidapi → verdict), ending in a plain-language
// verdict + fix. "Copy report" puts the whole thing on the clipboard, formatted
// for pasting straight into a GitHub issue — so users never need a terminal.
Window {
    id: win
    title: "Deadband — Diagnostics"
    width: 720; height: 560
    minimumWidth: 520; minimumHeight: 360
    color: Theme.bg
    property bool copied: false

    onVisibleChanged: if (visible && bridge.diagReport.length === 0) bridge.runDiagnostics()

    Column {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10

        // header row: title + actions
        Item {
            width: parent.width; height: 34
            Text {
                anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                text: "Device diagnostics"
                color: Theme.text; font.family: Theme.fontFamily
                font.pixelSize: Theme.fontL; font.weight: Font.DemiBold
            }
            Row {
                anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                spacing: 8
                PillButton {
                    label: bridge.diagBusy ? "Running…" : "↺ Re-run"
                    enabled: !bridge.diagBusy
                    onClicked: { win.copied = false; bridge.runDiagnostics() }
                }
                PillButton {
                    label: win.copied ? "✓ Copied" : "Copy report"
                    highlight: !win.copied
                    enabled: bridge.diagReport.length > 0
                    onClicked: { bridge.copyText(bridge.diagReport); win.copied = true }
                }
            }
        }
        Text {
            width: parent.width; wrapMode: Text.WordWrap
            text: "Checks whether Deadband can actually open your devices — and if not, "
                + "why. Paste the report into a GitHub issue when asking for help."
            color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
        }

        // the report
        Rectangle {
            width: parent.width
            height: parent.height - y
            radius: Theme.radius
            color: Theme.card; border.color: Theme.cardBorder; border.width: 1

            QQC.ScrollView {
                anchors.fill: parent
                anchors.margins: 12
                clip: true
                contentWidth: availableWidth
                QQC.TextArea {
                    readOnly: true
                    wrapMode: TextEdit.WrapAnywhere
                    text: bridge.diagBusy && bridge.diagReport.length === 0
                          ? "Collecting…" : bridge.diagReport
                    color: Theme.text
                    font.family: "monospace"; font.pixelSize: Theme.fontS
                    background: null
                    selectByMouse: true
                }
            }
        }
    }
}

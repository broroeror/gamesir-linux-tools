import QtQuick
import QtQuick.Layouts
import App 1.0

// Shared "mouse not connected / needs access" panel for the mouse tabs (Buttons,
// DPI). Shown when !mouse.present; the page's real content is hidden behind it.
// One copy so every mouse tab explains connect/permission identically.
ColumnLayout {
    anchors.centerIn: parent
    width: Math.min(parent.width - 60, 460)
    visible: !mouse.present
    spacing: 14

    Text {
        Layout.fillWidth: true
        horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
        font.family: Theme.fontFamily; font.pixelSize: Theme.fontL; color: Theme.text
        text: mouse.permission === "no-access"
                ? "Your G502 X is connected, but Deadband can't access it yet."
                : mouse.permission === "absent"
                ? "Connect your Logitech G502 X to configure it."
                : "Looking for a G502 X…"
    }
    Card {
        visible: mouse.permission === "no-access"
        title: "Grant access (one-time)"
        Layout.fillWidth: true
        Text {
            width: parent.width; wrapMode: Text.WrapAnywhere
            color: Theme.textDim; font.family: "monospace"; font.pixelSize: Theme.fontS
            text: "sudo cp packaging/udev/70-deadband-g502x.rules /etc/udev/rules.d/\n"
                + "sudo udevadm control --reload && sudo udevadm trigger"
        }
        Text {
            width: parent.width; wrapMode: Text.WordWrap; topPadding: 6
            color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
            text: "…then replug the mouse. If ratbagd holds the device, stop it first."
        }
    }
    PillButton { Layout.alignment: Qt.AlignHCenter; label: "Retry"; onClicked: mouse.refresh() }
}

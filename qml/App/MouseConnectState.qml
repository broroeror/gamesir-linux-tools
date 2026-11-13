import QtQuick
import QtQuick.Layouts
import App 1.0

// Shared "mouse not connected / needs access / needs setup" panel for the mouse
// tabs. Shown when !mouse.present, or when the mouse is still on its read-only
// factory profiles; the page's real content is hidden behind it. One copy so
// every mouse tab explains it identically.
ColumnLayout {
    anchors.centerIn: parent
    width: Math.min(parent.width - 60, 460)
    visible: !mouse.present || mouse.needsProfileSetup
    spacing: 14

    // ---- connected, but only factory profiles (#28) ----
    Text {
        visible: mouse.present && mouse.needsProfileSetup
        Layout.fillWidth: true
        horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
        font.family: Theme.fontFamily; font.pixelSize: Theme.fontL; color: Theme.text
        text: qsTranslate("UI", "Your G502 X is still using its factory profiles.")
    }
    Card {
        visible: mouse.present && mouse.needsProfileSetup
        title: qsTranslate("UI", "Set up editable profiles (one-time)")
        Layout.fillWidth: true
        Text {
            width: parent.width; wrapMode: Text.WordWrap
            color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
            text: qsTranslate("UI", "The factory profiles live in read-only memory, so they can't be edited directly. Deadband can copy them into editable slots, the same thing Logitech's own software does the first time it sees the mouse. Your current settings carry over unchanged, and a backup is saved first.")
        }
        PillButton {
            label: mouse.busy ? qsTranslate("UI", "Setting up…") : qsTranslate("UI", "Set up editable profiles")
            enabled: !mouse.busy
            onClicked: mouse.setupProfiles()
        }
    }

    Text {
        visible: !mouse.present
        Layout.fillWidth: true
        horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
        font.family: Theme.fontFamily; font.pixelSize: Theme.fontL; color: Theme.text
        text: mouse.permission === "no-access"
                ? qsTranslate("UI", "Your G502 X is connected, but Deadband can't access it yet.")
                : mouse.permission === "absent"
                ? qsTranslate("UI", "Connect your Logitech G502 X to configure it.")
                : qsTranslate("UI", "Looking for a G502 X…")
    }
    Card {
        visible: mouse.permission === "no-access"
        title: qsTranslate("UI", "Grant access (one-time)")
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
            text: qsTranslate("UI", "…then replug the mouse. If ratbagd holds the device, stop it first.")
        }
    }
    PillButton { visible: !mouse.present
                 Layout.alignment: Qt.AlignHCenter; label: qsTranslate("UI", "Retry"); onClicked: mouse.refresh() }
}

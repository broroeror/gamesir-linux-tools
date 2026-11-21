import QtQuick
import QtQuick.Layouts
import App 1.0

// Tarantula Pro device info and resets.
Item {
    id: page

    Text {
        visible: !t3.present
        anchors.centerIn: parent
        text: qsTranslate("UI", "Tarantula Pro not found. Plug its dongle in (XInput mode).")
        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
    }

    ColumnLayout {
        visible: t3.present
        anchors.top: parent.top; anchors.left: parent.left; anchors.margins: 20
        width: Math.min(parent.width - 40, 640)
        spacing: 14

        Card {
            Layout.fillWidth: true
            title: qsTranslate("UI", "Controller")
            Repeater {
                model: [[qsTranslate("UI", "Model"), "GameSir Tarantula Pro (2.4 GHz dongle 3537:103e)"],
                        [qsTranslate("UI", "Firmware"), t3.firmware],
                        [qsTranslate("UI", "Battery"), t3.battery >= 0 ? t3.battery + "%" : "—"],
                        [qsTranslate("UI", "Address"), t3.mac],
                        [qsTranslate("UI", "Gyro bridge (virtual DualShock 4)"),
                         t3.bridgeRunning ? qsTranslate("UI", "running") : qsTranslate("UI", "stopped")]]
                delegate: Row {
                    required property var modelData
                    spacing: 10
                    Text { width: 230; text: modelData[0]; color: Theme.textDim
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                    Text { text: modelData[1]; color: Theme.text
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                }
            }
            PillButton { label: qsTranslate("UI", "Read again from the controller"); onClicked: t3.refresh() }
        }

        Card {
            Layout.fillWidth: true
            title: qsTranslate("UI", "Restore")
            Text {
                width: parent.width; wrapMode: Text.WordWrap
                text: qsTranslate("UI", "Original colours: Xbox-style A/B/X/Y (green, red, blue, yellow), white buttons in the Switch layout, white HOME, blue bar, Phantom effect.")
                color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
            }
            ConfirmButton {
                label: qsTranslate("UI", "Restore original colours")
                onConfirmed: t3.restoreDefaultColors()
            }
            Rectangle { width: parent.width; height: 1; color: Theme.cardBorder }
            Text {
                width: parent.width; wrapMode: Text.WordWrap
                text: qsTranslate("UI", "Factory defaults: original colours and effect, Xbox layout, every button back to itself (C1/C2 = View, C3/C4 = Menu, T3 = Capture), all macros cleared, controller gyro off, vibration 75 %. A full backup is saved to ~/.local/share/t3pro first. Sticks and triggers are not touched; for those use the controller's own reset (hold View + Menu + M until the logo blinks).")
                color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
            }
            ConfirmButton {
                label: qsTranslate("UI", "Restore factory defaults")
                onConfirmed: t3.factoryReset()
            }
            Text {
                width: parent.width; wrapMode: Text.WordWrap
                text: qsTranslate("UI", "HOME + button shortcuts and the rumble gain belong to the bridge and are kept.")
                color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
            }
        }
    }
}

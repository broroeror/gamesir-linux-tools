import QtQuick
import QtQuick.Layouts
import App 1.0

// Tarantula Pro rumble: the per-grip level stored in the pad (0-100 %, what
// GameSir Connect sets) plus the bridge's software gain on what games ask for.
Item {
    id: page
    function seed() { lSlider.value = t3.vibLeft; rSlider.value = t3.vibRight; gSlider.value = Math.round(t3.rumbleGain * 100) }
    Component.onCompleted: seed()
    onVisibleChanged: if (visible) seed()
    Connections {
        target: t3
        function onPresenceChanged() { page.seed() }
        function onStateChanged() { if (!t3.busy && !lvlTimer.running && !gainTimer.running) page.seed() }
    }

    Timer { id: lvlTimer; interval: 300; onTriggered: t3.setVibration(lSlider.value, rSlider.value) }
    Timer { id: gainTimer; interval: 300; onTriggered: t3.setRumbleGain(gSlider.value / 100) }

    Text {
        visible: !t3.present
        anchors.centerIn: parent
        text: qsTranslate("UI", "Tarantula Pro not found. Plug its dongle in (XInput mode).")
        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
    }

    ColumnLayout {
        visible: t3.present
        anchors.top: parent.top; anchors.left: parent.left; anchors.margins: 20
        width: Math.min(parent.width - 40, 620)
        spacing: 14

        Card {
            Layout.fillWidth: true
            title: qsTranslate("UI", "Motor level (stored in the pad)")
            Row {
                width: parent.width
                Text { text: qsTranslate("UI", "Left grip"); color: Theme.textDim
                       font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                Item { width: parent.width - 140; height: 1 }
                Text { text: lSlider.value + "%"; color: Theme.text
                       font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
            }
            AccentSlider { id: lSlider; width: parent.width; from: 0; to: 100; onMoved: lvlTimer.restart() }
            Row {
                width: parent.width
                Text { text: qsTranslate("UI", "Right grip"); color: Theme.textDim
                       font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                Item { width: parent.width - 140; height: 1 }
                Text { text: rSlider.value + "%"; color: Theme.text
                       font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
            }
            AccentSlider { id: rSlider; width: parent.width; from: 0; to: 100; onMoved: lvlTimer.restart() }
            Text {
                width: parent.width; wrapMode: Text.WordWrap
                text: qsTranslate("UI", "Applies everywhere, also without the bridge.")
                color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
            }
        }

        Card {
            Layout.fillWidth: true
            title: qsTranslate("UI", "Game rumble gain (t3pro-bridge)")
            headerValue: gSlider.value + "%"
            AccentSlider { id: gSlider; width: parent.width; from: 0; to: 200; onMoved: gainTimer.restart() }
            Text {
                width: parent.width; wrapMode: Text.WordWrap
                text: qsTranslate("UI", "100% passes what the game asks for. Above 100% boosts weak rumble (capped at the motor's maximum).")
                color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
            }
            PillButton { label: qsTranslate("UI", "Test rumble"); onClicked: t3.testRumble() }
        }
    }
}

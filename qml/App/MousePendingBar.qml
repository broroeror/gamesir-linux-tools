import QtQuick
import App 1.0

// Shared staged-changes bar for the mouse tabs. Reads the bridge's unified
// pendingList (buttons + G-Shift + sensor), so every queued edit — no matter which
// tab staged it — shows here with a removable chip, and one "Apply" writes them all
// in a single gated, read-back-verified write. Parent anchors it (bottom); it sizes
// its own height to the chip flow.
Rectangle {
    id: pbar
    visible: mouse.present && mouse.pendingCount > 0
    height: Math.max(52, chips.implicitHeight + 20); radius: Theme.radius
    color: Theme.card; border.color: Theme.accent; border.width: 1

    Row {
        id: actions
        anchors.right: parent.right; anchors.rightMargin: 14
        anchors.verticalCenter: parent.verticalCenter; spacing: 8
        PillButton { label: "Discard"; enabled: !mouse.busy; onClicked: mouse.discard() }
        PillButton {
            label: mouse.busy ? "Applying…" : "Apply " + mouse.pendingCount
            highlight: !mouse.busy; enabled: !mouse.busy
            onClicked: mouse.apply()
        }
    }
    // one chip per queued change (✕ removes just that one)
    Flow {
        id: chips
        anchors.left: parent.left; anchors.leftMargin: 14
        anchors.right: actions.left; anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        spacing: 6
        Repeater {
            model: mouse.pendingList
            delegate: Rectangle {
                required property var modelData
                height: 26; radius: 6; implicitWidth: chipRow.implicitWidth + 16
                color: Theme.button; border.color: Theme.accent; border.width: 1
                Row {
                    id: chipRow; anchors.centerIn: parent; spacing: 6
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: (modelData.group === "gshift" ? "G· " : "")
                              + modelData.name + "  →  " + modelData.label
                        color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "✕"; color: Theme.textDim; font.pixelSize: Theme.fontS
                        TapHandler { enabled: !mouse.busy; onTapped: mouse.unstageItem(modelData.key) }
                    }
                }
            }
        }
    }
}

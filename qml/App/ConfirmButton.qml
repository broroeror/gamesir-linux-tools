import QtQuick

// A button that requires a second click to fire — for destructive actions.
// First click arms it (swaps to Confirm / Cancel); Confirm emits confirmed().
Item {
    id: cb
    property string label: ""
    property string confirmLabel: "Confirm"
    property bool arming: false
    signal confirmed()

    implicitHeight: 30
    implicitWidth: arming ? armRow.implicitWidth : idle.implicitWidth

    PillButton {
        id: idle
        visible: !cb.arming
        anchors.fill: parent
        label: cb.label
        onClicked: cb.arming = true
    }
    Row {
        id: armRow
        visible: cb.arming
        anchors.fill: parent
        spacing: 8
        PillButton {
            label: cb.confirmLabel; highlight: true
            onClicked: { cb.arming = false; cb.confirmed() }
        }
        PillButton {
            label: "Cancel"
            onClicked: cb.arming = false
        }
    }
}

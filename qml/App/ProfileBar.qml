import QtQuick

// Dynamic profile selector. G7 Pro highlights the bank being edited and marks
// the independently-reported active hardware profile with a small dot.
Row {
    id: root
    // Compact mode shrinks the pills ("P1".."P4") so the top bar fits at narrow
    // window widths; full "Profile N" labels are shown when there's room.
    property bool compact: false
    spacing: compact ? 5 : 8
    Repeater {
        model: bridge.profileCount
        delegate: Rectangle {
            required property int index
            property int n: index + 1
            property bool active: bridge.profile === n
            width: root.compact ? 40 : 92; height: 32; radius: 8
            color: active ? Theme.accent
                          : (hov.hovered ? Theme.cardHover : Theme.card)
            border.color: active ? Qt.lighter(Theme.accent, 1.2) : Theme.cardBorder
            border.width: 1
            Behavior on color { ColorAnimation { duration: 120 } }
            Text {
                anchors.centerIn: parent
                text: root.compact ? ("P" + parent.n) : ("Profile " + parent.n)
                color: parent.active ? "white" : Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontM
                font.weight: parent.active ? Font.DemiBold : Font.Normal
            }
            Rectangle {
                visible: bridge.isG7Pro && bridge.activeProfile === parent.n
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom; anchors.bottomMargin: 2
                width: 5; height: 5; radius: 3
                color: parent.active ? "white" : Theme.ok
            }
            HoverHandler { id: hov }
            TapHandler { onTapped: bridge.setProfile(parent.n) }
        }
    }
}

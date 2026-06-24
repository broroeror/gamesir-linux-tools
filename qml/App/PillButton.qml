import QtQuick

// Small pill button used across the config pages.
Rectangle {
    id: b
    property string label: ""
    property bool highlight: false
    signal clicked()
    implicitWidth: t.implicitWidth + 22; implicitHeight: 30; radius: 7
    color: highlight ? Theme.accent : (hh.hovered ? Theme.cardHover : "#20232B")
    border.color: highlight ? Qt.lighter(Theme.accent, 1.2) : Theme.cardBorder
    border.width: 1
    Behavior on color { ColorAnimation { duration: 100 } }
    Text {
        id: t; anchors.centerIn: parent; text: b.label
        color: b.highlight ? "white" : Theme.text
        font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
    }
    HoverHandler { id: hh }
    TapHandler { onTapped: b.clicked() }
}

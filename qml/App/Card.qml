import QtQuick

// A titled panel. Use `title` for the small header row (with optional icon glyph
// via `headerColor`), then put content in `default` children which flow into the
// inner column.
Rectangle {
    id: root
    property string title: ""
    property string headerValue: ""      // optional right-aligned value in the header
    property alias content: body.data
    // vertical padding/spacing compress with Theme.vComp (driven by FitScroll) so a
    // tall page packs more rows before scrolling; horizontal padding stays `pad`,
    // and fonts/controls are untouched. At vComp = 1 these equal today's values.
    readonly property int _padV: Math.max(4, Math.round(Theme.padV * Theme.vComp))
    readonly property int _gapV: Math.max(3, Math.round(Theme.gapV * Theme.vComp))
    property int spacing: _gapV
    default property alias _children: body.data

    color: Theme.card
    border.color: Theme.cardBorder
    border.width: 1
    radius: Theme.radius
    implicitHeight: layout.implicitHeight + _padV * 2

    Column {
        id: layout
        anchors.fill: parent
        anchors.leftMargin: Theme.pad; anchors.rightMargin: Theme.pad
        anchors.topMargin: root._padV; anchors.bottomMargin: root._padV
        spacing: root._gapV

        Item {
            visible: root.title.length > 0
            width: parent.width; height: titleRow.height
            Row {
                id: titleRow
                spacing: 8
                anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                Rectangle {            // small accent tick before the title
                    width: 4; height: 14; radius: 2
                    anchors.verticalCenter: parent.verticalCenter
                    color: Theme.accent
                }
                Text {
                    text: root.title
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontL
                    font.weight: Font.DemiBold
                }
            }
            Text {                     // optional value on the right of the header
                visible: root.headerValue.length > 0
                text: root.headerValue
                anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                color: Theme.textDim
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
            }
        }

        Column {
            id: body
            width: parent.width
            spacing: root.spacing
        }
    }
}

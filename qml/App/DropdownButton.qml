import QtQuick
import QtQuick.Controls as QQC
import App 1.0

// A compact labelled dropdown: "Label  Value ▾". Deliberately the same visual
// language as ControllerPicker — 32px card-coloured button, 8px radius, ▾/▴
// caret, a card Popup with 32px rows and the accent fill on the selected row —
// so the two dropdowns in the top bars read as one family.
Item {
    id: root
    property string label: ""
    property var model: []               // list of display strings
    property string placeholderText: "—"
    property int currentIndex: 0
    signal activated(int index)

    implicitWidth: btn.width
    implicitHeight: btn.height

    Rectangle {
        id: btn
        width: row.implicitWidth + 36
        height: 32; radius: 8
        color: (hov.hovered || menu.opened) ? Theme.cardHover : Theme.card
        border.color: Theme.cardBorder; border.width: 1
        Behavior on color { ColorAnimation { duration: 120 } }
        Row {
            id: row
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left; anchors.leftMargin: 12
            spacing: 6
            Text {
                text: root.label
                color: Theme.textDim
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
            }
            Text {
                text: (root.currentIndex >= 0 && root.currentIndex < root.model.length)
                      ? qsTranslate("UI", root.model[root.currentIndex]) : root.placeholderText
                color: Theme.text
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                font.weight: Font.DemiBold
            }
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right; anchors.rightMargin: 10
            text: menu.opened ? "▴" : "▾"; color: Theme.textDim; font.pixelSize: 12
        }
        HoverHandler { id: hov }
        TapHandler { onTapped: menu.opened ? menu.close() : menu.open() }
    }

    QQC.Popup {
        id: menu
        y: btn.height + 4
        width: Math.max(btn.width, 140)
        padding: 4
        closePolicy: QQC.Popup.CloseOnPressOutsideParent | QQC.Popup.CloseOnEscape
        background: Rectangle {
            color: Theme.card; radius: 8
            border.color: Theme.cardBorder; border.width: 1
        }
        contentItem: Column {
            spacing: 0
            Repeater {
                model: root.model
                delegate: Rectangle {
                    required property string modelData
                    required property int index
                    readonly property bool sel: index === root.currentIndex
                    width: menu.availableWidth
                    height: 32; radius: 6
                    color: sel ? Theme.accent : (ihov.hovered ? Theme.cardHover : "transparent")
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.left: parent.left; anchors.leftMargin: 10
                        text: qsTranslate("UI", modelData)
                        color: parent.sel ? Theme.textOnAccent : Theme.text
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                        font.weight: parent.sel ? Font.DemiBold : Font.Normal
                    }
                    HoverHandler { id: ihov }
                    TapHandler {
                        onTapped: {
                            menu.close()
                            if (index !== root.currentIndex) root.activated(index)
                        }
                    }
                }
            }
        }
    }
}

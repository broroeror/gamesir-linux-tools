import QtQuick
import QtQuick.Controls as QQC
import App 1.0

// A labelled color swatch that opens a ColorPicker in a popup. Used by
// Settings → Appearance to edit each theme token. Emits picked(color) live
// while the user drags, so the whole app re-themes in real time.
//
// Contract: bind `value` to your source of truth and update that source in
// onPicked — the field is display-only for `value` (it never writes it), so a
// preset/reset that changes the source flows straight back into the swatch.
Item {
    id: field
    property string label: ""
    property color value: "#000000"
    signal picked(color c)

    implicitWidth: 150
    implicitHeight: 34

    Row {
        anchors.fill: parent
        spacing: 8

        Rectangle {
            id: swatch
            width: 34; height: 34; radius: 7
            anchors.verticalCenter: parent.verticalCenter
            color: field.value
            border.color: pop.opened ? Theme.accent : Theme.cardBorder
            border.width: pop.opened ? 2 : 1
            HoverHandler { id: sh }
            TapHandler { onTapped: pop.opened ? pop.close() : pop.open() }
            // subtle hover ring
            Rectangle {
                anchors.fill: parent; radius: parent.radius
                color: "transparent"; visible: sh.hovered && !pop.opened
                border.color: Theme.textDim; border.width: 1
            }
        }

        Column {
            anchors.verticalCenter: parent.verticalCenter
            spacing: 1
            Text {
                text: field.label; color: Theme.text
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
            }
            Text {
                text: field.value.toString().toUpperCase()
                color: Theme.textDim
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontS - 1
            }
        }
    }

    QQC.Popup {
        id: pop
        y: swatch.height + 6
        width: 236; padding: 12
        closePolicy: QQC.Popup.CloseOnPressOutsideParent | QQC.Popup.CloseOnEscape
        onAboutToShow: picker.setColor(field.value)
        background: Rectangle {
            color: Theme.card; radius: Theme.radius
            border.color: Theme.cardBorder; border.width: 1
        }
        contentItem: Column {
            spacing: 10
            ColorPicker {
                id: picker
                width: parent.width
                onEdited: function (c) { field.picked(c) }
            }
            Row {
                spacing: 8
                Rectangle {
                    width: 26; height: 26; radius: 6; color: field.value
                    border.color: Theme.cardBorder; border.width: 1
                }
                // hex entry for precise / paste input
                Rectangle {
                    width: 150; height: 26; radius: 6
                    color: Theme.bg; border.color: hexIn.activeFocus ? Theme.accent : Theme.cardBorder
                    border.width: 1
                    TextInput {
                        id: hexIn
                        anchors.fill: parent; anchors.leftMargin: 8
                        verticalAlignment: TextInput.AlignVCenter
                        color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        text: field.value.toString().toUpperCase()
                        selectByMouse: true
                        // accept #RGB / #RRGGBB (with or without leading #)
                        validator: RegularExpressionValidator { regularExpression: /#?[0-9a-fA-F]{0,8}/ }
                        onEditingFinished: {
                            var t = text.trim()
                            if (t.length && t[0] !== "#") t = "#" + t
                            if (/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(t)) {
                                field.picked(t); picker.setColor(t)
                            } else {
                                text = field.value.toString().toUpperCase()   // revert
                            }
                        }
                    }
                }
            }
        }
    }
}

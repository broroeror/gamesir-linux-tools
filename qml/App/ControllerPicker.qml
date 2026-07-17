import QtQuick
import QtQuick.Controls as QQC
import App 1.0

// Top-bar selector for WHICH connected controller the app drives. Lists
// bridge.controllers and switches via bridge.selectController(id). Shows the
// current controller's name always; the dropdown is only interactive when more
// than one controller is connected (identical models are labelled by USB port).
//
// The dropdown is a QQC.Popup so it renders in the window's overlay and receives
// taps correctly — a plain child Rectangle overflows the 58px top bar's bounds
// and, though it renders, never gets the tap (input hit-testing is bounded by the
// ancestor, so the click falls through to the content panel below).
Item {
    id: root
    property var list: bridge.controllers
    property string current: bridge.selectedController
    property bool multi: list.length > 1
    // {usb port id: friendly name} — user-assigned, owned/persisted by Main.
    property var names: ({})

    // A user name wins over the model label. Names are keyed by USB PORT (identical
    // units are indistinguishable over USB — see Main's ctrlNames note), so this is
    // "what's plugged into that socket", not "which unit".
    function displayFor(e) {
        if (!e) return ""
        var n = names[e.id]
        return (n && n.length) ? n : e.label
    }

    visible: list.length > 0
    implicitWidth: btn.width
    implicitHeight: btn.height
    onMultiChanged: if (!multi) menu.close()

    function entryFor(id) {
        for (var i = 0; i < list.length; i++)
            if (list[i].id === id) return list[i]
        return list.length > 0 ? list[0] : null
    }
    function labelFor(id) { return root.displayFor(root.entryFor(id)) }

    Rectangle {
        id: btn
        // cap the width so a long controller name elides instead of pushing the
        // rest of the top bar (settings gear) off-screen at narrow widths.
        readonly property int pad: root.multi ? 62 : 38
        width: Math.min(210, Math.max(120, txt.implicitWidth + pad))
        height: 32; radius: 8
        color: (hov.hovered || menu.opened) ? Theme.cardHover : Theme.card
        border.color: Theme.cardBorder; border.width: 1
        Behavior on color { ColorAnimation { duration: 120 } }
        Row {
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left; anchors.leftMargin: 12
            spacing: 8
            // wired/wireless at a glance, in place of the old plain dot
            ConnIcon {
                anchors.verticalCenter: parent.verticalCenter
                property var cur: root.entryFor(root.current)
                wired: cur ? cur.wired : null
                live: cur ? cur.live : true
                tint: (cur && !cur.live) ? Theme.warn : Theme.accent
            }
            Text {
                id: txt
                text: root.labelFor(root.current)
                color: Theme.text
                width: Math.min(implicitWidth, btn.width - btn.pad)
                elide: Text.ElideRight
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
            }
        }
        Text {
            visible: root.multi
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right; anchors.rightMargin: 10
            text: menu.opened ? "▴" : "▾"; color: Theme.textDim; font.pixelSize: 12
        }
        HoverHandler { id: hov }
        TapHandler { enabled: root.multi; onTapped: menu.opened ? menu.close() : menu.open() }
    }

    // Dropdown list — a Popup so it overlays the content below the bar and gets taps.
    QQC.Popup {
        id: menu
        y: btn.height + 4
        width: Math.max(btn.width, 220)
        padding: 4
        closePolicy: QQC.Popup.CloseOnPressOutsideParent | QQC.Popup.CloseOnEscape
        background: Rectangle {
            color: Theme.card; radius: 8
            border.color: Theme.cardBorder; border.width: 1
        }
        contentItem: Column {
            spacing: 0
            Repeater {
                model: root.list
                delegate: Rectangle {
                    required property var modelData
                    width: menu.availableWidth
                    height: 32; radius: 6
                    property bool sel: modelData.id === root.current
                    color: sel ? Theme.accent
                                : (ihov.hovered ? Theme.cardHover : "transparent")
                    Row {
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.left: parent.left; anchors.leftMargin: 10
                        anchors.right: parent.right; anchors.rightMargin: 10
                        spacing: 8
                        ConnIcon {
                            anchors.verticalCenter: parent.verticalCenter
                            wired: modelData.wired
                            live: modelData.live
                            tint: parent.parent.sel ? "white"
                                                    : (modelData.live ? Theme.text : Theme.warn)
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: root.displayFor(modelData)
                            // an empty dongle isn't a controller — de-emphasise it
                            opacity: modelData.live ? 1 : 0.6
                            color: parent.parent.sel ? "white" : Theme.text
                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                        }
                        // Only annotate the exceptional case; "Connected" on every
                        // row would just be noise.
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: !modelData.live
                            text: "— " + modelData.status
                            color: parent.parent.sel ? "white" : Theme.warn
                            opacity: parent.parent.sel ? 0.9 : 1
                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        }
                    }
                    HoverHandler { id: ihov }
                    TapHandler {
                        onTapped: { bridge.selectController(modelData.id); menu.close() }
                    }
                }
            }
        }
    }
}

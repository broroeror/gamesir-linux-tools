import QtQuick
import QtQuick.Controls as QQC
import App 1.0

// Top-bar selector for WHICH device the app drives: any connected controller
// (bridge.controllers) and — when present — the Logitech G502 X mouse. Emits
// pickController(id) / pickMouse() so the parent (Main) owns the active-device
// state and the controller switch; this component only presents the choices.
//
// The dropdown is a QQC.Popup so it renders in the window overlay and receives
// taps correctly (a plain child would overflow the 58px bar and never get the tap).
Item {
    id: root
    property var list: bridge.controllers
    property string current: bridge.selectedController
    // {usb port id: friendly name} — user-assigned, owned/persisted by Main.
    property var names: ({})

    // Mouse device (driven by MouseBridge via Main).
    property bool mousePresent: false
    property bool mouseActive: false
    property string mouseName: "G502 X"

    signal pickController(string id)
    signal pickMouse()

    readonly property bool multi: list.length > 1
    readonly property bool canPick: multi || mousePresent   // dropdown worth opening?

    // A user name wins over the model label. Names are keyed by USB PORT (identical
    // units are indistinguishable over USB — see Main's ctrlNames note).
    function displayFor(e) {
        if (!e) return ""
        var n = names[e.id]
        return (n && n.length) ? n : e.label
    }

    visible: list.length > 0 || mousePresent
    implicitWidth: btn.width
    implicitHeight: btn.height
    onCanPickChanged: if (!canPick) menu.close()

    function entryFor(id) {
        for (var i = 0; i < list.length; i++)
            if (list[i].id === id) return list[i]
        return list.length > 0 ? list[0] : null
    }
    function labelFor(id) { return root.displayFor(root.entryFor(id)) }

    Rectangle {
        id: btn
        readonly property int pad: root.canPick ? 62 : 38
        width: Math.min(210, Math.max(120, txt.implicitWidth + pad))
        height: 32; radius: 8
        color: (hov.hovered || menu.opened) ? Theme.cardHover : Theme.card
        border.color: Theme.cardBorder; border.width: 1
        Behavior on color { ColorAnimation { duration: 120 } }
        Row {
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left; anchors.leftMargin: 12
            spacing: 8
            // mouse glyph when the mouse is the active device, else the controller's
            // wired/wireless indicator
            Text {
                visible: root.mouseActive
                anchors.verticalCenter: parent.verticalCenter
                text: "🖱"; font.pixelSize: 14; color: Theme.accent
            }
            ConnIcon {
                visible: !root.mouseActive
                anchors.verticalCenter: parent.verticalCenter
                property var cur: root.entryFor(root.current)
                wired: cur ? cur.wired : null
                live: cur ? cur.live : true
                tint: (cur && !cur.live) ? Theme.warn : Theme.accent
            }
            Text {
                id: txt
                text: root.mouseActive ? root.mouseName : root.labelFor(root.current)
                color: Theme.text
                width: Math.min(implicitWidth, btn.width - btn.pad)
                elide: Text.ElideRight
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
            }
        }
        Text {
            visible: root.canPick
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right; anchors.rightMargin: 10
            text: menu.opened ? "▴" : "▾"; color: Theme.textDim; font.pixelSize: 12
        }
        HoverHandler { id: hov }
        TapHandler { enabled: root.canPick; onTapped: menu.opened ? menu.close() : menu.open() }
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
                    property bool sel: !root.mouseActive && modelData.id === root.current
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
                            opacity: modelData.live ? 1 : 0.6
                            color: parent.parent.sel ? "white" : Theme.text
                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                        }
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
                        onTapped: { root.pickController(modelData.id); menu.close() }
                    }
                }
            }
            // Mouse row — only when a G502 X is present.
            Rectangle {
                visible: root.mousePresent
                width: menu.availableWidth
                height: 32; radius: 6
                property bool sel: root.mouseActive
                color: sel ? Theme.accent : (mhov.hovered ? Theme.cardHover : "transparent")
                Row {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left; anchors.leftMargin: 10
                    spacing: 8
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "🖱"; font.pixelSize: 14
                        color: parent.parent.sel ? "white" : Theme.accent
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.mouseName
                        color: parent.parent.sel ? "white" : Theme.text
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                    }
                }
                HoverHandler { id: mhov }
                TapHandler { onTapped: { root.pickMouse(); menu.close() } }
            }
        }
    }
}

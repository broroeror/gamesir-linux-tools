import QtQuick
import App 1.0

// Modal target picker: a dimmed overlay with a centered panel. `mode` chooses the
// layout — "buttons" (gamepad grid), "keyboard" (real keyboard shape), or "mouse"
// (a generic mouse diagram). Emits picked(code) and closes. Reusable by macros
// and paddle remaps. Parent it to a full-page Item so it covers everything.
Item {
    id: tp
    anchors.fill: parent
    z: 1000
    property string mode: ""          // "" = hidden
    property int current: -1          // currently-assigned code (highlighted)
    signal picked(int code)

    visible: mode !== ""

    function choose(code) { tp.picked(code); tp.mode = "" }
    function keyLabel(n) {
        switch (n) {
        case "Backspace": return "⌫"; case "Enter": return "↵"
        case "LShift": case "RShift": return "Shift"
        case "LCtrl": case "RCtrl": return "Ctrl"
        case "LAlt": case "RAlt": return "Alt"
        case "Caps": return "Caps"; case "Space": return "Space"
        default: return n
        }
    }

    // dim backdrop; click outside closes
    Rectangle {
        anchors.fill: parent; color: "#B3000000"
        MouseArea { anchors.fill: parent; onClicked: tp.mode = "" }
    }

    // ---------------- panel ----------------
    Rectangle {
        anchors.centerIn: parent
        color: Theme.card; border.color: Theme.cardBorder; border.width: 1
        radius: Theme.radius
        width: content.width + 40
        height: content.height + 52
        MouseArea { anchors.fill: parent }           // swallow clicks (don't close)

        Row {
            id: header
            anchors.top: parent.top; anchors.topMargin: 12
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 6
            Repeater {
                model: [{ m: "buttons", t: "Buttons" }, { m: "keyboard", t: "Keyboard" },
                        { m: "numpad", t: "Numpad" }, { m: "mouse", t: "Mouse" }]
                delegate: PillButton {
                    required property var modelData
                    label: modelData.t
                    highlight: tp.mode === modelData.m
                    onClicked: tp.mode = modelData.m
                }
            }
        }
        Text {
            anchors.top: parent.top; anchors.topMargin: 12
            anchors.right: parent.right; anchors.rightMargin: 14
            text: "✕"; color: Theme.textDim; font.pixelSize: Theme.fontM
            TapHandler { onTapped: tp.mode = "" }
        }

        Item {
            id: content
            anchors.top: header.bottom; anchors.topMargin: 14
            anchors.horizontalCenter: parent.horizontalCenter
            width: 520; height: childrenRect.height

            // ============ buttons ============
            Flow {
                visible: tp.mode === "buttons"
                anchors.horizontalCenter: parent.horizontalCenter
                width: 360; spacing: 6
                Repeater {
                    model: tp.mode === "buttons" ? bridge.buttonTargets : []
                    delegate: PillButton {
                        required property var modelData
                        label: modelData.name
                        highlight: tp.current === modelData.code
                        onClicked: tp.choose(modelData.code)
                    }
                }
            }

            // ============ keyboard ============
            property real ku: 30                        // key unit (px)
            property real kg: 4                         // key gap
            Column {
                visible: tp.mode === "keyboard"
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: content.kg
                Repeater {
                    model: tp.mode === "keyboard" ? bridge.keyboardRows : []
                    delegate: Row {
                        required property var modelData
                        spacing: content.kg
                        Repeater {
                            model: modelData
                            delegate: Rectangle {
                                required property var modelData
                                width: modelData.w * content.ku + (modelData.w - 1) * content.kg
                                height: content.ku; radius: 4
                                property bool sel: tp.current === modelData.code
                                color: sel ? Theme.accent : (kh.hovered ? Theme.cardHover : Theme.bg)
                                border.color: sel ? Theme.accent : Theme.cardBorder; border.width: 1
                                Text {
                                    anchors.centerIn: parent
                                    text: tp.keyLabel(modelData.name)
                                    color: sel ? "white" : Theme.text
                                    font.family: Theme.fontFamily
                                    font.pixelSize: modelData.name.length > 2 ? Theme.fontS : Theme.fontM
                                }
                                HoverHandler { id: kh }
                                TapHandler { onTapped: tp.choose(modelData.code) }
                            }
                        }
                    }
                }
            }

            // ============ numpad (media / nav / volume / arrows / numpad) ============
            Column {
                visible: tp.mode === "numpad"
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: content.kg
                Repeater {
                    model: tp.mode === "numpad" ? bridge.numpadRows : []
                    delegate: Row {
                        required property var modelData
                        spacing: content.kg
                        Repeater {
                            model: modelData
                            delegate: Rectangle {
                                required property var modelData
                                width: modelData.w * content.ku + (modelData.w - 1) * content.kg
                                height: content.ku; radius: 4
                                property bool sel: tp.current === modelData.code
                                color: sel ? Theme.accent : (nh.hovered ? Theme.cardHover : Theme.bg)
                                border.color: sel ? Theme.accent : Theme.cardBorder; border.width: 1
                                Text {
                                    anchors.centerIn: parent
                                    text: modelData.name
                                    color: sel ? "white" : Theme.text
                                    font.family: Theme.fontFamily
                                    font.pixelSize: modelData.name.length > 3 ? Theme.fontS : Theme.fontM
                                }
                                HoverHandler { id: nh }
                                TapHandler { onTapped: tp.choose(modelData.code) }
                            }
                        }
                    }
                }
            }

            // ============ mouse ============
            Item {
                visible: tp.mode === "mouse"
                anchors.horizontalCenter: parent.horizontalCenter
                width: 200; height: 240
                property int hov: -1
                function fill(code) { return tp.current === code ? Theme.accent
                                           : (mouseItem.hov === code ? Theme.cardHover : Theme.bg) }
                id: mouseItem
                // body
                Rectangle {
                    anchors.fill: parent; anchors.margins: 30
                    radius: width / 2; color: Theme.bg
                    border.color: Theme.cardBorder; border.width: 1
                }
                // left / right click halves (top)
                Rectangle {
                    x: 30; y: 30; width: parent.width / 2 - 30; height: 90
                    topLeftRadius: (parent.width - 60) / 2
                    color: mouseItem.fill(0xc8)
                    border.color: Theme.cardBorder; border.width: 1
                    Text { anchors.centerIn: parent; text: "L"; color: Theme.text
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                    HoverHandler { onHoveredChanged: mouseItem.hov = hovered ? 0xc8 : -1 }
                    TapHandler { onTapped: tp.choose(0xc8) }
                }
                Rectangle {
                    x: parent.width / 2; y: 30; width: parent.width / 2 - 30; height: 90
                    topRightRadius: (parent.width - 60) / 2
                    color: mouseItem.fill(0xca)
                    border.color: Theme.cardBorder; border.width: 1
                    Text { anchors.centerIn: parent; text: "R"; color: Theme.text
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                    HoverHandler { onHoveredChanged: mouseItem.hov = hovered ? 0xca : -1 }
                    TapHandler { onTapped: tp.choose(0xca) }
                }
                // wheel = middle + scroll up/down
                Column {
                    anchors.horizontalCenter: parent.horizontalCenter; y: 34; spacing: 2
                    Rectangle {
                        width: 26; height: 20; radius: 6; color: mouseItem.fill(0xcd)
                        border.color: Theme.cardBorder; border.width: 1
                        Text { anchors.centerIn: parent; text: "▲"; color: Theme.textDim; font.pixelSize: 10 }
                        HoverHandler { onHoveredChanged: mouseItem.hov = hovered ? 0xcd : -1 }
                        TapHandler { onTapped: tp.choose(0xcd) }
                    }
                    Rectangle {
                        width: 26; height: 24; radius: 6; color: mouseItem.fill(0xc9)
                        border.color: Theme.cardBorder; border.width: 1
                        Text { anchors.centerIn: parent; text: "M"; color: Theme.text; font.pixelSize: 10 }
                        HoverHandler { onHoveredChanged: mouseItem.hov = hovered ? 0xc9 : -1 }
                        TapHandler { onTapped: tp.choose(0xc9) }
                    }
                    Rectangle {
                        width: 26; height: 20; radius: 6; color: mouseItem.fill(0xce)
                        border.color: Theme.cardBorder; border.width: 1
                        Text { anchors.centerIn: parent; text: "▼"; color: Theme.textDim; font.pixelSize: 10 }
                        HoverHandler { onHoveredChanged: mouseItem.hov = hovered ? 0xce : -1 }
                        TapHandler { onTapped: tp.choose(0xce) }
                    }
                }
                // side buttons (Mouse 4 / 5)
                Rectangle {
                    x: 8; y: 70; width: 24; height: 26; radius: 5; color: mouseItem.fill(0xcb)
                    border.color: Theme.cardBorder; border.width: 1
                    Text { anchors.centerIn: parent; text: "4"; color: Theme.text; font.pixelSize: Theme.fontS }
                    HoverHandler { onHoveredChanged: mouseItem.hov = hovered ? 0xcb : -1 }
                    TapHandler { onTapped: tp.choose(0xcb) }
                }
                Rectangle {
                    x: 8; y: 100; width: 24; height: 26; radius: 5; color: mouseItem.fill(0xcc)
                    border.color: Theme.cardBorder; border.width: 1
                    Text { anchors.centerIn: parent; text: "5"; color: Theme.text; font.pixelSize: Theme.fontS }
                    HoverHandler { onHoveredChanged: mouseItem.hov = hovered ? 0xcc : -1 }
                    TapHandler { onTapped: tp.choose(0xcc) }
                }
            }
        }
    }
}

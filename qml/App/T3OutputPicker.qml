import QtQuick
import QtQuick.Layouts
import App 1.0

// What a Tarantula Pro button (remap) or macro step sends: pad buttons (up to
// 4 together), keyboard keys (modifiers + up to 3 keys), mouse buttons/wheel,
// or media keys. Multi-select; emits edited(kind, names) on every change.
Column {
    id: root
    property string kind: "pad"
    property var names: []
    property int maxPad: 4
    signal edited(string kind, var names)
    spacing: 6

    readonly property var kinds: [["pad", qsTranslate("UI", "Controller")], ["kb", qsTranslate("UI", "Keyboard")],
                                  ["mouse", qsTranslate("UI", "Mouse")], ["media", qsTranslate("UI", "Media")]]
    readonly property var options: kind === "kb" ? t3.kbKeys
                                 : kind === "mouse" ? t3.mouseOutputs
                                 : kind === "media" ? t3.mediaKeys : t3.padTargets
    readonly property var labels: ({
        "LCTRL": "Ctrl", "LSHIFT": "Shift", "LALT": "Alt", "LWIN": "Win", "RCTRL": "Ctrl Dir.",
        "RSHIFT": "Shift Dir.", "RALT": "AltGr", "RWIN": "Win Dir.",
        "LEFT_m": qsTranslate("UI", "Left click"), "RIGHT_m": qsTranslate("UI", "Right click"),
        "MIDDLE": qsTranslate("UI", "Middle click"), "BACK": qsTranslate("UI", "Back"),
        "FORWARD": qsTranslate("UI", "Forward"), "WHEEL_UP": qsTranslate("UI", "Wheel up"),
        "WHEEL_DOWN": qsTranslate("UI", "Wheel down"), "MUTE": qsTranslate("UI", "Mute"),
        "VOLDOWN": qsTranslate("UI", "Volume −"), "VOLUP": qsTranslate("UI", "Volume +"),
        "MICMUTE": qsTranslate("UI", "Mic mute"), "PLAY": qsTranslate("UI", "Play/Pause"),
        "PREV": qsTranslate("UI", "Previous"), "STOP": qsTranslate("UI", "Stop"), "NEXT": qsTranslate("UI", "Next"),
        "VIEW": "View", "MENU": "Menu", "CAMERA": qsTranslate("UI", "Capture"),
        "UP": "D-pad ▲", "DOWN": "D-pad ▼", "LEFT": "D-pad ◀", "RIGHT": "D-pad ▶"
    })
    function label(n) {
        if (kind === "mouse" && (n === "LEFT" || n === "RIGHT")) return labels[n + "_m"]
        if (kind === "kb") return isMod(n) ? labels[n] : n
        return labels[n] !== undefined ? labels[n] : n
    }
    function isMod(n) { return ["LCTRL","LSHIFT","LALT","LWIN","RCTRL","RSHIFT","RALT","RWIN"].indexOf(n) >= 0 }
    function toggle(n) {
        var s = names.slice(); var at = s.indexOf(n)
        if (at >= 0) s.splice(at, 1)
        else {
            if (kind === "pad" && s.length >= maxPad) s.shift()
            if (kind === "kb" && !isMod(n)) {
                var keys = s.filter(function (x) { return !isMod(x) })
                if (keys.length >= 3) s.splice(s.indexOf(keys[0]), 1)
            }
            s.push(n)
        }
        names = s
        edited(kind, names)
    }

    Row {
        spacing: 6
        Repeater {
            model: root.kinds
            delegate: PillButton {
                required property var modelData
                label: modelData[1]
                highlight: root.kind === modelData[0]
                onClicked: { root.kind = modelData[0]; root.names = []; root.edited(root.kind, root.names) }
            }
        }
    }
    Text {
        width: root.width; wrapMode: Text.WordWrap
        text: root.kind === "pad" ? qsTranslate("UI", "Pick up to %1 buttons pressed together.").arg(root.maxPad)
            : root.kind === "kb" ? qsTranslate("UI", "Pick modifiers (Ctrl, Shift, Alt, Win) plus up to 3 keys.")
            : root.kind === "mouse" ? qsTranslate("UI", "Mouse buttons and/or the wheel.")
            : qsTranslate("UI", "Media keys.")
        color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
    }
    Flow {
        width: root.width; spacing: 5
        Repeater {
            model: root.options
            delegate: Rectangle {
                required property string modelData
                readonly property bool on: root.names.indexOf(modelData) >= 0
                height: 26; radius: 6
                width: Math.max(30, lbl.implicitWidth + 16)
                color: on ? Theme.accent : (oh.hovered ? Theme.cardHover : Theme.button)
                Text {
                    id: lbl; anchors.centerIn: parent
                    text: root.label(modelData)
                    color: parent.on ? Theme.textOnAccent : Theme.text
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
                HoverHandler { id: oh }
                TapHandler { onTapped: root.toggle(modelData) }
            }
        }
    }
}

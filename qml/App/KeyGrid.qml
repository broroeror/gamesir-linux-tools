import QtQuick
import App 1.0

// Inline keyboard picker (NOT a modal — no backdrop, no overlay). Ctrl/Shift/Alt/Meta
// toggles chord onto the next key. Emits picked("<combo>") with a bare combo spec
// ("ctrl+c", "a", "enter"), for building a macro key step. Sizes to its content.
Column {
    id: kg
    spacing: 8
    signal picked(string combo)

    property var mods: ({ ctrl: false, shift: false, alt: false, meta: false })
    function toggleMod(m) { var o = Object.assign({}, kg.mods); o[m] = !o[m]; kg.mods = o }
    function clearMods() { kg.mods = ({ ctrl: false, shift: false, alt: false, meta: false }) }
    function prefix() {
        var p = ""
        if (kg.mods.ctrl)  p += "ctrl+"
        if (kg.mods.shift) p += "shift+"
        if (kg.mods.alt)   p += "alt+"
        if (kg.mods.meta)  p += "meta+"
        return p
    }
    function choose(k) { kg.picked(kg.prefix() + k); kg.clearMods() }

    readonly property real ku: 28       // key unit (px)
    readonly property real kgap: 4

    readonly property var rows: [
        [{t:"Esc",k:"esc"},{t:"F1",k:"f1"},{t:"F2",k:"f2"},{t:"F3",k:"f3"},{t:"F4",k:"f4"},{t:"F5",k:"f5"},{t:"F6",k:"f6"},{t:"F7",k:"f7"},{t:"F8",k:"f8"},{t:"F9",k:"f9"},{t:"F10",k:"f10"},{t:"F11",k:"f11"},{t:"F12",k:"f12"}],
        [{t:"`",k:"`"},{t:"1",k:"1"},{t:"2",k:"2"},{t:"3",k:"3"},{t:"4",k:"4"},{t:"5",k:"5"},{t:"6",k:"6"},{t:"7",k:"7"},{t:"8",k:"8"},{t:"9",k:"9"},{t:"0",k:"0"},{t:"-",k:"-"},{t:"=",k:"="},{t:"⌫",k:"backspace",w:2}],
        [{t:"Tab",k:"tab",w:1.5},{t:"Q",k:"q"},{t:"W",k:"w"},{t:"E",k:"e"},{t:"R",k:"r"},{t:"T",k:"t"},{t:"Y",k:"y"},{t:"U",k:"u"},{t:"I",k:"i"},{t:"O",k:"o"},{t:"P",k:"p"},{t:"[",k:"["},{t:"]",k:"]"},{t:"\\",k:"\\",w:1.5}],
        [{t:"Caps",k:"capslock",w:1.75},{t:"A",k:"a"},{t:"S",k:"s"},{t:"D",k:"d"},{t:"F",k:"f"},{t:"G",k:"g"},{t:"H",k:"h"},{t:"J",k:"j"},{t:"K",k:"k"},{t:"L",k:"l"},{t:";",k:";"},{t:"'",k:"'"},{t:"↵",k:"enter",w:2.25}],
        [{t:"Z",k:"z"},{t:"X",k:"x"},{t:"C",k:"c"},{t:"V",k:"v"},{t:"B",k:"b"},{t:"N",k:"n"},{t:"M",k:"m"},{t:",",k:","},{t:".",k:"."},{t:"/",k:"/"}],
        [{t:"Space",k:"space",w:6},{t:"Del",k:"delete",w:1.4},{t:"Home",k:"home",w:1.4},{t:"End",k:"end",w:1.4},{t:"←",k:"left"},{t:"↑",k:"up"},{t:"↓",k:"down"},{t:"→",k:"right"}]
    ]

    // modifier toggles
    Row {
        spacing: 6
        Repeater {
            model: [{m:"ctrl",t:"Ctrl"},{m:"shift",t:"Shift"},{m:"alt",t:"Alt"},{m:"meta",t:"Meta"}]
            delegate: Rectangle {
                required property var modelData
                readonly property bool on: kg.mods[modelData.m] === true
                radius: 6; height: 26; width: mt.implicitWidth + 18
                color: on ? Theme.accent : Theme.button
                border.color: on ? Theme.accent : Theme.cardBorder; border.width: 1
                Text { id: mt; anchors.centerIn: parent; text: modelData.t
                       color: parent.on ? "white" : Theme.text
                       font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                TapHandler { onTapped: kg.toggleMod(modelData.m) }
            }
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "chord onto the next key"; color: Theme.textFaint
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
        }
    }

    // keyboard
    Column {
        spacing: kg.kgap
        Repeater {
            model: kg.rows
            delegate: Row {
                required property var modelData
                spacing: kg.kgap
                Repeater {
                    model: modelData
                    delegate: Rectangle {
                        required property var modelData
                        readonly property real kw: modelData.w !== undefined ? modelData.w : 1
                        width: kw * kg.ku + (kw - 1) * kg.kgap
                        height: kg.ku; radius: 4
                        color: kh.hovered ? Theme.accent : Theme.bg
                        border.color: kh.hovered ? Theme.accent : Theme.cardBorder
                        border.width: 1
                        Text {
                            anchors.centerIn: parent; text: modelData.t
                            color: kh.hovered ? "white" : Theme.text
                            font.family: Theme.fontFamily
                            font.pixelSize: modelData.t.length > 2 ? Theme.fontS : Theme.fontM
                        }
                        HoverHandler { id: kh }
                        TapHandler { onTapped: kg.choose(modelData.k) }
                    }
                }
            }
        }
    }
}

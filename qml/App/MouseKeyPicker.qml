import QtQuick
import App 1.0

// Modal keyboard picker for assigning a keyboard key (optionally with Ctrl/Shift/
// Alt/Meta) to a mouse button. Self-contained: its own layout data + spec
// vocabulary, so it does NOT depend on the controller bridge (per the "separate
// device models" design). Emits picked("key:<combo>") and closes.
//
// Parent it to a full-page Item; set `active = true` to open.
Item {
    id: kp
    anchors.fill: parent
    z: 1000
    property bool active: false
    signal picked(string spec)
    visible: active

    // active modifier toggles (chorded onto the next key press)
    property var mods: ({ ctrl: false, shift: false, alt: false, meta: false })
    function toggleMod(m) { var o = Object.assign({}, kp.mods); o[m] = !o[m]; kp.mods = o }
    function clearMods() { kp.mods = ({ ctrl: false, shift: false, alt: false, meta: false }) }
    function prefix() {
        var p = ""
        if (kp.mods.ctrl)  p += "ctrl+"
        if (kp.mods.shift) p += "shift+"
        if (kp.mods.alt)   p += "alt+"
        if (kp.mods.meta)  p += "meta+"
        return p
    }
    function choose(k) { kp.picked("key:" + kp.prefix() + k); kp.active = false; kp.clearMods() }
    function close() { kp.active = false; kp.clearMods() }

    readonly property real ku: 30       // key unit (px)
    readonly property real kg: 4        // key gap

    // rows of {t: display label, k: key name (spec), w: width units (default 1)}
    readonly property var rows: [
        [{t:"Esc",k:"esc"},{t:"F1",k:"f1"},{t:"F2",k:"f2"},{t:"F3",k:"f3"},{t:"F4",k:"f4"},{t:"F5",k:"f5"},{t:"F6",k:"f6"},{t:"F7",k:"f7"},{t:"F8",k:"f8"},{t:"F9",k:"f9"},{t:"F10",k:"f10"},{t:"F11",k:"f11"},{t:"F12",k:"f12"}],
        [{t:"`",k:"`"},{t:"1",k:"1"},{t:"2",k:"2"},{t:"3",k:"3"},{t:"4",k:"4"},{t:"5",k:"5"},{t:"6",k:"6"},{t:"7",k:"7"},{t:"8",k:"8"},{t:"9",k:"9"},{t:"0",k:"0"},{t:"-",k:"-"},{t:"=",k:"="},{t:"⌫",k:"backspace",w:2}],
        [{t:"Tab",k:"tab",w:1.5},{t:"Q",k:"q"},{t:"W",k:"w"},{t:"E",k:"e"},{t:"R",k:"r"},{t:"T",k:"t"},{t:"Y",k:"y"},{t:"U",k:"u"},{t:"I",k:"i"},{t:"O",k:"o"},{t:"P",k:"p"},{t:"[",k:"["},{t:"]",k:"]"},{t:"\\",k:"\\",w:1.5}],
        [{t:"Caps",k:"capslock",w:1.75},{t:"A",k:"a"},{t:"S",k:"s"},{t:"D",k:"d"},{t:"F",k:"f"},{t:"G",k:"g"},{t:"H",k:"h"},{t:"J",k:"j"},{t:"K",k:"k"},{t:"L",k:"l"},{t:";",k:";"},{t:"'",k:"'"},{t:"↵",k:"enter",w:2.25}],
        [{t:"Z",k:"z"},{t:"X",k:"x"},{t:"C",k:"c"},{t:"V",k:"v"},{t:"B",k:"b"},{t:"N",k:"n"},{t:"M",k:"m"},{t:",",k:","},{t:".",k:"."},{t:"/",k:"/"}],
        [{t:"Space",k:"space",w:6},{t:"Del",k:"delete",w:1.4},{t:"Home",k:"home",w:1.4},{t:"End",k:"end",w:1.4},{t:"←",k:"left"},{t:"↑",k:"up"},{t:"↓",k:"down"},{t:"→",k:"right"}]
    ]

    // dim backdrop; tap outside closes
    Rectangle {
        anchors.fill: parent; color: "#B3000000"
        TapHandler { onTapped: kp.close() }
    }

    // panel
    Rectangle {
        anchors.centerIn: parent
        color: Theme.card; border.color: Theme.cardBorder; border.width: 1; radius: Theme.radius
        width: col.width + 40; height: col.height + 40
        TapHandler {}                      // swallow taps so they don't close

        Text {                             // close ✕
            anchors.top: parent.top; anchors.topMargin: 12
            anchors.right: parent.right; anchors.rightMargin: 14
            text: "✕"; color: Theme.textDim; font.pixelSize: Theme.fontM
            TapHandler { onTapped: kp.close() }
        }

        Column {
            id: col
            anchors.centerIn: parent
            spacing: 12

            // header: title + modifier toggles
            Row {
                spacing: 8
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Assign a key"; color: Theme.text
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontL; font.weight: Font.DemiBold
                }
                Item { width: 14; height: 1 }
                Repeater {
                    model: [{m:"ctrl",t:"Ctrl"},{m:"shift",t:"Shift"},{m:"alt",t:"Alt"},{m:"meta",t:"Meta"}]
                    delegate: Rectangle {
                        required property var modelData
                        readonly property bool on: kp.mods[modelData.m] === true
                        radius: 6; height: 26; width: mt.implicitWidth + 18
                        anchors.verticalCenter: parent.verticalCenter
                        color: on ? Theme.accent : Theme.button
                        border.color: on ? Theme.accent : Theme.cardBorder; border.width: 1
                        Text {
                            id: mt; anchors.centerIn: parent; text: modelData.t
                            color: parent.on ? "white" : Theme.text
                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        }
                        TapHandler { onTapped: kp.toggleMod(modelData.m) }
                    }
                }
            }

            // keyboard
            Column {
                spacing: kp.kg
                Repeater {
                    model: kp.rows
                    delegate: Row {
                        required property var modelData
                        spacing: kp.kg
                        Repeater {
                            model: modelData
                            delegate: Rectangle {
                                required property var modelData
                                readonly property real kw: modelData.w !== undefined ? modelData.w : 1
                                width: kw * kp.ku + (kw - 1) * kp.kg
                                height: kp.ku; radius: 4
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
                                TapHandler { onTapped: kp.choose(modelData.k) }
                            }
                        }
                    }
                }
            }
        }
    }
}

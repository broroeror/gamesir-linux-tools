import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts
import App 1.0

// Tarantula Pro button remapping, stored in the pad: any button can send
// other pad buttons (up to 4 together), keyboard keys, mouse buttons/wheel or
// media keys, with turbo (8 / 12 / 20 Hz like the official app) and toggle.
Item {
    id: page
    property string sel: "L4"
    property string kind: "pad"
    property var names: []
    property bool toggle: false
    property int turbo: 0

    function load(k) {
        sel = k
        var r = t3.remaps[k]
        if (!r) return
        kind = r.vacant ? "pad" : (r.kind === "none" ? "pad" : r.kind)
        names = r.vacant ? [] : r.names.slice()
        toggle = r.toggle; turbo = r.turbo
        picker.kind = kind; picker.names = names
    }
    function isCustom(k) {
        var r = t3.remaps[k]
        if (!r) return false
        if (r.vacant) return true
        return !(r.kind === "pad" && r.names.length === 1 && r.names[0] === k) || r.turbo > 0 || r.toggle
    }
    function customList() {
        var out = []
        for (var i = 0; i < t3.remapKeys.length; i++) if (isCustom(t3.remapKeys[i])) out.push(t3.remapKeys[i])
        return out
    }
    function describe(k) {
        var r = t3.remaps[k]
        if (!r) return ""
        if (r.vacant) return (t3.macros[k] && t3.macros[k].active) ? qsTranslate("UI", "Macro") : qsTranslate("UI", "Nothing")
        var txt = r.names.join(" + ")
        if (r.kind === "kb") txt = qsTranslate("UI", "Keyboard") + ": " + txt
        if (r.kind === "mouse") txt = qsTranslate("UI", "Mouse") + ": " + txt
        if (r.kind === "media") txt = qsTranslate("UI", "Media") + ": " + txt
        return txt + (r.turbo ? "  · turbo " + r.turbo + " Hz" : "") + (r.toggle ? "  · " + qsTranslate("UI", "toggle") : "")
    }
    Component.onCompleted: load(sel)
    Connections { target: t3; function onStateChanged() { if (!t3.busy) page.load(page.sel) } }

    Text {
        visible: !t3.present
        anchors.centerIn: parent
        text: qsTranslate("UI", "Tarantula Pro not found. Plug its dongle in (XInput mode).")
        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
    }

    QQC.ScrollView {
        id: scroll
        visible: t3.present
        anchors.fill: parent; anchors.margins: 20
        clip: true; contentWidth: availableWidth
        QQC.ScrollBar.horizontal.policy: QQC.ScrollBar.AlwaysOff

        RowLayout {
            width: scroll.availableWidth; spacing: 20

            Card {
                Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop
                title: qsTranslate("UI", "Pick a button")
                T3ControllerView {
                    width: parent.width; height: width / aspect + topPad
                    selected: page.sel
                    marked: page.customList()
                    pickable: t3.remapKeys
                    onPicked: function (n) { page.load(n) }
                }
                Text {
                    width: parent.width; wrapMode: Text.WordWrap
                    text: qsTranslate("UI", "Green dot = button with a custom setting. HOME and M are reserved by the controller.")
                    color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
            }

            Card {
                Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop
                title: qsTranslate("UI", "Button %1").arg(page.sel)
                headerValue: page.describe(page.sel)
                enabled: !t3.busy

                Text {
                    text: qsTranslate("UI", "Sends")
                    color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
                T3OutputPicker {
                    id: picker; width: parent.width; maxPad: 3
                    onEdited: function (k, n) { page.kind = k; page.names = n }
                }
                Row {
                    spacing: 10
                    ToggleSwitch {
                        anchors.verticalCenter: parent.verticalCenter
                        checked: page.toggle; onToggled: function (on) { page.toggle = on }
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: qsTranslate("UI", "Toggle: one press holds it down, the next releases it")
                        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                    }
                }
                Row {
                    spacing: 6
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: qsTranslate("UI", "Turbo") + "  "
                        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                    }
                    Repeater {
                        model: [[0, qsTranslate("UI", "Off")], [8, "8 Hz"], [12, "12 Hz"], [20, "20 Hz"]]
                        delegate: PillButton {
                            required property var modelData
                            label: modelData[1]; highlight: page.turbo === modelData[0]
                            onClicked: page.turbo = modelData[0]
                        }
                    }
                }
                Row {
                    spacing: 8
                    PillButton {
                        label: qsTranslate("UI", "Save"); highlight: true
                        onClicked: t3.setRemap(page.sel, page.kind, page.names, page.toggle, page.turbo)
                    }
                    PillButton {
                        label: qsTranslate("UI", "Back to default")
                        onClicked: t3.resetRemap(page.sel)
                    }
                }
                Text {
                    width: parent.width; wrapMode: Text.WordWrap
                    visible: t3.macroKeys.indexOf(page.sel) >= 0
                    text: qsTranslate("UI", "Saving a remap on this button removes its macro.")
                    color: Theme.warn; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
            }
        }
    }
}

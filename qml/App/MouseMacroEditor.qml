import QtQuick
import QtQuick.Controls as QQC
import App 1.0

// Modal macro editor for a mouse button. Builds an ordered step list — key/shortcut
// (via the shared keyboard picker), typed text, delays, and mouse clicks — that the
// backend serializes to onboard-macro bytecode. Emits saved(json) with
// {"steps":[...],"repeat":bool}; the page stages that on the selected button.
//
// Parent it to a full-page Item; set `active = true` to open (optionally seed
// `steps`/`repeat` to edit an existing macro).
Item {
    id: ed
    anchors.fill: parent
    z: 900
    visible: active
    property bool active: false
    property string buttonName: ""
    signal saved(string json)

    property var steps: []             // [{t:'combo',combo}|{t:'text',text}|{t:'delay',ms}|{t:'click',button}]
    property bool repeat: false

    function open(name) { ed.buttonName = name || ""; ed.steps = []; ed.repeat = false; ed.active = true }
    function close() { ed.active = false }

    // array mutations reassign so bindings refresh
    function addStep(s) { var a = ed.steps.slice(); a.push(s); ed.steps = a }
    function removeAt(i) { var a = ed.steps.slice(); a.splice(i, 1); ed.steps = a }
    function moveUp(i) { if (i <= 0) return; var a = ed.steps.slice(); var t = a[i - 1]; a[i - 1] = a[i]; a[i] = t; ed.steps = a }
    function moveDown(i) { if (i >= ed.steps.length - 1) return; var a = ed.steps.slice(); var t = a[i + 1]; a[i + 1] = a[i]; a[i] = t; ed.steps = a }

    function titleCombo(c) {
        return ("" + c).split("+").map(function (p) {
            return p.length ? p[0].toUpperCase() + p.slice(1) : p }).join("+")
    }
    function stepLabel(s) {
        if (s.t === "combo") return titleCombo(s.combo)
        if (s.t === "text")  return "“" + s.text + "”"
        if (s.t === "delay") return "wait " + s.ms + " ms"
        if (s.t === "click") return "Click M" + s.button
        return JSON.stringify(s)
    }

    function doSave() {
        if (ed.steps.length === 0) return
        ed.saved(JSON.stringify({ steps: ed.steps, repeat: ed.repeat }))
        ed.close()
    }

    // dim backdrop; tap outside closes
    Rectangle {
        anchors.fill: parent; color: "#B3000000"
        TapHandler { onTapped: ed.close() }
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(parent.width - 80, 560)
        height: Math.min(parent.height - 80, col.implicitHeight + 40)
        color: Theme.card; border.color: Theme.cardBorder; border.width: 1; radius: Theme.radius
        TapHandler {}                    // swallow taps

        Column {
            id: col
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12

            // header
            Item {
                width: parent.width; height: 26
                Text {
                    anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                    text: "Macro" + (ed.buttonName ? " — " + ed.buttonName : "")
                    color: Theme.text; font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontL; font.weight: Font.DemiBold
                }
                Text {
                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    text: "✕"; color: Theme.textDim; font.pixelSize: Theme.fontM
                    TapHandler { onTapped: ed.close() }
                }
            }
            Rectangle { width: parent.width; height: 1; color: Theme.cardBorder }

            // ---- the step list ----
            Text {
                text: "Steps run top to bottom on each press."
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
            }
            Rectangle {
                width: parent.width
                height: Math.min(196, Math.max(44, stepCol.implicitHeight + 12))
                radius: Theme.radiusSm ? Theme.radiusSm : 6
                color: Theme.bg; border.color: Theme.cardBorder; border.width: 1
                QQC.ScrollView {
                    anchors.fill: parent; anchors.margins: 6; clip: true
                    contentWidth: availableWidth
                    QQC.ScrollBar.horizontal.policy: QQC.ScrollBar.AlwaysOff
                    Column {
                        id: stepCol
                        width: parent.width; spacing: 4
                        Text {
                            visible: ed.steps.length === 0
                            text: "No steps yet — add one below."
                            color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                            padding: 6
                        }
                        Repeater {
                            model: ed.steps
                            delegate: Rectangle {
                                required property var modelData
                                required property int index
                                width: stepCol.width; height: 30; radius: 6
                                color: Theme.button; border.color: Theme.cardBorder; border.width: 1
                                Text {
                                    anchors.left: parent.left; anchors.leftMargin: 9
                                    anchors.verticalCenter: parent.verticalCenter
                                    anchors.right: rowBtns.left; anchors.rightMargin: 8
                                    elide: Text.ElideRight
                                    text: (index + 1) + ".  " + ed.stepLabel(modelData)
                                    color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                                }
                                Row {
                                    id: rowBtns
                                    anchors.right: parent.right; anchors.rightMargin: 6
                                    anchors.verticalCenter: parent.verticalCenter; spacing: 3
                                    component Mini: Rectangle {
                                        property string glyph: ""
                                        signal act()
                                        width: 24; height: 22; radius: 5
                                        color: mh.hovered ? Theme.cardHover : Theme.card
                                        border.color: Theme.cardBorder; border.width: 1
                                        Text { anchors.centerIn: parent; text: parent.glyph
                                               color: Theme.textDim; font.pixelSize: Theme.fontS }
                                        HoverHandler { id: mh }
                                        TapHandler { onTapped: parent.act() }
                                    }
                                    Mini { glyph: "↑"; onAct: ed.moveUp(index) }
                                    Mini { glyph: "↓"; onAct: ed.moveDown(index) }
                                    Mini { glyph: "✕"; onAct: ed.removeAt(index) }
                                }
                            }
                        }
                    }
                }
            }

            Rectangle { width: parent.width; height: 1; color: Theme.cardBorder }

            // ---- add-step controls ----
            // key / shortcut
            Row {
                width: parent.width; spacing: 8
                PillButton { label: "⌨  Key…"; onClicked: keyPick.active = true }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "a keypress or shortcut (Ctrl+C, F5, Enter…)"
                    color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
            }
            // text
            Row {
                width: parent.width; spacing: 8
                QQC.TextField {
                    id: textField
                    width: parent.width - addTextBtn.width - 8
                    placeholderText: "type text…"
                    color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                    background: Rectangle { color: Theme.bg; radius: 6
                                           border.color: Theme.cardBorder; border.width: 1 }
                    onAccepted: if (text.length) { ed.addStep({ t: "text", text: text }); text = "" }
                }
                PillButton {
                    id: addTextBtn; label: "Add text"
                    onClicked: if (textField.text.length) { ed.addStep({ t: "text", text: textField.text }); textField.text = "" }
                }
            }
            // delay
            Row {
                width: parent.width; spacing: 6
                Text {
                    anchors.verticalCenter: parent.verticalCenter; width: 44
                    text: "Delay"; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
                Repeater {
                    model: [25, 50, 100, 250, 500]
                    delegate: PillButton {
                        required property var modelData
                        label: modelData + "ms"
                        onClicked: ed.addStep({ t: "delay", ms: modelData })
                    }
                }
            }
            // click
            Row {
                width: parent.width; spacing: 6
                Text {
                    anchors.verticalCenter: parent.verticalCenter; width: 44
                    text: "Click"; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
                Repeater {
                    model: 5
                    delegate: PillButton {
                        required property int index
                        label: "M" + (index + 1)
                        onClicked: ed.addStep({ t: "click", button: index + 1 })
                    }
                }
            }

            Rectangle { width: parent.width; height: 1; color: Theme.cardBorder }

            // repeat + footer
            Row {
                width: parent.width; spacing: 10
                ToggleSwitch {
                    id: repSw; anchors.verticalCenter: parent.verticalCenter
                    checked: ed.repeat; onToggled: ed.repeat = repSw.checked
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Repeat while the button is held"
                    color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
            }
            Row {
                anchors.right: parent.right; spacing: 8
                PillButton { label: "Cancel"; onClicked: ed.close() }
                PillButton {
                    label: "Save"; highlight: ed.steps.length > 0
                    onClicked: ed.doSave()
                }
            }
        }

        // embedded keyboard picker → adds a combo step
        MouseKeyPicker {
            id: keyPick
            onPicked: function (spec) {
                // spec is "key:<combo>"; store the bare combo as a step
                ed.addStep({ t: "combo", combo: spec.indexOf("key:") === 0 ? spec.slice(4) : spec })
            }
        }
    }
}

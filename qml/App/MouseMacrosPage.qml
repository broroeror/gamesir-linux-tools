import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts
import App 1.0

// Mouse macros tab, modelled on the controller MacroPage: TOP = the button picker
// (which button's macro, grouped like a paddle selector). LEFT = the sequence with a
// generic "+ Add event" (and ⏺ Record). RIGHT = the selected-step editor, where you
// choose WHAT the step does (Key / Click / Scroll / Media / Text) and its target
// inline — no add-submenus — plus during/hold + between/delay and the step tools.
// Everything sits in a FitScroll so the panels fit the window; edits stage the macro
// on that button (debounced) into the shared queue (no flash write until Apply).
Item {
    id: page

    property int btn: -1
    property var steps: []
    property bool repeat: false
    property int sel: -1
    property var clip: null

    readonly property var clickNames: ({ 1: "Left Click", 2: "Right Click", 3: "Middle Click", 4: "Back", 5: "Forward" })
    readonly property bool committedMacro: page.btn >= 0 && mouse.bindings[String(page.btn)] === "Macro"
    readonly property string curType: (page.sel >= 0 && page.sel < page.steps.length) ? page.steps[page.sel].t : ""

    // ---- load / persist ----------------------------------------------------
    function seed() {
        var m = page.btn >= 0 ? mouse.stagedMacro(page.btn) : ({})
        page.steps = (m && m.steps) ? m.steps.map(function (s) { return Object.assign({}, s) }) : []
        page.repeat = m && m.repeat === true
        page.sel = page.steps.length ? 0 : -1
        repSw.checked = page.repeat
    }
    Component.onCompleted: {
        if (page.btn < 0 && mouse.buttonList.length) page.btn = mouse.buttonList[0].index
        seed(); mouse.probeMacroSlots()
    }
    onBtnChanged: seed()
    onVisibleChanged: if (visible) { seed(); mouse.probeMacroSlots() }

    Timer { id: stageTimer; interval: 250; onTriggered: page.restage() }
    function touch() { page.steps = page.steps.slice(); stageTimer.restart() }
    function restage() {
        if (page.btn < 0) return
        if (page.steps.length)
            mouse.stageMacro(page.btn, JSON.stringify({ steps: page.steps, repeat: page.repeat }))
        else
            mouse.unstageItem("macro:" + page.btn)
    }

    function addStep(s) { var a = page.steps.slice(); a.push(s); page.steps = a; page.sel = a.length - 1; stageTimer.restart() }
    // "+ Add event": a generic default step (Left Click) — pick what it does on the right
    function addEvent() { addStep({ t: "click", button: 1, hold: 0, delay: 30 }) }
    function removeStep(i) {
        var a = page.steps.slice(); a.splice(i, 1); page.steps = a
        if (page.sel >= a.length) page.sel = a.length - 1
        stageTimer.restart()
    }
    function setField(i, key, val) { if (i >= 0 && i < page.steps.length) { page.steps[i][key] = val; touch() } }
    function setMedia(i, code, name) { if (i >= 0) { page.steps[i].code = code; page.steps[i].name = name; touch() } }
    // change a step's action type, preserving hold/delay and any reusable target
    function setType(i, t) {
        if (i < 0 || i >= page.steps.length) return
        var s = page.steps[i], hold = s.hold || 0, delay = s.delay || 30, n
        if (t === "key") n = { t: "key", combo: s.combo || "a", hold: hold, delay: delay }
        else if (t === "click") n = { t: "click", button: s.button || 1, hold: hold, delay: delay }
        else if (t === "scroll") n = { t: "scroll", delta: s.delta || 1, delay: delay }
        else if (t === "media") n = { t: "media", code: s.code || mouse.mediaActions[0].code, name: s.name || mouse.mediaActions[0].name, delay: delay }
        else if (t === "text") n = { t: "text", text: s.text || "", delay: delay }
        else return
        var a = page.steps.slice(); a[i] = n; page.steps = a; touch()
    }
    function move(dir) {
        var j = page.sel + dir
        if (page.sel < 0 || j < 0 || j >= page.steps.length) return
        var a = page.steps.slice(); var t = a[page.sel]; a[page.sel] = a[j]; a[j] = t
        page.steps = a; page.sel = j; stageTimer.restart()
    }
    function copyStep() { if (page.sel >= 0) page.clip = Object.assign({}, page.steps[page.sel]) }
    function pasteStep() {
        if (!page.clip) return
        var a = page.steps.slice(); a.splice(page.sel + 1, 0, Object.assign({}, page.clip))
        page.steps = a; page.sel = page.sel + 1; stageTimer.restart()
    }
    function duplicate() {
        if (page.sel < 0) return
        var a = page.steps.slice(); a.splice(page.sel + 1, 0, Object.assign({}, a[page.sel]))
        page.steps = a; page.sel = page.sel + 1; stageTimer.restart()
    }

    function titleCombo(c) {
        return ("" + c).split("+").map(function (p) { return p.length ? p[0].toUpperCase() + p.slice(1) : p }).join("+")
    }
    function stepLabel(s) {
        if (s.t === "key")    return page.titleCombo(s.combo)
        if (s.t === "click")  return page.clickNames[s.button] || ("Mouse " + s.button)
        if (s.t === "scroll") return "Scroll " + (s.delta >= 0 ? "↑" : "↓")
        if (s.t === "media")  return s.name || "Media"
        if (s.t === "text")   return "“" + s.text + "”"
        return ""
    }
    readonly property bool selTimed: page.curType === "key" || page.curType === "click"
    function stepTiming(s) {
        if (s.t === "key" || s.t === "click") return (s.hold || 0) + " / " + (s.delay || 0) + " ms"
        return (s.delay || 0) + " ms"
    }

    // ---- keystroke recording ----------------------------------------------
    property bool recording: false
    property real recDownTime: 0
    property string recDownCombo: ""
    property real recPrevUp: 0
    property int recCount: 0
    function isModifierKey(k) {
        return k === Qt.Key_Control || k === Qt.Key_Shift || k === Qt.Key_Alt || k === Qt.Key_Meta
            || k === Qt.Key_Super_L || k === Qt.Key_Super_R || k === Qt.Key_AltGr
    }
    function keyName(event) {
        var k = event.key
        if (k >= Qt.Key_A && k <= Qt.Key_Z) return String.fromCharCode(k).toLowerCase()
        if (k >= Qt.Key_0 && k <= Qt.Key_9) return String.fromCharCode(k)
        if (k >= Qt.Key_F1 && k <= Qt.Key_F24) return "f" + (k - Qt.Key_F1 + 1)
        var m = {}
        m[Qt.Key_Space] = "space"; m[Qt.Key_Return] = "enter"; m[Qt.Key_Enter] = "enter"
        m[Qt.Key_Tab] = "tab"; m[Qt.Key_Backspace] = "backspace"; m[Qt.Key_Delete] = "delete"
        m[Qt.Key_Home] = "home"; m[Qt.Key_End] = "end"; m[Qt.Key_PageUp] = "pageup"; m[Qt.Key_PageDown] = "pagedown"
        m[Qt.Key_Insert] = "insert"; m[Qt.Key_Left] = "left"; m[Qt.Key_Right] = "right"; m[Qt.Key_Up] = "up"; m[Qt.Key_Down] = "down"
        m[Qt.Key_CapsLock] = "capslock"; m[Qt.Key_Print] = "printscreen"; m[Qt.Key_ScrollLock] = "scrolllock"; m[Qt.Key_Pause] = "pause"
        if (m[k] !== undefined) return m[k]
        if (event.text && event.text.length === 1 && event.text.charCodeAt(0) >= 0x20) return event.text.toLowerCase()
        return ""
    }
    function comboFromEvent(event) {
        var base = page.keyName(event)
        if (!base) return ""
        var p = ""
        if (event.modifiers & Qt.ControlModifier) p += "ctrl+"
        if (event.modifiers & Qt.ShiftModifier && base.length !== 1) p += "shift+"
        if (event.modifiers & Qt.AltModifier) p += "alt+"
        if (event.modifiers & Qt.MetaModifier) p += "meta+"
        return p + base
    }
    function startRecord() { page.recPrevUp = 0; page.recDownCombo = ""; page.recCount = 0; page.recording = true; capture.forceActiveFocus() }
    function stopRecord() {
        if (page.recDownCombo) { addStep({ t: "key", combo: page.recDownCombo, hold: 0, delay: 0 }); page.recDownCombo = "" }
        page.recording = false
    }
    function recPress(event) {
        if (event.isAutoRepeat) return
        if (event.key === Qt.Key_Escape) { page.stopRecord(); return }
        if (page.isModifierKey(event.key)) return
        var combo = page.comboFromEvent(event)
        if (!combo) return
        if (page.recDownCombo) addStep({ t: "key", combo: page.recDownCombo, hold: 0, delay: 0 })
        if (page.steps.length && page.recPrevUp)
            page.setField(page.steps.length - 1, "delay", Math.max(0, Math.min(5000, Math.round(Date.now() - page.recPrevUp))))
        page.recDownTime = Date.now(); page.recDownCombo = combo
    }
    function recRelease(event) {
        if (event.isAutoRepeat || page.isModifierKey(event.key) || !page.recDownCombo) return
        addStep({ t: "key", combo: page.recDownCombo, hold: Math.max(0, Math.min(5000, Math.round(Date.now() - page.recDownTime))), delay: 0 })
        page.recPrevUp = Date.now(); page.recDownCombo = ""; page.recCount += 1
    }

    // editable ms field
    component NumField: Rectangle {
        property int value: 0
        signal committed(int v)
        width: 64; height: 24; radius: Theme.radiusSm
        color: Theme.bg; border.width: 1
        border.color: numIn.activeFocus ? Theme.accent : Theme.cardBorder
        TextInput {
            id: numIn
            anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 8
            verticalAlignment: TextInput.AlignVCenter
            text: parent.value; color: Theme.text
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
            selectByMouse: true; validator: IntValidator { bottom: 0; top: 65535 }
            onEditingFinished: parent.committed(parseInt(text) || 0)
        }
    }
    // ---------------------------------------------- not connected / no access
    MouseConnectState {}

    // ---------------------------------------------- connected: the editor
    FitScroll {
        id: scroller
        visible: mouse.present
        anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
        anchors.bottom: pbar.visible ? pbar.top : parent.bottom
        anchors.margins: 20; anchors.bottomMargin: 16
        content: fitBox

        Column {
            id: fitBox
            width: scroller.availableWidth
            spacing: Math.max(8, Math.round(14 * Theme.vComp))

            // ---- TOP: which button's macro (grouped like the paddle selector) ----
            Card {
                title: "Button"
                width: parent.width
                headerValue: (mouse.macroSlotsFree >= 0 ? mouse.macroSlotsFree + " slots free" : "")
                             + (page.committedMacro ? "  ·  runs a macro" : "")
                Flow {
                    width: parent.width; spacing: 16
                    Repeater {
                        model: mouse.buttonGroups
                        delegate: Column {
                            required property var modelData
                            spacing: 5
                            Text { text: modelData.group; color: Theme.textFaint
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                            Row {
                                spacing: 6
                                Repeater {
                                    model: modelData.buttons
                                    delegate: PillButton {
                                        required property var modelData
                                        label: modelData.name
                                        highlight: page.btn === modelData.index
                                        onClicked: page.btn = modelData.index
                                    }
                                }
                            }
                        }
                    }
                }
                Row {
                    width: parent.width; spacing: 10; topPadding: 4
                    ToggleSwitch { id: repSw; anchors.verticalCenter: parent.verticalCenter
                                   onToggled: { page.repeat = repSw.checked; page.touch() } }
                    Text { text: "Repeat while the button is held"; color: Theme.textDim
                           anchors.verticalCenter: parent.verticalCenter
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                }
            }

            // ---- master-detail: sequence | selected-step editor ----
            RowLayout {
                width: parent.width; spacing: 16

                // -------- LEFT: sequence + Add event / Record --------
                Card {
                    title: "Sequence"
                    headerValue: page.steps.length + " step" + (page.steps.length === 1 ? "" : "s")
                    Layout.fillWidth: true; Layout.horizontalStretchFactor: 3; Layout.alignment: Qt.AlignTop
                    Text {
                        visible: page.steps.length === 0
                        width: parent.width; wrapMode: Text.WordWrap
                        text: "Empty — + Add event to start, then pick what it does on the right (or ⏺ Record)."
                        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                    }
                    ListView {
                        id: stepList
                        width: parent.width
                        height: page.steps.length ? Math.min(8, page.steps.length) * 40 : 0
                        clip: true; spacing: 6; boundsBehavior: Flickable.StopAtBounds
                        model: page.steps.length
                        WheelHandler {
                            onWheel: function (ev) {
                                var max = Math.max(0, stepList.contentHeight - stepList.height)
                                stepList.contentY = Math.max(0, Math.min(max, stepList.contentY - ev.angleDelta.y))
                            }
                        }
                        delegate: Rectangle {
                            required property int index
                            width: ListView.view.width; height: 34; radius: Theme.radius
                            color: page.sel === index ? Theme.cardHover : "transparent"
                            border.color: page.sel === index ? Theme.accent : Theme.cardBorder; border.width: 1
                            Row {
                                anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 96; spacing: 8
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter; width: 16
                                    text: (index + 1); color: Theme.textDim
                                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter; width: 130; elide: Text.ElideRight
                                    text: page.stepLabel(page.steps[index]); color: Theme.text; font.bold: true
                                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: page.stepTiming(page.steps[index]); color: Theme.textDim
                                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                                }
                            }
                            Row {
                                anchors.right: parent.right; anchors.rightMargin: 8
                                anchors.verticalCenter: parent.verticalCenter; spacing: 4
                                component Mini: Rectangle {
                                    property string glyph: ""; signal act()
                                    width: 22; height: 22; radius: 5
                                    color: mh.hovered ? Theme.cardHover : "transparent"
                                    border.color: Theme.cardBorder; border.width: 1
                                    Text { anchors.centerIn: parent; text: parent.glyph; color: Theme.textDim; font.pixelSize: Theme.fontS }
                                    HoverHandler { id: mh }
                                    TapHandler { onTapped: parent.act() }
                                }
                                Mini { glyph: "⧉"; onAct: { page.sel = index; page.duplicate() } }
                                Mini { glyph: "✕"; onAct: page.removeStep(index) }
                            }
                            TapHandler { onTapped: page.sel = index }
                        }
                    }
                    Row {
                        width: parent.width; spacing: 6; topPadding: 2
                        PillButton { label: "+ Add event"; onClicked: page.addEvent() }
                        PillButton { label: "⏺ Record"; highlight: page.recording; onClicked: page.startRecord() }
                    }
                }

                // -------- RIGHT: selected-step editor (choose what it does) --------
                Card {
                    title: page.sel >= 0 ? "Step " + (page.sel + 1) : "Step"
                    Layout.fillWidth: true; Layout.horizontalStretchFactor: 4; Layout.alignment: Qt.AlignTop
                    visible: page.sel >= 0 && page.sel < page.steps.length

                    // action type
                    Text { text: "Action"; color: Theme.textDim
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                    Flow {
                        width: parent.width; spacing: 6
                        Repeater {
                            model: [["key", "Key"], ["click", "Mouse click"], ["scroll", "Scroll"], ["media", "Media"], ["text", "Text"]]
                            delegate: PillButton {
                                required property var modelData
                                label: modelData[1]
                                highlight: page.curType === modelData[0]
                                onClicked: page.setType(page.sel, modelData[0])
                            }
                        }
                    }

                    // ---- target, per type ----
                    // Key: current key + inline keyboard
                    Text {
                        visible: page.curType === "key"; topPadding: 4
                        text: "Key:  " + (page.curType === "key" ? page.titleCombo(page.steps[page.sel].combo) : "")
                        color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS; font.weight: Font.DemiBold
                    }
                    KeyGrid {
                        visible: page.curType === "key"
                        onPicked: function (combo) { page.setField(page.sel, "combo", combo) }
                    }
                    // Click
                    Flow {
                        width: parent.width; spacing: 6; visible: page.curType === "click"
                        Repeater {
                            model: [[1, "Left Click"], [2, "Right Click"], [3, "Middle Click"], [4, "Back"], [5, "Forward"]]
                            delegate: PillButton {
                                required property var modelData
                                label: modelData[1]
                                highlight: page.curType === "click" && page.steps[page.sel].button === modelData[0]
                                onClicked: page.setField(page.sel, "button", modelData[0])
                            }
                        }
                    }
                    // Scroll
                    Flow {
                        width: parent.width; spacing: 6; visible: page.curType === "scroll"
                        Repeater {
                            model: [[1, "Scroll Up"], [-1, "Scroll Down"]]
                            delegate: PillButton {
                                required property var modelData
                                label: modelData[1]
                                highlight: page.curType === "scroll" && (page.steps[page.sel].delta >= 0) === (modelData[0] > 0)
                                onClicked: page.setField(page.sel, "delta", modelData[0])
                            }
                        }
                    }
                    // Media
                    Flow {
                        width: parent.width; spacing: 6; visible: page.curType === "media"
                        Repeater {
                            model: mouse.mediaActions
                            delegate: PillButton {
                                required property var modelData
                                label: modelData.name
                                highlight: page.curType === "media" && page.steps[page.sel].code === modelData.code
                                onClicked: page.setMedia(page.sel, modelData.code, modelData.name)
                            }
                        }
                    }
                    // Text
                    QQC.TextField {
                        visible: page.curType === "text"
                        width: parent.width
                        text: page.curType === "text" ? page.steps[page.sel].text : ""
                        placeholderText: "text to type…"
                        color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        background: Rectangle { color: Theme.bg; radius: 6; border.color: Theme.cardBorder; border.width: 1 }
                        onEditingFinished: page.setField(page.sel, "text", text)
                    }

                    // ---- timing ----
                    Row {
                        width: parent.width; spacing: 10; topPadding: 4
                        visible: page.selTimed
                        Text { text: "During (hold)"; color: Theme.textDim; width: 92
                               anchors.verticalCenter: parent.verticalCenter
                               font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        AccentSlider {
                            width: parent.width - 92 - 74; from: 0; to: 2000
                            anchors.verticalCenter: parent.verticalCenter
                            value: page.selTimed ? (page.steps[page.sel].hold || 0) : 0
                            onMoved: function (v) { page.setField(page.sel, "hold", Math.round(v)) }
                        }
                        NumField {
                            anchors.verticalCenter: parent.verticalCenter
                            value: page.selTimed ? (page.steps[page.sel].hold || 0) : 0
                            onCommitted: function (v) { page.setField(page.sel, "hold", v) }
                        }
                    }
                    Row {
                        width: parent.width; spacing: 10
                        Text { text: "Between (delay)"; color: Theme.textDim; width: 92
                               anchors.verticalCenter: parent.verticalCenter
                               font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        AccentSlider {
                            width: parent.width - 92 - 74; from: 0; to: 2000
                            anchors.verticalCenter: parent.verticalCenter
                            value: page.sel >= 0 ? (page.steps[page.sel].delay || 0) : 0
                            onMoved: function (v) { page.setField(page.sel, "delay", Math.round(v)) }
                        }
                        NumField {
                            anchors.verticalCenter: parent.verticalCenter
                            value: page.sel >= 0 ? (page.steps[page.sel].delay || 0) : 0
                            onCommitted: function (v) { page.setField(page.sel, "delay", v) }
                        }
                    }
                    // ---- step tools ----
                    Flow {
                        width: parent.width; spacing: 6; topPadding: 4
                        PillButton { label: "Duplicate"; onClicked: page.duplicate() }
                        PillButton { label: "Copy"; onClicked: page.copyStep() }
                        PillButton { label: "Paste"; enabled: page.clip !== null; onClicked: page.pasteStep() }
                        PillButton { label: "Move ▲"; enabled: page.sel > 0; onClicked: page.move(-1) }
                        PillButton { label: "Move ▼"; enabled: page.sel >= 0 && page.sel < page.steps.length - 1; onClicked: page.move(1) }
                        PillButton { label: "Remove"; onClicked: page.removeStep(page.sel) }
                    }
                }
            }
        }
    }

    // ---- keystroke recording overlay ----
    Item {
        id: capture
        anchors.fill: parent
        z: 2000
        visible: page.recording
        focus: page.recording
        Keys.onPressed: function (event) { page.recPress(event); event.accepted = true }
        Keys.onReleased: function (event) { page.recRelease(event); event.accepted = true }
        Rectangle {
            anchors.fill: parent; color: "#D0000000"
            Column {
                anchors.centerIn: parent; spacing: 14
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter; spacing: 10
                    Rectangle { width: 12; height: 12; radius: 6; color: Theme.warn
                                anchors.verticalCenter: parent.verticalCenter
                                SequentialAnimation on opacity { loops: Animation.Infinite
                                    NumberAnimation { to: 0.3; duration: 500 } NumberAnimation { to: 1; duration: 500 } } }
                    Text { text: "Recording keystrokes"; color: Theme.text
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontL; font.weight: Font.DemiBold }
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: page.recCount + " captured  ·  timing is measured live"
                    color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Press keys to add them. Modifiers chord onto the next key."
                    color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
                PillButton { anchors.horizontalCenter: parent.horizontalCenter
                             label: "■ Stop (Esc)"; highlight: true; onClicked: page.stopRecord() }
            }
        }
    }

    // shared queue bar (buttons + sensor + macros); one Apply writes everything
    MousePendingBar {
        id: pbar
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        anchors.leftMargin: 20; anchors.rightMargin: 20; anchors.bottomMargin: 20
    }
}

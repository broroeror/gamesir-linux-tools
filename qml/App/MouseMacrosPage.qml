import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts
import App 1.0

// Mouse macros tab — modelled on the controller's MacroPage. Pick a button, build a
// sequence of steps (keys via the inline keyboard, text, or mouse clicks), each with
// a hold + delay-after time. Edits stage the macro on that button (no device write
// until the shared Apply), so building a macro never burns a flash slot until you
// commit — and re-applying an identical macro is a no-op.
Item {
    id: page

    property int btn: -1
    property var steps: []              // [{t:'key',combo,hold,delay}|{t:'click',button,hold,delay}|{t:'text',text,delay}]
    property bool repeat: false
    property int sel: -1
    property var clip: null

    function buttonName(i) {
        var l = mouse.buttonList
        for (var j = 0; j < l.length; j++) if (l[j].index === i) return l[j].name
        return "Button " + i
    }
    // does the selected button currently RUN a macro on the device?
    readonly property bool committedMacro: page.btn >= 0 && mouse.bindings[String(page.btn)] === "Macro"

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

    function touch() { page.steps = page.steps.slice(); stageTimer.restart() }   // re-trigger bindings + debounce restage
    Timer { id: stageTimer; interval: 250; onTriggered: page.restage() }
    function restage() {
        if (page.btn < 0) return
        if (page.steps.length)
            mouse.stageMacro(page.btn, JSON.stringify({ steps: page.steps, repeat: page.repeat }))
        else
            mouse.unstageItem("macro:" + page.btn)     // emptied -> drop the staged macro
    }

    function addStep(s) { var a = page.steps.slice(); a.push(s); page.steps = a; page.sel = a.length - 1; stageTimer.restart() }
    function addKey(combo) { addStep({ t: "key", combo: combo, hold: 0, delay: 30 }) }
    function addClick(n)   { addStep({ t: "click", button: n, hold: 0, delay: 30 }) }
    function addText(t)    { if (t && t.length) addStep({ t: "text", text: t, delay: 30 }) }
    function removeStep(i) {
        var a = page.steps.slice(); a.splice(i, 1); page.steps = a
        if (page.sel >= a.length) page.sel = a.length - 1
        stageTimer.restart()
    }
    function setField(i, key, val) { if (i >= 0) { page.steps[i][key] = val; touch() } }
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

    function titleCombo(c) {
        return ("" + c).split("+").map(function (p) { return p.length ? p[0].toUpperCase() + p.slice(1) : p }).join("+")
    }
    function stepLabel(s) {
        if (s.t === "key")   return page.titleCombo(s.combo)
        if (s.t === "click") return "Click M" + s.button
        if (s.t === "text")  return "“" + s.text + "”"
        return ""
    }
    function stepTiming(s) {
        if (s.t === "text") return (s.delay || 0) + " ms"
        return (s.hold || 0) + " / " + (s.delay || 0) + " ms"
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
        anchors.margins: 20
        content: fitBox

        Column {
            id: fitBox
            width: scroller.availableWidth
            spacing: Math.max(8, Math.round(14 * Theme.vComp))

            // ---- button selector + repeat + slots ----
            RowLayout {
                width: parent.width; spacing: 12
                Text { text: "Button"; color: Theme.textDim
                       font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                       Layout.alignment: Qt.AlignVCenter }
                Flow {
                    Layout.fillWidth: true; spacing: 6
                    Repeater {
                        model: mouse.buttonList
                        delegate: PillButton {
                            required property var modelData
                            label: modelData.name
                            highlight: page.btn === modelData.index
                            onClicked: page.btn = modelData.index
                        }
                    }
                }
                Text { text: "Repeat"; color: Theme.textDim
                       font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                       Layout.alignment: Qt.AlignVCenter }
                ToggleSwitch {
                    id: repSw; Layout.alignment: Qt.AlignVCenter
                    onToggled: { page.repeat = repSw.checked; page.touch() }
                }
            }
            Text {
                width: parent.width
                visible: mouse.macroSlotsFree >= 0
                text: mouse.macroSlotsFree + " macro slot" + (mouse.macroSlotsFree === 1 ? "" : "s") + " free"
                      + (page.committedMacro ? "  ·  this button already runs a macro" : "")
                color: mouse.macroSlotsFree === 0 ? Theme.warn : Theme.textFaint
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
            }

            // ---- master-detail: sequence | selected-step editor ----
            RowLayout {
                width: parent.width; spacing: 16

                // sequence list + text/click adders
                ColumnLayout {
                    Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 10
                    Card {
                        title: "Sequence"
                        headerValue: page.steps.length + " step" + (page.steps.length === 1 ? "" : "s")
                        Layout.fillWidth: true
                        Text {
                            visible: page.steps.length === 0
                            width: parent.width; wrapMode: Text.WordWrap
                            text: "Empty — click a key below, or add text / a mouse click."
                            color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        }
                        ListView {
                            id: stepList
                            width: parent.width
                            height: page.steps.length ? Math.min(6, page.steps.length) * 40 : 0
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
                                    anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 28; spacing: 8
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter; width: 16
                                        text: (index + 1); color: Theme.textDim
                                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter; width: 120; elide: Text.ElideRight
                                        text: page.stepLabel(page.steps[index]); color: Theme.text; font.bold: true
                                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: page.stepTiming(page.steps[index]); color: Theme.textDim
                                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                                    }
                                }
                                Text {
                                    anchors.right: parent.right; anchors.rightMargin: 10
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "✕"; color: Theme.textDim
                                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                                    TapHandler { onTapped: page.removeStep(index) }
                                }
                                TapHandler { onTapped: page.sel = index }
                            }
                        }
                        // quick add: text + clicks
                        RowLayout {
                            width: parent.width; spacing: 6
                            QQC.TextField {
                                id: textField
                                Layout.fillWidth: true
                                placeholderText: "type text…"
                                color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                                background: Rectangle { color: Theme.bg; radius: 6
                                                       border.color: Theme.cardBorder; border.width: 1 }
                                onAccepted: { page.addText(text); text = "" }
                            }
                            PillButton { label: "+ Text"; onClicked: { page.addText(textField.text); textField.text = "" } }
                            Repeater {
                                model: 5
                                delegate: PillButton {
                                    required property int index
                                    label: "M" + (index + 1)
                                    onClicked: page.addClick(index + 1)
                                }
                            }
                        }
                    }
                }

                // selected-step editor
                Card {
                    title: page.sel >= 0 ? "Step " + (page.sel + 1) + " — " + page.stepLabel(page.steps[page.sel]) : "Step"
                    Layout.fillWidth: true; Layout.preferredWidth: 1
                    visible: page.sel >= 0 && page.sel < page.steps.length

                    // editable text for a text step
                    Row {
                        width: parent.width; spacing: 10
                        visible: page.sel >= 0 && page.steps[page.sel].t === "text"
                        Text { text: "Text"; color: Theme.textDim; width: 84
                               anchors.verticalCenter: parent.verticalCenter
                               font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        QQC.TextField {
                            width: parent.width - 94
                            text: page.sel >= 0 && page.steps[page.sel].t === "text" ? page.steps[page.sel].text : ""
                            color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                            background: Rectangle { color: Theme.bg; radius: 6; border.color: Theme.cardBorder; border.width: 1 }
                            onEditingFinished: page.setField(page.sel, "text", text)
                        }
                    }
                    // hold (key/click only)
                    Row {
                        width: parent.width; spacing: 10
                        visible: page.sel >= 0 && page.steps[page.sel].t !== "text"
                        Text { text: "Hold"; color: Theme.textDim; width: 84
                               anchors.verticalCenter: parent.verticalCenter
                               font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        AccentSlider {
                            width: parent.width - 84 - 74; from: 0; to: 2000
                            anchors.verticalCenter: parent.verticalCenter
                            value: page.sel >= 0 ? (page.steps[page.sel].hold || 0) : 0
                            onMoved: function (v) { page.setField(page.sel, "hold", Math.round(v)) }
                        }
                        NumField {
                            anchors.verticalCenter: parent.verticalCenter
                            value: page.sel >= 0 ? (page.steps[page.sel].hold || 0) : 0
                            onCommitted: function (v) { page.setField(page.sel, "hold", v) }
                        }
                    }
                    // delay after (all steps)
                    Row {
                        width: parent.width; spacing: 10
                        Text { text: "Delay after"; color: Theme.textDim; width: 84
                               anchors.verticalCenter: parent.verticalCenter
                               font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        AccentSlider {
                            width: parent.width - 84 - 74; from: 0; to: 2000
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
                    Text { text: "Step tools"; color: Theme.textDim; topPadding: 6
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                    Flow {
                        width: parent.width; spacing: 6
                        PillButton { label: "Copy"; onClicked: page.copyStep() }
                        PillButton { label: "Paste"; enabled: page.clip !== null; onClicked: page.pasteStep() }
                        PillButton { label: "Move ▲"; enabled: page.sel > 0; onClicked: page.move(-1) }
                        PillButton { label: "Move ▼"; enabled: page.sel >= 0 && page.sel < page.steps.length - 1; onClicked: page.move(1) }
                        PillButton { label: "Remove"; onClicked: page.removeStep(page.sel) }
                    }
                }
            }

            // ---- add a key (inline keyboard) ----
            Card {
                title: "Add a key"
                width: parent.width
                KeyGrid {
                    id: keyGrid
                    onPicked: function (combo) { page.addKey(combo) }
                }
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

import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts
import App 1.0

// Tarantula Pro macros, two kinds:
//  * on-pad macros on the back/extra buttons (L4 R4 T1-T3 C1-C4): up to 12
//    timed steps stored in the controller, played by its firmware. A step can
//    press several pad buttons together, keyboard keys, mouse or media keys.
//  * HOME + button shortcuts: software macros the t3pro-bridge service runs.
Item {
    id: page

    property string selKey: "L4"
    property var steps: []           // [{kind, names, hold, delay}]
    property int selStep: 0
    property bool holdMode: false
    property bool loop: false
    property int loopTime: 1000

    property string homeBtn: "A"
    property string homeMode: "chord"    // "chord" = HOME + button, "button" = the button alone
    property string homeName: ""
    property var homeSteps: []

    function clone(o) { return JSON.parse(JSON.stringify(o)) }
    function loadKey(k) {
        selKey = k
        var m = t3.macros[k]
        steps = m ? clone(m.steps) : []
        holdMode = m ? m.hold : false
        loop = m ? m.loop : false
        loopTime = (m && m.loopTime) ? m.loopTime : 1000
        selStep = 0
        syncPicker()
    }
    function syncPicker() {
        if (selStep < steps.length) { stepPicker.kind = steps[selStep].kind; stepPicker.names = steps[selStep].names }
    }
    function setStep(i, field, v) { var s = steps.slice(); s[i] = clone(s[i]); s[i][field] = v; steps = s }
    // Repeater delegates must not replace their own model while handling an
    // event (Qt destroys the delegate mid-handler and crashes): defer it.
    function setStepLater(i, field, v) { Qt.callLater(setStep, i, field, v) }
    function removeStep(i) {
        var s = steps.slice(); s.splice(i, 1); steps = s
        selStep = Math.max(0, Math.min(selStep, s.length - 1)); syncPicker()
    }
    function setHomeStepLater(i, field, v) { Qt.callLater(setHomeStep, i, field, v) }
    function removeHomeStep(i) { var s = homeSteps.slice(); s.splice(i, 1); homeSteps = s }
    function stepText(s) {
        var pre = s.kind === "kb" ? "⌨ " : s.kind === "mouse" ? "🖱 " : s.kind === "media" ? "♪ " : ""
        return pre + (s.names.length ? s.names.join(" + ") : qsTranslate("UI", "(choose)"))
    }
    function macroKeysSet() {
        var out = []
        for (var i = 0; i < t3.macroKeys.length; i++) {
            var m = t3.macros[t3.macroKeys[i]]
            if (m && m.active) out.push(t3.macroKeys[i])
        }
        return out
    }
    function loadHome(b, mode) {
        if (mode !== undefined) homeMode = mode
        homeBtn = b; homeName = ""; homeSteps = []
        for (var i = 0; i < t3.homeMacros.length; i++)
            if (t3.homeMacros[i].button === b && t3.homeMacros[i].mode === homeMode) {
                homeName = t3.homeMacros[i].name
                homeSteps = clone(t3.homeMacros[i].steps)
            }
    }
    function setHomeStep(i, field, v) { var s = homeSteps.slice(); s[i] = clone(s[i]); s[i][field] = v; homeSteps = s }
    Component.onCompleted: { loadKey(selKey); loadHome(homeBtn) }
    Connections {
        target: t3
        function onStateChanged() { if (!t3.busy && !t3.recording) page.loadKey(page.selKey) }
        function onRecorded(key, recSteps) {
            if (key !== page.selKey) return
            page.steps = recSteps; page.selStep = 0; page.syncPicker()
        }
    }

    component NumField: Rectangle {
        property int value: 0
        signal committed(int v)
        width: 64; height: 26; radius: Theme.radiusSm
        color: Theme.bg; border.width: 1
        border.color: numIn.activeFocus ? Theme.accent : Theme.cardBorder
        TextInput {
            id: numIn
            anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 8
            verticalAlignment: TextInput.AlignVCenter
            text: parent.value; color: Theme.text
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
            selectByMouse: true; validator: IntValidator { bottom: 0; top: 60000 }
            onEditingFinished: parent.committed(parseInt(text) || 0)
        }
    }
    component Label: Text {
        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
        anchors.verticalCenter: parent ? parent.verticalCenter : undefined
    }

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

            ColumnLayout {
                Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop
                spacing: 14
                Card {
                    Layout.fillWidth: true
                    title: qsTranslate("UI", "Macro button")
                    T3ControllerView {
                        width: parent.width; height: width / aspect + topPad
                        selected: page.selKey
                        marked: page.macroKeysSet()
                        pickable: t3.macroKeys
                        onPicked: function (n) { page.loadKey(n) }
                    }
                    Text {
                        width: parent.width; wrapMode: Text.WordWrap
                        text: qsTranslate("UI", "Only the back buttons (L4, R4, C1–C4, T1–T3) can hold a macro. Green dot = macro saved.")
                        color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                    }
                }

                // ======================= HOME shortcuts =======================
                Card {
                    Layout.fillWidth: true
                    title: qsTranslate("UI", "PC shortcuts (run by the bridge)")
                    Text {
                        width: parent.width; wrapMode: Text.WordWrap
                        text: t3.bridgeRunning
                            ? qsTranslate("UI", "HOME + button: hold HOME and press the button (HOME alone still opens Steam). Button alone: the button fires the shortcut by itself — it can even send HOME + A. Run by the t3pro-bridge service; changes apply within a second.")
                            : qsTranslate("UI", "The t3pro-bridge service is not running, so these shortcuts are inactive.")
                        color: t3.bridgeRunning ? Theme.textFaint : Theme.warn
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                    }
                    Repeater {
                        model: t3.homeMacros
                        delegate: Row {
                            required property var modelData
                            spacing: 8
                            PillButton {
                                label: (modelData.mode === "chord" ? "HOME+" : "") + modelData.button
                                highlight: page.homeBtn === modelData.button && page.homeMode === modelData.mode
                                onClicked: page.loadHome(modelData.button, modelData.mode)
                            }
                            Label {
                                text: (modelData.name ? modelData.name + ": " : "") +
                                      modelData.steps.map(function (s) { return s.names }).join(" → ")
                                elide: Text.ElideRight; width: 240
                            }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.cardBorder }
                    Row {
                        spacing: 6
                        Label { text: qsTranslate("UI", "Trigger") + "  " }
                        PillButton { label: qsTranslate("UI", "HOME + button"); highlight: page.homeMode === "chord"
                                     onClicked: page.loadHome(page.homeBtn, "chord") }
                        PillButton { label: qsTranslate("UI", "Button alone"); highlight: page.homeMode === "button"
                                     onClicked: page.loadHome(t3.soloKeys.indexOf(page.homeBtn) >= 0 ? page.homeBtn : "R4", "button") }
                    }
                    Text {
                        width: parent.width; wrapMode: Text.WordWrap
                        visible: page.homeMode === "chord" && !t3.virtualDs4
                        text: qsTranslate("UI", "HOME + button shortcuts need the virtual PS4 controller (Device tab), which is off. Use “Button alone” on a back button instead.")
                        color: Theme.warn; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                    }
                    Text {
                        width: parent.width; wrapMode: Text.WordWrap
                        visible: page.homeMode === "button"
                        text: qsTranslate("UI", "Back buttons only. Saving maps the button on the controller to a spare key (L4 = F13 … T3 = F21) that the bridge turns into this shortcut; any pad macro or remap on it is replaced. Removing the shortcut maps the button back to itself.")
                        color: Theme.warn; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                    }
                    Row {
                        spacing: 8
                        Label { text: page.homeMode === "chord" ? "HOME +" : qsTranslate("UI", "Button") }
                        DropdownButton {
                            width: 100
                            readonly property var keys: page.homeMode === "button" ? t3.soloKeys : t3.chordKeys
                            model: keys
                            currentIndex: Math.max(0, keys.indexOf(page.homeBtn))
                            onActivated: function (i) { page.loadHome(keys[i]) }
                        }
                        QQC.TextField {
                            width: 190
                            text: page.homeName
                            placeholderText: qsTranslate("UI", "name (optional)")
                            color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                            background: Rectangle { color: Theme.bg; radius: 6; border.color: Theme.cardBorder; border.width: 1 }
                            onEditingFinished: page.homeName = text
                        }
                    }
                    Repeater {
                        model: page.homeSteps
                        delegate: Row {
                            required property var modelData
                            required property int index
                            spacing: 6
                            Label { text: (index + 1) + "."; width: 18 }
                            DropdownButton {
                                width: 100
                                model: [qsTranslate("UI", "Controller"), qsTranslate("UI", "Keyboard"), qsTranslate("UI", "Mouse"), "Steam"]
                                currentIndex: modelData.kind === "key" ? 1 : modelData.kind === "mouse" ? 2 : modelData.kind === "steam" ? 3 : 0
                                onActivated: function (i) { page.setHomeStepLater(index, "kind", ["pad", "key", "mouse", "steam"][i]) }
                            }
                            QQC.TextField {
                                width: 130
                                text: modelData.names
                                placeholderText: modelData.kind === "key" ? "LEFTCTRL+2" : modelData.kind === "mouse" ? "LEFT"
                                               : modelData.kind === "steam" ? "QAM / MENU / KEYBOARD" : "HOME+A"
                                color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                                background: Rectangle { color: Theme.bg; radius: 6; border.color: Theme.cardBorder; border.width: 1 }
                                onEditingFinished: page.setHomeStepLater(index, "names", text)
                            }
                            NumField { value: modelData.hold; onCommitted: function (v) { page.setHomeStepLater(index, "hold", Math.max(10, v)) } }
                            NumField { value: modelData.delay; onCommitted: function (v) { page.setHomeStepLater(index, "delay", v) } }
                            PillButton {
                                label: "✕"
                                onClicked: Qt.callLater(page.removeHomeStep, index)
                            }
                        }
                    }
                    Text {
                        width: parent.width; wrapMode: Text.WordWrap
                        text: qsTranslate("UI", "Per step: what to press, then hold ms and wait ms. Controller: A B X Y LB RB LT RT L3 R3 VIEW MENU UP DOWN LEFT RIGHT HOME CAMERA. Keyboard: Linux names, e.g. LEFTCTRL+2, F12, LEFTALT+TAB. Mouse: LEFT RIGHT MIDDLE SIDE EXTRA WHEEL_UP WHEEL_DOWN. Steam: QAM (quick access menu), MENU or KEYBOARD (on-screen keyboard on/off) — needs the Tarantula Pro Decky plugin, works whatever app is in front (button alone only).")
                        color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                    }
                    Row {
                        spacing: 8
                        PillButton {
                            label: qsTranslate("UI", "+ Step")
                            onClicked: { var s = page.homeSteps.slice(); s.push({kind: "pad", names: "", hold: 60, delay: 40}); page.homeSteps = s }
                        }
                        PillButton {
                            label: qsTranslate("UI", "Save shortcut"); highlight: true
                            enabled: page.homeSteps.length > 0
                            onClicked: Qt.callLater(function () { t3.setHomeMacro(page.homeBtn, page.homeName, page.homeSteps, page.homeMode) })
                        }
                        PillButton {
                            label: qsTranslate("UI", "Remove")
                            onClicked: { t3.removeHomeMacro(page.homeBtn, page.homeMode); page.loadHome(page.homeBtn) }
                        }
                    }
                }
            }

            // ======================= on-pad macro editor =======================
            Card {
                Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop
                title: qsTranslate("UI", "Macro on %1 (stored in the controller)").arg(page.selKey)
                enabled: !t3.busy || t3.recording !== ""

                Row {
                    spacing: 8
                    PillButton {
                        label: t3.recording ? qsTranslate("UI", "Stop recording") : qsTranslate("UI", "● Record on the controller")
                        highlight: t3.recording !== ""
                        onClicked: t3.recording ? t3.stopRecord() : t3.startRecord(page.selKey)
                    }
                }
                Text {
                    width: parent.width; wrapMode: Text.WordWrap
                    visible: t3.recording !== ""
                    text: qsTranslate("UI", "Recording… press the sequence on the controller (real timings are kept). Press HOME or Stop to finish. Nothing is saved until you press Save.")
                    color: Theme.warn; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }

                Repeater {
                    model: page.steps
                    delegate: Row {
                        required property var modelData
                        required property int index
                        spacing: 6
                        Label { text: (index + 1) + "."; width: 20 }
                        Rectangle {
                            width: 170; height: 28; radius: 6
                            color: page.selStep === index ? Theme.accent : (sh.hovered ? Theme.cardHover : Theme.button)
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.left: parent.left; anchors.leftMargin: 8; width: parent.width - 12
                                elide: Text.ElideRight
                                text: page.stepText(modelData)
                                color: page.selStep === index ? Theme.textOnAccent : Theme.text
                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                            }
                            HoverHandler { id: sh }
                            TapHandler { onTapped: { page.selStep = index; page.syncPicker() } }
                        }
                        Label { text: qsTranslate("UI", "hold") }
                        NumField { value: modelData.hold; onCommitted: function (v) { page.setStepLater(index, "hold", Math.max(10, v)) } }
                        Label { text: qsTranslate("UI", "wait") }
                        NumField { value: modelData.delay; onCommitted: function (v) { page.setStepLater(index, "delay", v) } }
                        PillButton {
                            label: "✕"
                            onClicked: Qt.callLater(page.removeStep, index)
                        }
                    }
                }
                PillButton {
                    label: qsTranslate("UI", "+ Step")
                    enabled: page.steps.length < 12
                    onClicked: {
                        var s = page.steps.slice(); s.push({kind: "pad", names: ["A"], hold: 60, delay: 40})
                        page.steps = s; page.selStep = s.length - 1; page.syncPicker()
                    }
                }
                Rectangle { width: parent.width; height: 1; color: Theme.cardBorder; visible: page.steps.length > 0 }
                Text {
                    visible: page.steps.length > 0
                    text: qsTranslate("UI", "Step %1 sends:").arg(page.selStep + 1)
                    color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
                T3OutputPicker {
                    id: stepPicker
                    visible: page.steps.length > 0
                    width: parent.width
                    onEdited: function (k, n) {
                        if (page.selStep >= page.steps.length) return
                        var s = page.steps.slice(); s[page.selStep] = page.clone(s[page.selStep])
                        s[page.selStep].kind = k; s[page.selStep].names = n; page.steps = s
                    }
                }
                Rectangle { width: parent.width; height: 1; color: Theme.cardBorder }
                Text {
                    text: qsTranslate("UI", "How it plays")
                    color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
                Row {
                    spacing: 6
                    PillButton { label: qsTranslate("UI", "Once per press"); highlight: !page.holdMode; onClicked: page.holdMode = false }
                    PillButton { label: qsTranslate("UI", "While held"); highlight: page.holdMode; onClicked: page.holdMode = true }
                }
                Row {
                    spacing: 8
                    ToggleSwitch {
                        anchors.verticalCenter: parent.verticalCenter
                        checked: page.loop; onToggled: function (on) { page.loop = on }
                    }
                    Label { text: qsTranslate("UI", "Repeat, cycle every") }
                    NumField { value: page.loopTime; enabled: page.loop; onCommitted: function (v) { page.loopTime = Math.max(10, v) } }
                    Label { text: "ms" }
                }
                Row {
                    spacing: 8
                    PillButton {
                        label: qsTranslate("UI", "Save to %1").arg(page.selKey); highlight: true
                        enabled: page.steps.length > 0 && !t3.recording
                        onClicked: Qt.callLater(function () { t3.setMacro(page.selKey, page.steps, page.holdMode, page.loop, page.loopTime) })
                    }
                    PillButton {
                        label: qsTranslate("UI", "Clear %1").arg(page.selKey)
                        enabled: !t3.recording
                        onClicked: t3.clearMacro(page.selKey)
                    }
                }
                Text {
                    width: parent.width; wrapMode: Text.WordWrap
                    text: qsTranslate("UI", "Saving a macro replaces the button's own mapping. Clearing it maps the button back to itself.")
                    color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
            }
        }
    }
}

import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts
import App 1.0

// Tarantula Pro macros, two kinds:
//  * on-pad macros on the back/extra buttons (L4 R4 T1-T3 C1-C4): up to 12
//    timed steps stored in the controller, played by its firmware;
//  * HOME + button shortcuts: software macros the t3pro-bridge service runs
//    (pad buttons through the virtual DS4, or keyboard keys).
Item {
    id: page

    property string selKey: "L4"
    property var steps: []           // [{button, hold, delay}]
    property bool holdMode: false

    property string homeBtn: "A"
    property string homeName: ""
    property var homeSteps: []       // [{kind, names, hold, delay}]

    function loadKey(k) {
        selKey = k
        var m = t3.macros[k]
        steps = m ? JSON.parse(JSON.stringify(m.steps)) : []
        holdMode = m ? m.hold : false
    }
    function setStep(i, field, v) { var s = steps.slice(); s[i][field] = v; steps = s }
    function loadHome(b) {
        homeBtn = b; homeName = ""; homeSteps = []
        for (var i = 0; i < t3.homeMacros.length; i++)
            if (t3.homeMacros[i].button === b) {
                homeName = t3.homeMacros[i].name
                homeSteps = JSON.parse(JSON.stringify(t3.homeMacros[i].steps))
            }
    }
    function setHomeStep(i, field, v) { var s = homeSteps.slice(); s[i][field] = v; homeSteps = s }
    Component.onCompleted: { loadKey(selKey); loadHome(homeBtn) }
    Connections { target: t3; function onStateChanged() { if (!t3.busy) page.loadKey(page.selKey) } }

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
        clip: true
        contentWidth: availableWidth
        QQC.ScrollBar.horizontal.policy: QQC.ScrollBar.AlwaysOff

        RowLayout {
            width: scroll.availableWidth; spacing: 20

            // ======================= on-pad macros =======================
            Card {
                Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop
                title: qsTranslate("UI", "Back-button macros (stored in the pad)")
                enabled: !t3.busy

                Flow {
                    width: parent.width; spacing: 6
                    Repeater {
                        model: t3.macroKeys
                        delegate: PillButton {
                            required property string modelData
                            label: modelData
                            highlight: page.selKey === modelData
                            statusDot: (t3.macros[modelData] && t3.macros[modelData].active) ? Theme.ok : "transparent"
                            onClicked: page.loadKey(modelData)
                        }
                    }
                }
                Text {
                    width: parent.width; wrapMode: Text.WordWrap
                    text: qsTranslate("UI", "Each step presses a button for <b>hold</b> ms, then waits <b>wait</b> ms. Up to 12 steps. Saving a macro replaces the button's own mapping.")
                    textFormat: Text.StyledText
                    color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
                Repeater {
                    model: page.steps
                    delegate: Row {
                        required property var modelData
                        required property int index
                        spacing: 8
                        Label { text: (index + 1) + "." ; width: 22 }
                        DropdownButton {
                            width: 96
                            model: t3.stepButtons
                            currentIndex: Math.max(0, t3.stepButtons.indexOf(modelData.button))
                            onActivated: function (i) { page.setStep(index, "button", t3.stepButtons[i]) }
                        }
                        Label { text: qsTranslate("UI", "hold") }
                        NumField { value: modelData.hold; onCommitted: function (v) { page.setStep(index, "hold", Math.max(10, v)) } }
                        Label { text: qsTranslate("UI", "wait") }
                        NumField { value: modelData.delay; onCommitted: function (v) { page.setStep(index, "delay", v) } }
                        PillButton {
                            label: "✕"
                            onClicked: { var s = page.steps.slice(); s.splice(index, 1); page.steps = s }
                        }
                    }
                }
                Row {
                    spacing: 8
                    PillButton {
                        label: qsTranslate("UI", "+ Step")
                        enabled: page.steps.length < 12
                        onClicked: { var s = page.steps.slice(); s.push({button: "A", hold: 60, delay: 40}); page.steps = s }
                    }
                    ToggleSwitch {
                        anchors.verticalCenter: parent.verticalCenter
                        checked: page.holdMode
                        onToggled: function (on) { page.holdMode = on }
                    }
                    Label { text: page.holdMode ? qsTranslate("UI", "runs while held") : qsTranslate("UI", "runs once per press") }
                }
                Row {
                    spacing: 8
                    PillButton {
                        label: qsTranslate("UI", "Save to %1").arg(page.selKey); highlight: true
                        enabled: page.steps.length > 0
                        onClicked: t3.setMacro(page.selKey, page.steps, page.holdMode)
                    }
                    PillButton {
                        label: qsTranslate("UI", "Clear %1").arg(page.selKey)
                        onClicked: t3.clearMacro(page.selKey)
                    }
                }
            }

            // ======================= HOME shortcuts =======================
            Card {
                Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop
                title: qsTranslate("UI", "HOME + button shortcuts")

                Text {
                    width: parent.width; wrapMode: Text.WordWrap
                    text: t3.bridgeRunning
                        ? qsTranslate("UI", "Hold HOME and press the button. HOME alone still opens Steam. Run by the t3pro-bridge service; changes apply within a second.")
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
                            label: "HOME+" + modelData.button
                            highlight: page.homeBtn === modelData.button
                            onClicked: page.loadHome(modelData.button)
                        }
                        Label {
                            text: (modelData.name ? modelData.name + ": " : "") +
                                  modelData.steps.map(function (s) { return s.names }).join(" → ")
                            elide: Text.ElideRight; width: 260
                        }
                    }
                }
                Rectangle { width: parent.width; height: 1; color: Theme.cardBorder }
                Row {
                    spacing: 8
                    Label { text: "HOME +" }
                    DropdownButton {
                        width: 100
                        model: t3.chordKeys
                        currentIndex: Math.max(0, t3.chordKeys.indexOf(page.homeBtn))
                        onActivated: function (i) { page.loadHome(t3.chordKeys[i]) }
                    }
                    QQC.TextField {
                        width: 200
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
                        spacing: 8
                        Label { text: (index + 1) + "."; width: 22 }
                        DropdownButton {
                            width: 96
                            model: [qsTranslate("UI", "Pad"), qsTranslate("UI", "Keys")]
                            currentIndex: modelData.kind === "key" ? 1 : 0
                            onActivated: function (i) { page.setHomeStep(index, "kind", i === 1 ? "key" : "pad") }
                        }
                        QQC.TextField {
                            width: 150
                            text: modelData.names
                            placeholderText: modelData.kind === "key" ? "LEFTCTRL+2" : "X+Y"
                            color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                            background: Rectangle { color: Theme.bg; radius: 6; border.color: Theme.cardBorder; border.width: 1 }
                            onEditingFinished: page.setHomeStep(index, "names", text)
                        }
                        Label { text: qsTranslate("UI", "hold") }
                        NumField { value: modelData.hold; onCommitted: function (v) { page.setHomeStep(index, "hold", Math.max(10, v)) } }
                        Label { text: qsTranslate("UI", "wait") }
                        NumField { value: modelData.delay; onCommitted: function (v) { page.setHomeStep(index, "delay", v) } }
                        PillButton {
                            label: "✕"
                            onClicked: { var s = page.homeSteps.slice(); s.splice(index, 1); page.homeSteps = s }
                        }
                    }
                }
                Text {
                    width: parent.width; wrapMode: Text.WordWrap
                    text: qsTranslate("UI", "Pad buttons: %1. Keys use Linux names without KEY_, e.g. LEFTCTRL+2, F12, LEFTALT+TAB.").arg(t3.chordKeys.concat(["HOME"]).join(" "))
                    color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
                Row {
                    spacing: 8
                    PillButton {
                        label: qsTranslate("UI", "+ Step")
                        onClicked: { var s = page.homeSteps.slice(); s.push({kind: "pad", names: "", hold: 60, delay: 40}); page.homeSteps = s }
                    }
                    PillButton {
                        label: qsTranslate("UI", "Save HOME+%1").arg(page.homeBtn); highlight: true
                        enabled: page.homeSteps.length > 0
                        onClicked: t3.setHomeMacro(page.homeBtn, page.homeName, page.homeSteps)
                    }
                    PillButton {
                        label: qsTranslate("UI", "Remove")
                        onClicked: { t3.removeHomeMacro(page.homeBtn); page.loadHome(page.homeBtn) }
                    }
                }
            }
        }
    }
}

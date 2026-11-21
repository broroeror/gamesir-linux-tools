import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts
import App 1.0

// Tarantula Pro gyro handled by the controller itself (same options as
// GameSir Connect's motion page): how it is activated, what it drives (left
// or right stick, or the mouse), aim/tilt mode, axes, sensitivity, inversion
// and deadzone. Independent of the t3pro-bridge, which always passes the raw
// gyro to Steam through the virtual DS4.
Item {
    id: page
    property var m: ({})
    property bool dirty: false

    function seed() { m = JSON.parse(JSON.stringify(t3.motion || {})); dirty = false }
    function set(k, v) { var c = JSON.parse(JSON.stringify(m)); c[k] = v; m = c; dirty = true }
    function keyName(code) {
        var kc = t3.keyCodes
        for (var n in kc) if (kc[n] === code) return n
        return "?"
    }
    Component.onCompleted: seed()
    onVisibleChanged: if (visible && !dirty) seed()
    Connections { target: t3; function onStateChanged() { if (!t3.busy && !page.dirty) page.seed() } }

    component Label: Text {
        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
    }
    component Pills: Flow {
        id: pills
        property var options: []         // [[value, label]]
        property int value: 0
        signal chosen(int v)
        spacing: 6
        Repeater {
            model: pills.options
            delegate: PillButton {
                required property var modelData
                label: modelData[1]; highlight: pills.value === modelData[0]
                onClicked: pills.chosen(modelData[0])
            }
        }
    }
    component SliderRow: Column {
        id: sr
        property string text: ""
        property int value: 0
        property int to: 100
        signal moved(int v)
        spacing: 2
        Row {
            width: sr.width
            Text { text: sr.text; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
            Item { width: sr.width - 160; height: 1 }
            Text { text: sl.value; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
        }
        AccentSlider { id: sl; width: sr.width; from: 0; to: sr.to; value: sr.value; onMoved: function (v) { sr.moved(Math.round(v)) } }
    }

    Text {
        visible: !t3.present
        anchors.centerIn: parent
        text: qsTranslate("UI", "Tarantula Pro not found. Plug its dongle in (XInput mode).")
        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
    }

    QQC.ScrollView {
        id: scroll
        visible: t3.present && m.activation !== undefined
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
                    title: qsTranslate("UI", "Activation")
                    Pills {
                        width: parent.width
                        value: page.m.activation || 0
                        // values follow the firmware's trigger enum (SDK): 1 one-shot = toggle, 2 hold
                        options: [[0, qsTranslate("UI", "Off")], [2, qsTranslate("UI", "While holding a button")],
                                  [1, qsTranslate("UI", "On/off with a button")], [3, qsTranslate("UI", "Always on")]]
                        onChosen: function (v) { page.set("activation", v) }
                    }
                    Label {
                        width: parent.width; wrapMode: Text.WordWrap
                        text: page.m.activation === 2 ? qsTranslate("UI", "The gyro works only while the activation button is held.")
                            : page.m.activation === 1 ? qsTranslate("UI", "Each press of the activation button turns the gyro on or off.")
                            : page.m.activation === 3 ? qsTranslate("UI", "The gyro is always active.")
                            : qsTranslate("UI", "The controller does not use the gyro by itself.")
                    }
                    Label {
                        visible: page.m.activation === 1 || page.m.activation === 2
                        text: qsTranslate("UI", "Activation button: <b>%1</b> — click a button on the drawing").arg(page.keyName(page.m.key))
                        textFormat: Text.StyledText
                    }
                    T3ControllerView {
                        visible: page.m.activation === 1 || page.m.activation === 2
                        width: parent.width; height: width / aspect + topPad
                        showBackHint: false
                        selected: page.keyName(page.m.key)
                        pickable: t3.remapKeys
                        onPicked: function (n) { page.set("key", t3.keyCodes[n]) }
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop
                spacing: 14
                Card {
                    Layout.fillWidth: true
                    title: qsTranslate("UI", "Output")
                    Pills {
                        width: parent.width
                        value: page.m.output || 0
                        options: [[0, qsTranslate("UI", "None")], [1, qsTranslate("UI", "Left stick")],
                                  [2, qsTranslate("UI", "Right stick")], [4, qsTranslate("UI", "Mouse")]]
                        onChosen: function (v) { page.set("output", v) }
                    }
                    Label {
                        width: parent.width; wrapMode: Text.WordWrap
                        visible: (page.m.output || 0) !== 0 && t3.bridgeRunning
                        color: Theme.warn
                        text: qsTranslate("UI", "The gyro bridge already gives Steam the raw gyro. If Steam gyro is also on, both will move the camera — use one or the other.")
                    }
                    Label { text: qsTranslate("UI", "Mode") }
                    Pills {
                        width: parent.width
                        value: page.m.kind || 0
                        options: [[0, qsTranslate("UI", "Aim (turn the controller)")], [1, qsTranslate("UI", "Tilt (steering)")]]
                        onChosen: function (v) { page.set("kind", v) }
                    }
                    Label { text: qsTranslate("UI", "Axes") }
                    Pills {
                        width: parent.width
                        value: page.m.axes || 0
                        options: [[0, "Yaw"], [1, "Roll"], [2, qsTranslate("UI", "Combined")]]
                        onChosen: function (v) { page.set("axes", v) }
                    }
                }
                Card {
                    Layout.fillWidth: true
                    title: qsTranslate("UI", "Response")
                    SliderRow { width: parent.width; text: qsTranslate("UI", "Horizontal sensitivity"); value: page.m.sens_x || 0
                                onMoved: function (v) { page.set("sens_x", v) } }
                    SliderRow { width: parent.width; text: qsTranslate("UI", "Vertical sensitivity"); value: page.m.sens_y || 0
                                onMoved: function (v) { page.set("sens_y", v) } }
                    SliderRow { width: parent.width; text: qsTranslate("UI", "Deadzone"); value: page.m.deadzone || 0
                                onMoved: function (v) { page.set("deadzone", v) } }
                    SliderRow { width: parent.width; text: qsTranslate("UI", "Anti-deadzone"); value: page.m.anti_deadzone || 0
                                onMoved: function (v) { page.set("anti_deadzone", v) } }
                    SliderRow { width: parent.width; visible: page.m.kind === 1
                                text: qsTranslate("UI", "Tilt range"); value: page.m.range || 0
                                onMoved: function (v) { page.set("range", v) } }
                    Row {
                        spacing: 8
                        ToggleSwitch { checked: !!page.m.invert_x; onToggled: function (on) { page.set("invert_x", on ? 1 : 0) } }
                        Label { text: qsTranslate("UI", "Invert horizontal"); anchors.verticalCenter: parent.verticalCenter }
                        Item { width: 20; height: 1 }
                        ToggleSwitch { checked: !!page.m.invert_y; onToggled: function (on) { page.set("invert_y", on ? 1 : 0) } }
                        Label { text: qsTranslate("UI", "Invert vertical"); anchors.verticalCenter: parent.verticalCenter }
                    }
                }
                Row {
                    spacing: 8
                    PillButton {
                        label: qsTranslate("UI", "Save gyro settings"); highlight: true
                        enabled: page.dirty && !t3.busy
                        statusDot: page.dirty ? Theme.warn : "transparent"
                        onClicked: { t3.setMotion(page.m); page.dirty = false }
                    }
                    PillButton {
                        label: qsTranslate("UI", "Discard changes")
                        enabled: page.dirty
                        onClicked: page.seed()
                    }
                }
            }
        }
    }
}

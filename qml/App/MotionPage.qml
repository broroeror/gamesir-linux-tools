import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts
import App 1.0

// GameSir gyro (motion) editor. Adapts to each controller's block via the bridge's
// capability props: the 8K has Aim+Tilt, 3-button activation, Roll/Y/Yaw inverts
// (gated by the X-axis mode), a sensitivity slider and 16-bit deadzone maxima; the
// Cyclone is a compact variant (Aim only, single activation button, X/Y inverts,
// no sensitivity, byte deadzones). All controls write immediately.
Item {
    id: page

    property int sec: 0                                   // 0 = Aim, 1 = Tilt
    readonly property string section: sec === 0 ? "Aim" : "Tilt"
    property var aim: ({})
    property var tilt: ({})
    readonly property var cur: sec === 0 ? aim : tilt

    function seed() {
        aim = bridge.motionAim
        tilt = bridge.motionTilt
        reseed()
    }
    function reseed() {
        dzRange.lo = num(cur.dz_min, 0);   dzRange.hi = num(cur.dz_max, 100)
        adzRange.lo = num(cur.adz_min, 0); adzRange.hi = num(cur.adz_max, 100)
        xySlider.value = num(cur.xy_scale, 50)
        sensSlider.value = num(cur.sens, 50)
        curveIntSlider.value = num(cur.curve_int, 100)
    }
    function num(v, d) { return v !== undefined ? v : d }
    Component.onCompleted: seed()
    Connections { target: bridge; function onMotionLoaded() { page.seed() } }
    onVisibleChanged: if (visible) seed()
    onSecChanged: reseed()

    function apply(field, val) {
        var d = sec === 0 ? aim : tilt
        var nd = {}; for (var k in d) nd[k] = d[k]
        nd[field] = val
        if (sec === 0) aim = nd; else tilt = nd
    }
    function setEnum(field, idx)  { apply(field, idx); bridge.setMotionEnum(section, field, idx) }
    function setVal(field, v)     { apply(field, v);   bridge.setMotionValue(section, field, v) }
    function setInvert(i, on)     { apply("invert_" + i, on); bridge.setMotionInvert(section, i, on) }

    // Directional-Macros output: 4 target-code slots (up/down/left/right).
    property int dirEdit: -1
    function dirLabel(i) {
        var d = cur.dir_macros
        var c = (d && d.length > i) ? d[i] : 0
        return c > 0 ? bridge.targetLabel(c) : "—"
    }
    function setDir(i, code) {
        var d = cur.dir_macros ? cur.dir_macros.slice() : [0, 0, 0, 0]
        d[i] = code < 0 ? 0 : code; apply("dir_macros", d)
        bridge.setMotionDir(section, i, code)
    }
    function setCurveType(idx)    { apply("curve_type", idx); bridge.setMotionCurveType(section, idx) }
    function setCurveStrength(v)  { apply("curve_int", v);    bridge.setMotionCurveStrength(section, v) }

    // deadzone writes are single-field + cheap, but debounce a drag anyway
    Timer { id: dzTimer; interval: 200
            onTriggered: { bridge.setMotionDeadzone(page.section, "dz_min", dzRange.lo)
                           bridge.setMotionDeadzone(page.section, "dz_max", dzRange.hi) } }
    Timer { id: adzTimer; interval: 200
            onTriggered: { bridge.setMotionDeadzone(page.section, "adz_min", adzRange.lo)
                           bridge.setMotionDeadzone(page.section, "adz_max", adzRange.hi) } }

    // activation combo
    readonly property int slotEmpty: 255
    readonly property var slots: cur.act_slots ? cur.act_slots : []
    function isSel(code) { return slots.indexOf(code) >= 0 }
    function selCount() { var n = 0; for (var i = 0; i < slots.length; i++) if (slots[i] !== slotEmpty) n++; return n }
    function toggleBtn(code) {
        var on = !isSel(code)
        if (on && selCount() >= bridge.motionButtonMax) return
        bridge.setMotionButton(section, code, on)
        seed()                                    // re-pull slots from the bridge
    }

    // inverts: only the axis exposed by the X-axis mode is live (8K); Cyclone X/Y
    // inverts aren't gated.
    function invLive(label) {
        if (!bridge.motionXAxisGatesInverts) return true
        if (label.indexOf("Roll") >= 0) return cur.xaxis === 1 || cur.xaxis === 2
        if (label.indexOf("Yaw") >= 0)  return cur.xaxis === 0 || cur.xaxis === 2
        return true
    }

    // Content stays at its natural (preset) size and SCROLLS if the window is
    // too short — text never scales down, so nothing gets illegibly narrow.
    // Cards compress their vertical padding (Theme.vComp via FitScroll) to fit
    // the window before scrolling — contents stay full-size.
    FitScroll {
        id: scroller
        anchors.fill: parent
        anchors.margins: 20
        content: fitBox

        Column {
            id: fitBox
            width: scroller.availableWidth
            spacing: Math.max(6, Math.round(14 * Theme.vComp))

            Row {
                spacing: 8
                Repeater {
                    model: bridge.motionHasTilt ? ["Aim", "Tilt"] : ["Aim"]
                    delegate: PillButton {
                        required property string modelData
                        required property int index
                        label: modelData
                        highlight: page.sec === index
                        onClicked: page.sec = index
                    }
                }
                Item { width: 8; height: 1 }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: page.sec === 0 ? "Aim — point-to-aim gyro" : "Tilt — lean-to-steer gyro"
                    color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
            }

            RowLayout {
                width: parent.width; spacing: 20

                // ================= left column =================
                ColumnLayout {
                    Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 12
                    Card {
                        title: "Activation"; Layout.fillWidth: true
                        Text { text: "Method"; color: Theme.textDim
                               font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        Flow {
                            width: parent.width; spacing: 8
                            Repeater {
                                model: bridge.motionActMethods
                                delegate: PillButton {
                                    required property string modelData
                                    required property int index
                                    label: modelData
                                    highlight: page.cur.act_method === index
                                    onClicked: page.setEnum("act_method", index)
                                }
                            }
                        }
                        Text {
                            text: bridge.motionButtonMax > 1
                                  ? "Activation buttons  (up to " + bridge.motionButtonMax + ", held together)"
                                  : "Activation button"
                            color: Theme.textDim; topPadding: 4
                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        }
                        Flow {
                            width: parent.width; spacing: 6
                            opacity: page.cur.act_method !== 0 ? 1.0 : 0.4
                            Repeater {
                                model: bridge.motionButtons
                                delegate: PillButton {
                                    required property var modelData
                                    label: modelData.name
                                    highlight: page.isSel(modelData.code)
                                    enabled: page.cur.act_method !== 0
                                             && (page.isSel(modelData.code)
                                                 || page.selCount() < bridge.motionButtonMax)
                                    onClicked: page.toggleBtn(modelData.code)
                                }
                            }
                        }
                    }

                    Card {
                        title: "Output"; Layout.fillWidth: true
                        Flow {
                            width: parent.width; spacing: 8
                            Repeater {
                                model: bridge.motionOutputs
                                delegate: PillButton {
                                    required property string modelData
                                    required property int index
                                    label: modelData
                                    highlight: page.cur.output === index
                                    onClicked: page.setEnum("output", index)
                                }
                            }
                        }
                        Row {
                            width: parent.width; topPadding: 6; visible: bridge.motionHasSens
                            Text { text: "Sensitivity"; color: Theme.textDim
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                            Item { width: parent.width - 130; height: 1 }
                            Text { text: sensSlider.value + "%"; color: Theme.text
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        }
                        AccentSlider {
                            id: sensSlider; width: parent.width; from: 0; to: 100
                            visible: bridge.motionHasSens
                            onMoved: page.setVal("sens", value)
                        }
                        Row {
                            width: parent.width; topPadding: 4
                            Text { text: "Horizontal"; color: Theme.textDim
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                            Item { width: parent.width - 150; height: 1 }
                            Text { text: "Vertical"; color: Theme.textDim
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        }
                        AccentSlider {
                            id: xySlider; width: parent.width; from: 0; to: 100
                            onMoved: page.setVal("xy_scale", value)
                        }
                        Text {
                            width: parent.width; text: "X / Y sensitivity balance"
                            color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                            horizontalAlignment: Text.AlignHCenter
                        }
                    }

                    // Directional-Macros output: assign each gyro direction to a
                    // button / key / mouse click (both controllers, when RE'd).
                    Card {
                        title: "Directional Macros"; Layout.fillWidth: true
                        visible: page.cur.output === 2 && bridge.motionHasDirMacros
                        Repeater {
                            model: [{ n: "Up", i: 0 }, { n: "Down", i: 1 },
                                    { n: "Left", i: 2 }, { n: "Right", i: 3 }]
                            delegate: Row {
                                required property var modelData
                                width: parent.width; spacing: 8
                                Text { text: modelData.n; width: 54; color: Theme.textDim
                                       anchors.verticalCenter: parent.verticalCenter
                                       font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                                PillButton {
                                    label: page.dirLabel(modelData.i)
                                    onClicked: motionPicker.open(modelData.i)
                                }
                                Text {
                                    visible: page.dirLabel(modelData.i) !== "—"
                                    text: "✕"; color: Theme.textDim
                                    anchors.verticalCenter: parent.verticalCenter
                                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                                    TapHandler { onTapped: page.setDir(modelData.i, -1) }
                                }
                            }
                        }
                    }
                    Item { Layout.fillHeight: true }
                }

                Rectangle { Layout.fillHeight: true; Layout.topMargin: 8; Layout.bottomMargin: 8
                            Layout.preferredWidth: 1; color: Theme.cardBorder }

                // ================= right column =================
                ColumnLayout {
                    Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 12
                    Card {
                        title: "Rotation Axis"; Layout.fillWidth: true
                        Text { text: "X-axis output"; color: Theme.textDim
                               font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        Flow {
                            width: parent.width; spacing: 8
                            Repeater {
                                model: bridge.motionXAxisModes
                                delegate: PillButton {
                                    required property string modelData
                                    required property int index
                                    label: modelData
                                    highlight: page.cur.xaxis === index
                                    onClicked: page.setEnum("xaxis", index)
                                }
                            }
                        }
                        Column {
                            width: parent.width; spacing: 8; topPadding: 6
                            Repeater {
                                model: bridge.motionInvertLabels
                                delegate: Row {
                                    required property string modelData
                                    required property int index
                                    width: parent.width
                                    opacity: page.invLive(modelData) ? 1.0 : 0.4
                                    Text { text: modelData; color: Theme.text
                                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                                           anchors.verticalCenter: parent.verticalCenter }
                                    Item { width: parent.width - 190; height: 1 }
                                    ToggleSwitch {
                                        enabled: page.invLive(modelData)
                                        checked: page.cur["invert_" + index] === true
                                        onToggled: page.setInvert(index, checked)
                                    }
                                }
                            }
                        }
                    }

                    Card {
                        title: "Deadzone & Response"; Layout.fillWidth: true
                        Row {
                            width: parent.width
                            Text { text: "Deadzone"; color: Theme.textDim
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                            Item { width: parent.width - 160; height: 1 }
                            Text { text: dzRange.lo + "–" + dzRange.hi + "%"; color: Theme.text
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        }
                        RangeSlider {
                            id: dzRange; width: parent.width; from: 0; to: 100
                            onMoved: { page.apply("dz_min", lo); page.apply("dz_max", hi); dzTimer.restart() }
                        }
                        Row {
                            width: parent.width; topPadding: 4
                            Text { text: "Anti-deadzone"; color: Theme.textDim
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                            Item { width: parent.width - 160; height: 1 }
                            Text { text: adzRange.lo + "–" + adzRange.hi + "%"; color: Theme.text
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        }
                        RangeSlider {
                            id: adzRange; width: parent.width; from: 0; to: 100
                            onMoved: { page.apply("adz_min", lo); page.apply("adz_max", hi); adzTimer.restart() }
                        }
                        Text { text: "Response curve"; color: Theme.textDim; topPadding: 6
                               font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        Flow {
                            width: parent.width; spacing: 8
                            Repeater {
                                model: bridge.motionCurveTypes
                                delegate: PillButton {
                                    required property string modelData
                                    required property int index
                                    label: modelData
                                    highlight: page.cur.curve_type === index
                                    onClicked: page.setCurveType(index)
                                }
                            }
                        }
                        Row {
                            width: parent.width; topPadding: 4
                            visible: page.cur.curve_type === 1 || page.cur.curve_type === 2
                            Text { text: "Curve strength"; color: Theme.textDim
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                            Item { width: parent.width - 130; height: 1 }
                            Text { text: curveIntSlider.value + "%"; color: Theme.text
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        }
                        AccentSlider {
                            id: curveIntSlider; width: parent.width; from: 0; to: 100
                            visible: page.cur.curve_type === 1 || page.cur.curve_type === 2
                            onMoved: page.setCurveStrength(value)
                        }
                    }
                    Item { Layout.fillHeight: true }
                }
            }
        }
    }

    // popout picker for Directional-Macros slots (button / key / mouse)
    TargetPicker {
        id: motionPicker
        current: page.dirEdit >= 0 && page.cur.dir_macros ? page.cur.dir_macros[page.dirEdit] : -1
        function open(i) { page.dirEdit = i; mode = "buttons" }
        onPicked: function (code) { if (page.dirEdit >= 0) page.setDir(page.dirEdit, code) }
    }
}

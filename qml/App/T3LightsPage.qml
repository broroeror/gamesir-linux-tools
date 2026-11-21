import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts
import App 1.0

// Original GameSir Tarantula Pro lighting (SAPJoy protocol, t3pro_gui.py).
// Every change is written to the pad, saved and read back by the bridge, so
// there is no Save bar here. Hue on the wire is 0..255, S/V are 0..100.
Item {
    id: page

    property int curMode: 0
    property int selZone: 0          // index into t3.zones
    property int selLed: -1          // -1 = every LED of the zone
    property var pending: null

    function seed() {
        curMode = t3.lightMode
        briSlider.value = t3.brightness
        spdSlider.value = t3.speed
        seedPicker()
    }
    function zone() { return t3.zones.length > selZone ? t3.zones[selZone] : null }
    // zones list order (t3pro_gui.ZONES): 0 = ABXY, 1 = Home, 2 = Bar, 3 = BAYX (Switch layout)
    function pickFromDrawing(n) {
        var face = ["A", "B", "X", "Y"].indexOf(n)
        if (face >= 0) { selZone = t3.layout === 2 ? 3 : 0; selLed = face }
        else if (n === "HOME") { selZone = 1; selLed = -1 }
        else if (n === "BAR") { selZone = 2; selLed = -1 }
        seedPicker()
    }
    function drawingSel() {
        if ((selZone === 0 || selZone === 3) && selLed >= 0) return ["A", "B", "X", "Y"][selLed]
        return selZone === 1 ? "HOME" : selZone === 2 ? "BAR" : ""
    }
    function seedPicker() {
        var z = zone(); if (!z) return
        var l = z.leds[Math.max(0, selLed)]
        picker.setColor(Qt.hsva(l.h / 255, l.s / 100, Math.max(0.01, l.v / 100), 1))
    }
    Component.onCompleted: seed()
    onVisibleChanged: if (visible) seed()
    Connections {
        target: t3
        function onPresenceChanged() { page.seed() }
        // re-seed from the pad once a read/save lands, unless the user is mid-edit
        function onStateChanged() {
            if (!t3.busy && !lightTimer.running && !colorTimer.running) page.seed()
        }
    }

    Timer {
        id: lightTimer; interval: 250
        onTriggered: t3.setLight(page.curMode, briSlider.value, spdSlider.value)
    }
    Timer {
        id: colorTimer; interval: 250
        onTriggered: if (page.pending) {
            var z = page.zone()
            t3.setLed(z.id, page.selLed, page.pending[0], page.pending[1], page.pending[2])
            page.pending = null
        }
    }

    Text {
        visible: !t3.present
        anchors.centerIn: parent
        width: Math.min(parent.width - 60, 520); wrapMode: Text.WordWrap
        horizontalAlignment: Text.AlignHCenter
        text: qsTranslate("UI", "Tarantula Pro not found. Plug its 2.4 GHz dongle in and switch the pad to XInput mode.")
        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
    }

    FitScroll {
        id: scroller
        visible: t3.present
        anchors.fill: parent
        anchors.margins: 20
        content: fitBox

        Column {
            id: fitBox
            width: scroller.availableWidth
            spacing: Math.max(6, Math.round(14 * Theme.vComp))

            RowLayout {
                width: parent.width; spacing: 20

                ColumnLayout {
                    Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop
                    spacing: 12

                    Card {
                        title: qsTranslate("UI", "Controller"); Layout.fillWidth: true
                        T3ControllerView {
                            width: parent.width; height: width / aspect + topPad
                            showBackHint: false
                            selected: page.drawingSel()
                            pickable: ["A", "B", "X", "Y", "HOME", "BAR"]
                            onPicked: function (n) { page.pickFromDrawing(n) }
                        }
                        Text {
                            width: parent.width; wrapMode: Text.WordWrap
                            text: qsTranslate("UI", "Click A, B, X, Y, HOME or the light bar to change its colour.")
                            color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        }
                        Row {
                            spacing: 6
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: qsTranslate("UI", "Button layout") + "  "
                                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                            }
                            PillButton { label: "Xbox (ABXY)"; highlight: t3.layout !== 2; onClicked: t3.setLayout(1) }
                            PillButton { label: "Switch (BAYX)"; highlight: t3.layout === 2; onClicked: t3.setLayout(2) }
                        }
                        Text {
                            width: parent.width; wrapMode: Text.WordWrap
                            text: qsTranslate("UI", "Each layout keeps its own A/B/X/Y colours: Xbox uses the ABXY zone, Switch uses the BAYX zone. The same layout switch is on the controller (hold the gear button).")
                            color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        }
                        ConfirmButton {
                            label: qsTranslate("UI", "Restore original colours")
                            onConfirmed: t3.restoreDefaultColors()
                        }
                    }

                    Card {
                        title: qsTranslate("UI", "Effect"); Layout.fillWidth: true
                        Flow {
                            width: parent.width; spacing: 8
                            Repeater {
                                model: t3.modeNames
                                delegate: PillButton {
                                    required property string modelData
                                    required property int index
                                    label: qsTranslate("UI", modelData.charAt(0).toUpperCase() + modelData.slice(1))
                                    highlight: page.curMode === index
                                    onClicked: { page.curMode = index; lightTimer.restart() }
                                }
                            }
                        }
                        Text {
                            width: parent.width; wrapMode: Text.WordWrap
                            text: qsTranslate("UI", "The bar shows its own colour only in Solid mode; animated effects draw their own colours there.")
                            color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        }
                        Row {
                            width: parent.width
                            Text { text: qsTranslate("UI", "Brightness"); color: Theme.textDim
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                            Item { width: parent.width - 110; height: 1 }
                            Text { text: briSlider.value + "%"; color: Theme.text
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        }
                        AccentSlider { id: briSlider; width: parent.width; from: 0; to: 100
                                       onMoved: lightTimer.restart() }
                        Row {
                            width: parent.width
                            Text { text: qsTranslate("UI", "Speed"); color: Theme.textDim
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                            Item { width: parent.width - 110; height: 1 }
                            Text { text: spdSlider.value + "%"; color: Theme.text
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        }
                        AccentSlider { id: spdSlider; width: parent.width; from: 0; to: 100
                                       onMoved: lightTimer.restart() }
                    }

                    Card {
                        title: qsTranslate("UI", "Zones"); Layout.fillWidth: true
                        Repeater {
                            model: t3.zones
                            delegate: Row {
                                required property var modelData
                                required property int index
                                width: parent.width; spacing: 10
                                Rectangle {
                                    width: 170; height: 34; radius: 8
                                    color: page.selZone === index ? Theme.accent : (zh.hovered ? Theme.cardHover : Theme.button)
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        anchors.left: parent.left; anchors.leftMargin: 10
                                        text: qsTranslate("UI", modelData.label)
                                        color: page.selZone === index ? Theme.textOnAccent : Theme.text
                                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                                    }
                                    HoverHandler { id: zh }
                                    TapHandler { onTapped: { page.selZone = index; page.selLed = -1; page.seedPicker() } }
                                }
                                Repeater {
                                    model: modelData.leds
                                    delegate: Rectangle {
                                        required property var modelData
                                        required property int index
                                        property int zoneIndex: parent ? parent.index : 0
                                        width: 34; height: 34; radius: 17
                                        color: modelData.hex
                                        border.width: (page.selZone === zoneIndex && (page.selLed === index || page.selLed < 0)) ? 3 : 1
                                        border.color: border.width > 1 ? Theme.accent : Theme.cardBorder
                                        TapHandler {
                                            onTapped: { page.selZone = parent.zoneIndex; page.selLed = index; page.seedPicker() }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop
                    spacing: 12
                    Card {
                        Layout.fillWidth: true
                        title: {
                            var z = page.zone()
                            if (!z) return qsTranslate("UI", "Colour")
                            return qsTranslate("UI", z.label) + " — " + (page.selLed < 0 || z.leds.length === 1
                                ? qsTranslate("UI", "all LEDs") : qsTranslate("UI", "LED %1").arg(page.selLed + 1))
                        }
                        ColorPicker {
                            id: picker; width: parent.width
                            onEdited: function (c) {
                                var h = c.hsvHue >= 0 ? Math.round(c.hsvHue * 255) : 0
                                page.pending = [h, Math.round(c.hsvSaturation * 100), Math.round(c.hsvValue * 100)]
                                colorTimer.restart()
                            }
                        }
                        Text {
                            width: parent.width; wrapMode: Text.WordWrap
                            text: qsTranslate("UI", "Click a zone to colour all its LEDs, or a single dot to colour just that one.")
                            color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        }
                    }
                }
            }
        }
    }
}

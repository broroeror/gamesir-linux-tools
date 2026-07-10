import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts
import App 1.0

// GameSir G7 Pro 8K lighting + device settings (bank 0x20). Not the Cyclone's
// keyframe RGB — a single ring effect + brightness, a 4-quadrant home indicator,
// and power/dock settings. Writes apply immediately via the bridge.
Item {
    id: page

    // Local selection state for the pill groups + the 4 quadrant hues, seeded from
    // the bridge on load and updated on click (bridge props only notify on reload).
    property int curMode: 0
    property int curSleep: 0
    property int curDock: 0
    // Home-ring selection: `sel` holds the selected quadrant indices (multi-select),
    // `primary` is the one whose colour seeds the picker (last interacted). Always
    // keeps at least one selected so the picker has a target.
    property var sel: [0]
    property int primary: 0
    property int pendingHue: 60
    property int pendingSat: 100
    property var quads: [[60, 100], [60, 100], [60, 100], [60, 100]]   // [hue, byte1]

    function seed() {
        curMode = bridge.light8kMode
        curSleep = bridge.light8kSleep
        curDock = bridge.light8kDockMode
        briSlider.value = bridge.light8kBrightness
        dockBri.value = bridge.light8kDockBright
        autoSw.checked = bridge.light8kAuto
        quads = bridge.light8kQuads
        seedPicker()
    }
    Component.onCompleted: seed()
    Connections { target: bridge; function onLight8kLoaded() { page.seed() } }
    onVisibleChanged: if (visible) seed()

    // hue byte = hue in DEGREES (0..255), so the ring tops out around violet and
    // can't reach magenta/pink (>255deg). Display with /360 so the app matches the
    // physical ring. byte1 is saturation; brightness is the global slider.
    function quadColor(q) { return Qt.hsva(Math.min(1, q[0] / 360), q[1] / 100, 1, 1) }
    function seedPicker() { quadPicker.setColor(quadColor(quads[primary])) }
    function isSel(i) { return sel.indexOf(i) >= 0 }
    // click toggles a quadrant in/out of the selection (keeping at least one).
    function toggleQuad(i) {
        var s = sel.slice(); var at = s.indexOf(i)
        if (at >= 0) { if (s.length > 1) s.splice(at, 1) }
        else s.push(i)
        sel = s
        primary = (sel.indexOf(i) >= 0) ? i : sel[0]
        seedPicker()
    }
    // 0xFF (255) is a glitch/sentinel on the ring (renders magenta) — the official
    // app never wrote above 246 (=blue). Cap there so hue stays in verified range.
    readonly property int hueByteMax: 246
    // apply the picked colour to ALL selected quadrants: update the ring preview
    // immediately, and debounce the (paced) device write so a drag doesn't flood.
    function applyQuad(c) {
        var hue = c.hsvHue >= 0 ? Math.min(hueByteMax, Math.round(c.hsvHue * 360))
                                : quads[primary][0]
        var sat = Math.round(c.hsvSaturation * 100)
        var q = quads.slice()
        for (var k = 0; k < sel.length; k++) q[sel[k]] = [hue, sat]
        quads = q
        pendingHue = hue; pendingSat = sat
        writeTimer.restart()
    }
    Timer {
        id: writeTimer; interval: 40
        onTriggered: bridge.setLight8kQuads(page.sel, page.pendingHue, page.pendingSat)
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

            RowLayout {
                width: parent.width; spacing: 20

                // ================= left: controller light =================
                ColumnLayout {
                    Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 12

                    Card {
                        title: "Controller Light"; Layout.fillWidth: true
                        Flow {
                            width: parent.width; spacing: 8
                            Repeater {
                                model: bridge.light8kModes
                                delegate: PillButton {
                                    required property string modelData
                                    required property int index
                                    label: modelData
                                    highlight: page.curMode === index
                                    onClicked: { page.curMode = index; bridge.setLight8kMode(index) }
                                }
                            }
                        }
                        Row {
                            width: parent.width
                            Text { text: "Brightness"; color: Theme.textDim
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                            Item { width: parent.width - 110; height: 1 }
                            Text { text: briSlider.value + "%"; color: Theme.text
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        }
                        AccentSlider {
                            id: briSlider; width: parent.width; from: 0; to: 100
                            onMoved: bridge.setLight8kBrightness(value)
                        }
                    }

                    Card {
                        title: "Home Indicator"; Layout.fillWidth: true
                        Row {
                            width: parent.width; spacing: 14
                            // ring preview doubles as the quadrant selector: click a
                            // wedge to edit that quadrant's colour with the picker.
                            Column {
                                spacing: 10; width: 104
                                Canvas {
                                    id: ring; width: 104; height: 104
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    // quadrant index -> [startAngle, endAngle] so 1=top-left,
                                    // 2=top-right, 3=bottom-left, 4=bottom-right (matches the
                                    // register order written to the controller).
                                    readonly property var arcs: [
                                        [Math.PI, 1.5 * Math.PI],       // 1 TL
                                        [1.5 * Math.PI, 2 * Math.PI],   // 2 TR
                                        [0.5 * Math.PI, Math.PI],       // 3 BL
                                        [0, 0.5 * Math.PI]              // 4 BR
                                    ]
                                    property var q: page.quads
                                    property var selRef: page.sel
                                    onQChanged: requestPaint()
                                    onSelRefChanged: requestPaint()
                                    onPaint: {
                                        var ctx = getContext('2d'); ctx.clearRect(0, 0, width, height)
                                        var cx = width / 2, cy = height / 2, ro = width / 2 - 4, ri = ro * 0.52
                                        function wedge(i) {
                                            var a0 = arcs[i][0], a1 = arcs[i][1]
                                            ctx.beginPath(); ctx.arc(cx, cy, ro, a0, a1)
                                            ctx.arc(cx, cy, ri, a1, a0, true); ctx.closePath()
                                        }
                                        for (var i = 0; i < 4; i++) {
                                            wedge(i); ctx.fillStyle = page.quadColor(page.quads[i]); ctx.fill()
                                        }
                                        // selected wedges: a drop shadow lifts them off the ring and a
                                        // bright inner glow rims them — visible on ANY theme/colour combo,
                                        // unlike the old thin accent outline.
                                        for (var i = 0; i < 4; i++) {
                                            if (page.sel.indexOf(i) < 0) continue
                                            ctx.save()
                                            ctx.shadowColor = 'rgba(0,0,0,0.6)'; ctx.shadowBlur = 8
                                            ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 2
                                            wedge(i); ctx.fillStyle = page.quadColor(page.quads[i]); ctx.fill()
                                            ctx.restore()
                                            ctx.save()
                                            wedge(i); ctx.clip()
                                            ctx.shadowColor = 'rgba(255,255,255,0.95)'; ctx.shadowBlur = 11
                                            ctx.lineWidth = 3; ctx.strokeStyle = 'rgba(255,255,255,0.9)'
                                            wedge(i); ctx.stroke()
                                            ctx.restore()
                                        }
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        onClicked: (m) => {
                                            var dx = m.x - width / 2, dy = m.y - height / 2
                                            // TL=0 TR=1 BL=2 BR=3 — toggles in/out of the selection
                                            page.toggleQuad((dy < 0 ? 0 : 2) + (dx < 0 ? 0 : 1))
                                        }
                                    }
                                }
                                Text {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    width: 104; horizontalAlignment: Text.AlignHCenter
                                    wrapMode: Text.WordWrap
                                    text: page.sel.length === 1
                                          ? ("Quadrant " + (page.sel[0] + 1))
                                          : ("Quadrants " + page.sel.slice().sort().map(function (i) { return i + 1 }).join(", "))
                                    color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                                }
                                Text {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    width: 104; horizontalAlignment: Text.AlignHCenter
                                    wrapMode: Text.WordWrap
                                    text: "Click wedges to select — pick several to edit together"
                                    color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS - 1
                                }
                            }
                            ColorPicker {
                                id: quadPicker
                                width: Math.min(190, parent.width - 110)
                                hueMax: page.hueByteMax / 360   // cap at blue (246); 0xFF glitches to magenta
                                anchors.verticalCenter: parent.verticalCenter
                                onEdited: page.applyQuad(c)
                            }
                        }
                    }
                    Item { Layout.fillHeight: true }
                }

                Rectangle { Layout.fillHeight: true; Layout.topMargin: 8; Layout.bottomMargin: 8
                            Layout.preferredWidth: 1; color: Theme.cardBorder }

                // ================= right: device settings =================
                ColumnLayout {
                    Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 12

                    Card {
                        title: "Power"; Layout.fillWidth: true
                        Row {
                            width: parent.width
                            Text { text: "Auto power on/off"; color: Theme.text
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                                   anchors.verticalCenter: parent.verticalCenter }
                            Item { width: parent.width - 190; height: 1 }
                            ToggleSwitch { id: autoSw; onToggled: bridge.setLight8kAuto(autoSw.checked) }
                        }
                        Text { text: "Sleep timer"; color: Theme.textDim
                               font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        Flow {
                            width: parent.width; spacing: 8
                            Repeater {
                                model: bridge.light8kSleepOptions
                                delegate: PillButton {
                                    required property string modelData
                                    required property int index
                                    label: modelData
                                    highlight: page.curSleep === index
                                    onClicked: { page.curSleep = index; bridge.setLight8kSleep(index) }
                                }
                            }
                        }
                    }

                    Card {
                        title: "Dock LED"; Layout.fillWidth: true
                        Flow {
                            width: parent.width; spacing: 8
                            Repeater {
                                model: bridge.light8kDockModes
                                delegate: PillButton {
                                    required property string modelData
                                    required property int index
                                    label: modelData
                                    highlight: page.curDock === index
                                    onClicked: { page.curDock = index; bridge.setLight8kDockMode(index) }
                                }
                            }
                        }
                        Row {
                            width: parent.width
                            Text { text: "Brightness"; color: Theme.textDim
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                            Item { width: parent.width - 110; height: 1 }
                            Text { text: dockBri.value + "%"; color: Theme.text
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        }
                        AccentSlider {
                            id: dockBri; width: parent.width; from: 0; to: 100
                            onMoved: bridge.setLight8kDockBright(value)
                        }
                    }
                    Item { Layout.fillHeight: true }
                }
            }
        }
    }
}

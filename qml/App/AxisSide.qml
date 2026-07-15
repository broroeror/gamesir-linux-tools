import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts

// One analog side's full config: a controls column (deadzone / anti-deadzone /
// curve presets / trajectory / reset) plus a visual column (curve graph + live
// view). Keyed on `side` ('st'/'rs' or 'lt'/'rt'); `isStick` swaps the
// type-specific control + visualiser. `mirror` reverses the two columns so the
// RIGHT side's controls sit on the outer (right) edge and its graph pulls toward
// the centre — set it only on the right instance. All edits stage via the
// bridge's pending-config queue and land on Save.
Item {
    id: root
    property string side
    property string title
    property bool isStick: true
    property bool mirror: false
    property int curveType: 0          // 0..2 preset, 3 custom
    property int intensity: 100         // preset strength: 100 standard, 0 inverse, 50 linear
    property int typeIdx: 0            // trajectory or hair-mode index

    // The square graph is sized by WIDTH (height==width), so a short+wide window
    // would blow it up past what fits and push the card off-screen. Let the two
    // visualisers shrink with the page's compression (Theme.vComp) too — with a
    // gentle floor so they stay legible — so FitScroll can actually make them fit.
    readonly property real lvScale: Math.max(0.62, Theme.vComp)

    // Header formatting for deadzone values: one decimal on a 0.1-step model (the
    // 8K's 16-bit deadzones), whole percent otherwise.
    function fmtDz(v) { return bridge.deadzoneStep < 1 ? v.toFixed(1) : Math.round(v).toString() }

    // Warp a preset's standard points to an intensity, mirroring gamesir_config
    // .warp_points so the graph updates live as the slider drags (blend between
    // the preset points P and their y=x reflection).
    function warp(P, inten) {
        var f = Math.max(0, Math.min(100, inten)) / 100.0
        var out = []
        for (var i = 0; i < P.length; i++) {
            var x = P[i][0], y = P[i][1]
            out.push([Math.round(x * f + y * (1 - f)), Math.round(y * f + x * (1 - f))])
        }
        return out
    }
    // Raw trajectory stretches the (circular) physical stick range out to a
    // square so the diagonals reach the corners (x/y absolute max). The 0x12
    // report is the circular physical reading, so we apply that stretch to the
    // live dot when Raw is selected. `a` is the axis to map, `other` its partner.
    // Map a raw input magnitude (0..1) through the configured deadzone + response
    // curve to the OUTPUT magnitude the game actually receives — so the live
    // preview reflects the curve/deadzone instead of the raw physical position
    // (the vendor 0x12 report is always raw; the shaping happens downstream).
    function respMag(im) {
        var lo = dz.lo / 100
        var hi = Math.max(lo + 0.001, dz.hi / 100)
        if (im <= lo) return 0
        var t = Math.max(0, Math.min(1, (im - lo) / (hi - lo)))
        var c = curve.sampleFrac(t)
        if (c <= 0) return 0
        var floor = adz.lo / 100                    // anti-deadzone lifts the floor
        return Math.min(1, floor + c * (1 - floor))
    }

    function rawMap(a, other) {
        if (root.typeIdx !== 1) return a           // Circle: leave as-is
        var m = Math.max(Math.abs(a), Math.abs(other))
        if (m < 0.0001) return a
        return Math.max(-1, Math.min(1, a * Math.sqrt(a * a + other * other) / m))
    }

    // Live-apply the current preset at a new intensity (graph + queued write).
    function applyIntensity(inten) {
        intensity = inten
        var name = bridge.curveNames[curveType]      // curveType is 1 or 2 here
        curve.setPoints(warp(bridge.curvePresets[name], inten))
        bridge.setCurveIntensity(side, name, inten)
    }

    // Follow the content size so the hosting ScrollView can scroll when short.
    implicitWidth: lay.implicitWidth
    implicitHeight: lay.implicitHeight

    // True once we've applied a real (non-empty) config, so we don't leave the
    // sliders sitting at their placeholder 0/100 (which reads as a collapsed
    // deadzone and lets a stray click land a random value).
    property bool seeded: false
    function seed() {
        var c = bridge.config
        // A controller switch fires configLoaded with an EMPTY config before the
        // real read lands; ignore those so we keep showing the last good values
        // and re-apply once the real config arrives.
        if (!bridge.profile || c[side + "_dz_min"] === undefined) return
        dz.lo = c[side + "_dz_min"]; dz.hi = c[side + "_dz_max"]
        adz.lo = c[side + "_adz_min"]; adz.hi = c[side + "_adz_max"]
        var cv = c[side + "_curve"]
        curveType = cv ? cv.type : 0
        intensity = (cv && cv.intensity !== undefined) ? cv.intensity : 100
        intenSlider.value = intensity
        curve.setPoints(cv && cv.points ? cv.points : [[40, 41], [128, 128], [215, 214]])
        typeIdx = isStick ? c[side + "_traj"] : c[side + "_hair"]
        seeded = true
    }
    Component.onCompleted: seed()
    Connections { target: bridge; function onConfigLoaded() { root.seed() } }
    // Re-seed when the page becomes visible: if config finished loading while this
    // tab was hidden, onConfigLoaded already fired and the initial seed missed it.
    onVisibleChanged: if (visible && !seeded) seed()

    function presetClicked(name) {
        curveType = bridge.curveNames.indexOf(name)
        intensity = 100
        intenSlider.value = 100
        curve.setPoints(warp(bridge.curvePresets[name], 100))
        bridge.setCurveIntensity(side, name, 100)
    }

    // One-click recovery if a profile gets into a bad state (e.g. a collapsed
    // deadzone bricked the stick).
    function resetDefaults() {
        var dzMin = 5, dzMax = isStick ? 100 : 95
        dz.lo = dzMin; dz.hi = dzMax; adz.lo = 0; adz.hi = 100
        bridge.setScalar(side + "_dz_min", dzMin); bridge.setScalar(side + "_dz_max", dzMax)
        bridge.setScalar(side + "_adz_min", 0); bridge.setScalar(side + "_adz_max", 100)
        curveType = 0; curve.setPoints(bridge.curvePresets["Linear"])
        bridge.setCurve(side, "Linear", [])
        typeIdx = 0
        if (isStick) bridge.setTraj(side, 0); else bridge.setHair(side, 0)
    }

    RowLayout {
        id: lay
        anchors.fill: parent
        spacing: 14
        // Reverse only THIS row's column order for the right half; children don't
        // inherit the mirroring, so sliders / text inside stay normal.
        LayoutMirroring.enabled: root.mirror
        LayoutMirroring.childrenInherit: false

        // ================= controls column (outer edge) =================
        ColumnLayout {
            Layout.fillWidth: true
            Layout.minimumWidth: 200; Layout.preferredWidth: 240; Layout.maximumWidth: 300
            Layout.fillHeight: true
            spacing: Math.max(6, Math.round(12 * Theme.vComp))   // card-stack gap compresses

            // Header row (fixed height so the visual column's Reset button can sit
            // at the same level and the graph still lines up with Deadzone). The
            // RIGHT side right-justifies its title so it hugs the outer edge.
            Item {
                Layout.fillWidth: true; Layout.preferredHeight: 34
                Text {
                    text: root.title; color: Theme.text
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: root.mirror ? undefined : parent.left
                    anchors.right: root.mirror ? parent.right : undefined
                    horizontalAlignment: root.mirror ? Text.AlignRight : Text.AlignLeft
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontL; font.bold: true
                }
            }

            Card {
                title: "Deadzone"; Layout.fillWidth: true
                headerValue: root.fmtDz(dz.lo) + "–" + root.fmtDz(dz.hi); spacing: 8
                RangeSlider {
                    id: dz; width: parent.width; from: 0; to: 100; lo: 0; hi: 100
                    step: bridge.deadzoneStep
                    onMoved: { bridge.setScalar(root.side + "_dz_min", lo)
                               bridge.setScalar(root.side + "_dz_max", hi) }
                }
            }

            Card {
                title: "Anti-Deadzone"; Layout.fillWidth: true
                headerValue: root.fmtDz(adz.lo) + "–" + root.fmtDz(adz.hi); spacing: 8
                RangeSlider {
                    id: adz; width: parent.width; from: 0; to: 100; lo: 0; hi: 100
                    step: bridge.deadzoneStep
                    onMoved: { bridge.setScalar(root.side + "_adz_min", lo)
                               bridge.setScalar(root.side + "_adz_max", hi) }
                }
            }

            Card {
                title: "Curve Adjustment"; Layout.fillWidth: true
                Flow {
                    width: parent.width; spacing: 8
                    Repeater {
                        model: bridge.curveNames
                        delegate: PillButton {
                            required property string modelData
                            required property int index
                            label: modelData
                            highlight: root.curveType === index
                            onClicked: root.presetClicked(modelData)
                        }
                    }
                    PillButton {
                        label: "Custom"; highlight: root.curveType === 3
                        onClicked: { root.curveType = 3
                                     bridge.setCurve(root.side, "Custom", curve.points) }
                    }
                }
                // Intensity: only meaningful for the shaped presets (Concave/
                // S-curve). 100 = standard, 50 = linear, 0 = inverse.
                Column {
                    width: parent.width; spacing: 6; topPadding: 6
                    visible: root.curveType === 1 || root.curveType === 2
                    Row {
                        width: parent.width
                        Text { text: "Intensity"; color: Theme.textDim
                               font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        Item { width: parent.width - 90; height: 1 }
                        Text { text: root.intensity + "%"; color: Theme.text
                               font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                    }
                    AccentSlider {
                        id: intenSlider
                        width: parent.width; from: 0; to: 100; value: 100
                        onMoved: root.applyIntensity(Math.round(value))
                    }
                }
            }

            Card {
                title: root.isStick ? "Stick Trajectory" : "Hair Trigger Mode"
                Layout.fillWidth: true
                Flow {
                    width: parent.width; spacing: 8
                    Repeater {
                        model: root.isStick ? ["Circle", "Raw"] : bridge.hairModes
                        delegate: PillButton {
                            required property string modelData
                            required property int index
                            label: modelData
                            highlight: root.typeIdx === index
                            onClicked: {
                                root.typeIdx = index
                                if (root.isStick) bridge.setTraj(root.side, index)
                                else bridge.setHair(root.side, index)
                            }
                        }
                    }
                }
            }

            Item { Layout.fillHeight: true }
        }

        // ================= visual column (toward centre) =================
        ColumnLayout {
            Layout.fillWidth: true
            Layout.minimumWidth: 170; Layout.preferredWidth: 230; Layout.maximumWidth: 300
            Layout.fillHeight: true
            spacing: Math.max(6, Math.round(12 * Theme.vComp))   // card-stack gap compresses

            // The controls column's title has a twin (invisible) header row on the
            // controls side; here we put the "Reset to defaults" button in that same
            // top-centre slot, so the graph still lines up with the Deadzone card.
            Item {
                Layout.fillWidth: true; Layout.preferredHeight: 34
                PillButton {
                    anchors.centerIn: parent
                    width: Math.min(parent.width, 220)
                    label: "Reset to defaults"
                    onClicked: root.resetDefaults()
                }
            }

            Card {
                id: graphCard
                title: "Response Curve"; Layout.fillWidth: true
                Row {
                    width: parent.width; spacing: 6
                    // Y axis label — "Output" runs vertically up the left edge.
                    Item {
                        width: 14; height: curve.height
                        anchors.verticalCenter: undefined
                        Text {
                            text: "Output"; color: Theme.textFaint
                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                            rotation: -90; anchors.centerIn: parent
                        }
                    }
                    Column {
                        spacing: 4
                        CurveEditor {
                            id: curve
                            width: Math.max(120, Math.min(Math.round(230 * root.lvScale), graphCard.width - 64)); height: width
                            // Draggable points only in Custom mode; the Linear/
                            // Concave/S-curve presets show just the smooth curve
                            // (dots on a preset read as editable when they aren't).
                            interactive: root.curveType === 3
                            curveKind: root.curveType
                            intensity: root.intensity
                            onEdited: { root.curveType = 3; bridge.setCurve(root.side, "Custom", pts) }
                        }
                        // X axis label — "Input" runs along the bottom.
                        Text {
                            text: "Input"; color: Theme.textFaint
                            width: curve.width; horizontalAlignment: Text.AlignHCenter
                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        }
                    }
                }
            }

            Card {
                title: "Live"; Layout.fillWidth: true

                // Stick visualiser — compact, centred.
                Item {
                    visible: root.isStick
                    width: parent.width; height: visible ? Math.round(116 * root.lvScale) : 0
                    property real ax: root.side === "st" ? bridge.leftStickX : bridge.rightStickX
                    property real ay: root.side === "st" ? bridge.leftStickY : bridge.rightStickY
                    Rectangle {
                        anchors.centerIn: parent
                        width: Math.min(parent.width - 8, Math.round(106 * root.lvScale)); height: width
                        // Circle trajectory = round gate; Raw = square-ish gate with
                        // softly rounded corners. The dot (below) does the real work
                        // of showing Raw's corner-reaching motion.
                        radius: root.typeIdx === 0 ? width / 2 : width * 0.10
                        Behavior on radius { NumberAnimation { duration: 200; easing.type: Easing.InOutQuad } }
                        color: Theme.bg
                        border.color: Theme.cardBorder; border.width: 2
                        Rectangle {       // deadzone ring (matches the gate shape)
                            anchors.centerIn: parent
                            width: parent.width * (dz.lo / 100); height: width
                            radius: root.typeIdx === 0 ? width / 2 : width * 0.10
                            Behavior on radius { NumberAnimation { duration: 200; easing.type: Easing.InOutQuad } }
                            color: "transparent"
                            border.color: Theme.accentDim; border.width: 1
                        }
                        Rectangle {       // live position: raw direction, but the
                            // magnitude is shaped by the deadzone + response curve
                            // so you can SEE the curve working (dot lags/leads the
                            // stick, sits still inside the deadzone, etc.).
                            property real ix: root.rawMap(parent.parent.ax, parent.parent.ay)
                            property real iy: root.rawMap(parent.parent.ay, parent.parent.ax)
                            property real im: Math.min(1, Math.hypot(ix, iy))
                            // list curve/deadzone deps so it recomputes live when
                            // they change (not only when the stick moves).
                            property real sc: (curve.points, curve.curveKind, curve.intensity,
                                               dz.lo, dz.hi, adz.lo,
                                               im > 0.0001 ? root.respMag(im) / im : 0)
                            width: 12; height: 12; radius: 6; color: Theme.accent
                            x: parent.width / 2 - 6 + ix * sc * (parent.width / 2 - 7)
                            y: parent.height / 2 - 6 + iy * sc * (parent.height / 2 - 7)
                        }
                    }
                }

                // Trigger visualiser — a horizontal fill bar (the trigger pulls in
                // one axis, so a wide short bar reads better than a tall thin one).
                Item {
                    visible: !root.isStick
                    width: parent.width; height: visible ? 26 : 0
                    property real v: root.side === "lt" ? bridge.leftTrigger : bridge.rightTrigger
                    Rectangle {
                        anchors.fill: parent; radius: height / 2
                        color: Theme.bg; border.color: Theme.cardBorder; border.width: 2
                        Rectangle {
                            anchors.left: parent.left; anchors.leftMargin: 2
                            anchors.verticalCenter: parent.verticalCenter
                            // fill reflects the deadzone + response curve applied
                            // to the raw pull, so the curve is visible here too.
                            width: (parent.width - 4) * (curve.points, curve.curveKind,
                                     curve.intensity, dz.lo, dz.hi, adz.lo,
                                     root.respMag(parent.parent.v))
                            height: parent.height - 4; radius: height / 2
                            color: Theme.accent
                        }
                    }
                }

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: root.isStick
                          ? ("X " + Math.round((root.side === "st" ? bridge.leftStickX : bridge.rightStickX) * 100)
                             + "%   Y " + Math.round((root.side === "st" ? bridge.leftStickY : bridge.rightStickY) * 100) + "%")
                          : (Math.round((root.side === "lt" ? bridge.leftTrigger : bridge.rightTrigger) * 100) + "%")
                    color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
            }
            Item { Layout.fillHeight: true }
        }
    }
}

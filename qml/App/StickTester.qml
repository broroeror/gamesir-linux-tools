import QtQuick
import QtQuick.Layouts

Window {
    id: tester
    title: "Stick test"
    width: 720; height: 600
    minimumWidth: 640; minimumHeight: 600
    color: Theme.bg
    property string phase: ""
    property real deadline: 0
    property int remaining: 5
    property bool measured: false
    property bool travelled: false
    property string message: "Leave both sticks untouched to measure rest, or test their full travel."
    property var readings: [fresh(), fresh()]
    readonly property var axes: [bridge.leftStickX, bridge.leftStickY,
                                 bridge.rightStickX, bridge.rightStickY]
    readonly property bool available: bridge.connected && bridge.modeOk
                                     && (!bridge.hasConfigSession || bridge.configClaimed)
    readonly property string source: bridge.selectedController + ":" + bridge.activeProfile + ":" + bridge.profile
    onSourceChanged: reset()
    onAvailableChanged: reset()
    onActiveChanged: if (!active && phase) cancel()
    onVisibleChanged: if (!visible && phase) cancel()
    Connections { target: bridge; function onConfigLoaded() { tester.reset() } }

    function fresh() {
        return {n: 0, x: 0, y: 0, m2: 0, peak: 0,
                minX: 0, maxX: 0, minY: 0, maxY: 0, trace: []}
    }
    function reset() {
        phase = ""; measured = false; travelled = false
        readings = [fresh(), fresh()]
        message = "Leave both sticks untouched to measure rest, or test their full travel."
    }
    function cancel() {
        if (phase === "rest") measured = false
        phase = ""
        message = "Test stopped. Keep this window focused while measuring."
    }
    function start(kind) {
        if (!available) return
        measured = false
        if (kind === "travel") { readings = [fresh(), fresh()]; travelled = true }
        else {
            readings = readings.map(function(s) {
                return Object.assign({}, s, {n: 0, x: 0, y: 0, m2: 0, peak: 0})
            })
            deadline = Date.now() + 5000; remaining = 5
        }
        phase = kind
        message = kind === "rest" ? "Release both sticks and leave them untouched for 5 seconds."
                                 : "Rotate both sticks around the edges, then release them and measure return."
    }
    function sample() {
        if (!available || !phase) return
        var next = readings.slice()
        for (var i = 0; i < 2; i++) {
            var x = Math.max(-1, Math.min(1, axes[i * 2]))
            var y = Math.max(-1, Math.min(1, axes[i * 2 + 1]))
            var s = Object.assign({}, next[i])
            if (phase === "rest") {
                s.n++
                var dx = x - s.x, dy = y - s.y
                s.x += dx / s.n; s.y += dy / s.n
                s.m2 += dx * (x - s.x) + dy * (y - s.y)
                s.peak = Math.max(s.peak, Math.hypot(x, y))
            } else {
                if (!s.trace.length) { s.minX = s.maxX = x; s.minY = s.maxY = y }
                s.minX = Math.min(s.minX, x); s.maxX = Math.max(s.maxX, x)
                s.minY = Math.min(s.minY, y); s.maxY = Math.max(s.maxY, y)
                s.trace = s.trace.slice(-511).concat([[x, y]])
            }
            next[i] = s
        }
        readings = next
        remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000))
        if (phase === "rest" && Date.now() >= deadline) {
            measured = readings.every(function(s) { return s.n >= 30 })
            phase = ""
            message = measured ? "Rest / return measurement complete. Results are suggestions; settings are unchanged."
                               : "Not enough samples. Repeat the rest measurement."
        }
    }
    Timer {
        interval: 20; repeat: true
        running: tester.visible && tester.active && tester.available && tester.phase !== ""
        onTriggered: tester.sample()
    }

    ColumnLayout {
        anchors.fill: parent; anchors.margins: 20; spacing: 14
        Text {
            Layout.fillWidth: true; wrapMode: Text.WordWrap
            text: tester.available ? tester.message + (tester.phase === "rest" ? " (" + tester.remaining + " s)" : "") : "Connect the controller and enable configuration if required."
            color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
        }
        Flow {
            Layout.fillWidth: true; spacing: 8
            PillButton {
                label: tester.phase === "travel" ? "Measure return · 5 s" : "Measure rest · 5 s"
                enabled: tester.available && tester.phase !== "rest"
                onClicked: tester.start("rest")
            }
            PillButton {
                label: "Test travel"; enabled: tester.available && !tester.phase
                onClicked: tester.start("travel")
            }
            PillButton { label: "Reset"; onClicked: tester.reset() }
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 16
            Repeater {
                model: ["Left stick", "Right stick"]
                delegate: Card {
                    id: result
                    required property int index
                    required property string modelData
                    readonly property var stats: tester.readings[index]
                    title: modelData; Layout.fillWidth: true; Layout.preferredWidth: 1
                    Canvas {
                        id: plot
                        width: Math.min(parent.width, 180); height: width
                        anchors.horizontalCenter: parent.horizontalCenter
                        onPaint: {
                            var ctx = getContext("2d"), c = width / 2, r = c - 8
                            ctx.reset(); ctx.strokeStyle = Theme.cardBorder; ctx.lineWidth = 1
                            ctx.beginPath(); ctx.arc(c, c, r, 0, Math.PI * 2); ctx.stroke()
                            ctx.beginPath(); ctx.moveTo(c, 4); ctx.lineTo(c, height - 4)
                            ctx.moveTo(4, c); ctx.lineTo(width - 4, c); ctx.stroke()
                            var path = result.stats.trace
                            ctx.strokeStyle = Theme.accentDim; ctx.beginPath()
                            for (var i = 0; i < path.length; i++) {
                                var px = c + path[i][0] * r, py = c + path[i][1] * r
                                if (!i) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                            }
                            ctx.stroke(); ctx.fillStyle = Theme.accent; ctx.beginPath()
                            ctx.arc(c + tester.axes[result.index * 2] * r,
                                    c + tester.axes[result.index * 2 + 1] * r, 4, 0, Math.PI * 2)
                            ctx.fill()
                        }
                        Connections { target: bridge; enabled: tester.visible; function onInputChanged() { plot.requestPaint() } }
                        Connections { target: tester; function onReadingsChanged() { plot.requestPaint() } }
                    }
                    Text {
                        width: parent.width; wrapMode: Text.WordWrap
                        text: tester.measured
                              ? "Center offset: " + (Math.hypot(result.stats.x, result.stats.y) * 100).toFixed(1) + "%\n"
                                + "Noise (RMS): " + (Math.sqrt(Math.max(0, result.stats.m2 / result.stats.n)) * 100).toFixed(1) + "%\n"
                                + "Peak at rest: " + (result.stats.peak * 100).toFixed(1) + "%\n"
                                + (result.stats.peak > 0.2 ? "Stick moved? Repeat at rest."
                                   : "Suggested deadzone: " + Math.ceil(result.stats.peak * 100 + 1) + "%")
                              : "Rest / return: not measured"
                        color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                    }
                    Text {
                        width: parent.width; wrapMode: Text.WordWrap
                        text: tester.travelled
                              ? "Travel X: " + Math.round(result.stats.minX * 100) + " to " + Math.round(result.stats.maxX * 100) + "%\n"
                                + "Travel Y: " + Math.round(result.stats.minY * 100) + " to " + Math.round(result.stats.maxY * 100) + "%"
                              : "Travel: not measured"
                        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                    }
                }
            }
        }
        Item { Layout.fillHeight: true }
        Text {
            Layout.fillWidth: true; wrapMode: Text.WordWrap
            text: "Measures reported input. Firmware deadzones and curves can hide drift; this does not calibrate the controller."
            color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
        }
    }
}

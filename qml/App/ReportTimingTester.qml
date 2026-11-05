import QtQuick
import QtQuick.Layouts

Window {
    id: tester
    title: "Game-input timing"
    width: 650; height: 580
    minimumWidth: 600; minimumHeight: 550
    color: Theme.bg
    property var results: ({})
    readonly property bool claimed: bridge.hasConfigSession && bridge.configClaimed
    function refresh() { results = bridge.reportTimingSnapshot() }
    onActiveChanged: if (!active) bridge.stopReportTiming()
    onVisibleChanged: {
        if (visible) refresh()
        else bridge.stopReportTiming()
    }
    Component.onDestruction: bridge.stopReportTiming()
    Timer { interval: 100; repeat: true; running: tester.visible; onTriggered: tester.refresh() }
    onResultsChanged: if (plot) plot.requestPaint()

    ColumnLayout {
        anchors.fill: parent; anchors.margins: 20; spacing: 14
        Text {
            Layout.fillWidth: true; wrapMode: Text.WordWrap
            text: tester.claimed
                  ? "Release the controller to game input, then start. Rotate a stick continuously for 10 seconds."
                  : "Rotate a stick continuously for 10 seconds. This measures input-update spacing, not physical button latency."
            color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
        }
        Flow {
            Layout.fillWidth: true; spacing: 8
            PillButton {
                visible: tester.claimed
                label: "Release to game input"; enabled: !tester.results.running
                onClicked: bridge.setConfigClaimed(false)
            }
            PillButton {
                label: "Start · 10 s"
                enabled: bridge.connected && !bridge.demoMode && !tester.claimed && !tester.results.running
                onClicked: { bridge.startReportTiming(); tester.refresh() }
            }
            PillButton {
                label: "Stop"; enabled: tester.results.running === true
                onClicked: { bridge.stopReportTiming(); tester.refresh() }
            }
        }
        Text {
            Layout.fillWidth: true; wrapMode: Text.WordWrap
            text: (tester.results.message || "Ready.")
                  + (tester.results.running ? "  " + (tester.results.elapsed || 0).toFixed(1) + " / 10 s" : "")
            color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
        }
        Rectangle {
            Layout.fillWidth: true; height: 6; radius: 3; color: Theme.track
            Rectangle {
                width: parent.width * Math.min(1, (tester.results.elapsed || 0) / 10)
                height: parent.height; radius: 3; color: Theme.accent
            }
        }
        Card {
            title: "Observed game-input updates"; Layout.fillWidth: true
            Text {
                text: tester.results.hz === undefined ? "— Hz" : tester.results.hz.toFixed(1) + " Hz"
                color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontL * 2
            }
            GridLayout {
                width: parent.width; columns: 3; columnSpacing: 24; rowSpacing: 8
                Repeater {
                    model: [{label: "Median", key: "median"}, {label: "p95", key: "p95"},
                            {label: "Maximum", key: "maximum"}, {label: "Minimum", key: "minimum"},
                            {label: "Jitter (std dev)", key: "jitter"}]
                    delegate: Text {
                        required property var modelData
                        text: modelData.label + ": " + (tester.results[modelData.key] === undefined ? "—"
                              : tester.results[modelData.key].toFixed(3) + " ms")
                        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                    }
                }
            }
            Text {
                width: parent.width; wrapMode: Text.WordWrap
                text: (tester.results.source || "Source: Linux game input (evdev)")
                      + " · " + (tester.results.samples || 0) + " updates"
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
            }
        }
        Text {
            text: "Interval peaks · grouped samples · 0–" + Math.max(1, tester.results.maximum || 0).toFixed(3) + " ms"
            color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
        }
        Canvas {
            id: plot
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 80
            onPaint: {
                var ctx = getContext("2d"), points = tester.results.trace || []
                ctx.reset(); ctx.fillStyle = Theme.card; ctx.fillRect(0, 0, width, height)
                if (!points.length) return
                var scale = Math.max(1, tester.results.maximum || 0)
                ctx.fillStyle = Theme.accent
                for (var i = 0; i < points.length; i++) {
                    var h = Math.max(1, (height - 8) * points[i] / scale)
                    ctx.fillRect(i * width / points.length, height - h,
                                 Math.max(1, width / points.length - 1), h)
                }
            }
        }
        Text {
            Layout.fillWidth: true; wrapMode: Text.WordWrap
            text: "Unchanged input may be omitted by the driver. Results include this PC's input stack and are not a USB polling-rate or end-to-end latency measurement."
            color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
        }
    }
}

import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts
import App 1.0

// G502 X sensor page: the five DPI stages (each snapped to the sensor's step),
// which stage is Active vs Sniper, and the report rate. Everything stages into the
// SAME queue as the Buttons tab, so DPI + button edits apply together in one write.
// Configuring distinct stages here is what makes the DPI Up / DPI Down buttons
// (assignable on the Buttons tab) actually step through resolutions.
Item {
    id: page

    // shown value = staged (unsaved) if present, else the value read from the device
    function dpiVal(i) {
        var s = mouse.pendingSensor["dpi:" + i]
        if (s !== undefined) return s
        var c = mouse.dpiStages[i]
        return c !== undefined ? c : 0
    }
    function activeIdx() {
        var s = mouse.pendingSensor["dpi_default"]
        return s !== undefined ? s : mouse.dpiDefault
    }
    function sniperIdx() {
        var s = mouse.pendingSensor["dpi_shift"]
        return s !== undefined ? s : mouse.dpiShift
    }
    function rateVal() {
        var s = mouse.pendingSensor["report_rate"]
        return s !== undefined ? s : mouse.reportRate
    }

    // ---------------------------------------------- not connected / no access
    MouseConnectState {}

    // ---------------------------------------------- connected: sensor settings
    QQC.ScrollView {
        id: scroll
        visible: mouse.present
        anchors.top: parent.top; anchors.topMargin: 16
        anchors.left: parent.left; anchors.right: parent.right
        anchors.bottom: pbar.visible ? pbar.top : parent.bottom
        anchors.leftMargin: 20; anchors.rightMargin: 20; anchors.bottomMargin: 16
        clip: true
        contentWidth: availableWidth
        QQC.ScrollBar.horizontal.policy: QQC.ScrollBar.AlwaysOff

        Column {
            width: scroll.availableWidth
            spacing: 16
            // freeze the controls while a write is in flight (matches the Buttons
            // tab) so an edit staged mid-apply can't be cleared out from under it.
            enabled: !mouse.busy
            opacity: mouse.busy ? 0.55 : 1

            // ---- DPI stages ----
            Card {
                width: parent.width
                title: "DPI stages"
                headerValue: mouse.dpiMin + "–" + mouse.dpiMax + " DPI  ·  step " + mouse.dpiStep

                Column {
                    width: parent.width
                    spacing: 8
                    Repeater {
                        model: 5
                        delegate: Item {
                            id: row
                            required property int index
                            width: parent.width
                            height: 40
                            readonly property bool isActive: page.activeIdx() === index
                            readonly property bool isSniper: page.sniperIdx() === index
                            readonly property bool isStagedVal:
                                mouse.pendingSensor["dpi:" + index] !== undefined

                            RowLayout {
                                anchors.fill: parent
                                spacing: 12

                                Text {
                                    Layout.preferredWidth: 20
                                    text: (row.index + 1)
                                    color: Theme.textDim
                                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                                    font.weight: Font.DemiBold
                                }

                                AccentSlider {
                                    id: sl
                                    Layout.fillWidth: true
                                    from: mouse.dpiMin; to: mouse.dpiMax; integer: true
                                    value: page.dpiVal(row.index)
                                    onMoved: function (v) { mouse.stageDpi(row.index, v) }
                                    // AccentSlider breaks its value binding on drag; re-sync
                                    // it whenever the staged/committed value changes (e.g.
                                    // Discard, a refresh, or the snap after a drag).
                                    Connections {
                                        target: mouse
                                        function onPendingChanged() { sl.value = page.dpiVal(row.index) }
                                        function onSensorChanged()  { sl.value = page.dpiVal(row.index) }
                                    }
                                }

                                // fine −/+ by one sensor step
                                PillButton {
                                    label: "−"
                                    onClicked: mouse.stageDpi(row.index, page.dpiVal(row.index) - mouse.dpiStep)
                                }
                                Text {
                                    Layout.preferredWidth: 56
                                    horizontalAlignment: Text.AlignRight
                                    text: page.dpiVal(row.index)
                                    color: row.isStagedVal ? Theme.accent : Theme.text
                                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                                    font.weight: Font.DemiBold
                                }
                                PillButton {
                                    label: "+"
                                    onClicked: mouse.stageDpi(row.index, page.dpiVal(row.index) + mouse.dpiStep)
                                }

                                // which stage is Active (boot) vs Sniper (shift-DPI)
                                PillButton {
                                    label: "Active"; highlight: row.isActive
                                    onClicked: mouse.stageDpiDefault(row.index)
                                }
                                PillButton {
                                    label: "Sniper"; highlight: row.isSniper
                                    onClicked: mouse.stageDpiShift(row.index)
                                }
                            }
                        }
                    }
                }
            }

            // ---- Report rate ----
            Card {
                width: parent.width
                title: "Report rate"
                headerValue: page.rateVal() + " Hz"

                Flow {
                    width: parent.width; spacing: 8
                    Repeater {
                        model: mouse.reportRates
                        delegate: PillButton {
                            required property var modelData
                            label: modelData + " Hz"
                            highlight: page.rateVal() === modelData
                            onClicked: mouse.stageReportRate(modelData)
                        }
                    }
                }
            }

            // ---- how it works ----
            Card {
                width: parent.width
                title: "How the DPI buttons work"
                Text {
                    width: parent.width; wrapMode: Text.WordWrap
                    color: Theme.textDim
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                    text: "Active is the DPI the mouse boots into. A button set to "
                        + "DPI Up / DPI Down / DPI Cycle (on the Buttons tab) steps through "
                        + "the stages above — so give them distinct values to feel the change. "
                        + "A Sniper button drops to the Sniper stage only while it's held."
                }
            }
        }
    }

    // shared queue bar (buttons + sensor); one Apply writes everything
    MousePendingBar {
        id: pbar
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        anchors.leftMargin: 20; anchors.rightMargin: 20; anchors.bottomMargin: 20
    }
}

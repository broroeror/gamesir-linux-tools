import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts

// Front page: live controller render, per-profile button remap (master-detail:
// pick a source on the left, assign a target on the right), and the factory
// default-profile reset. Remap edits stage through the config pending/save queue.
Item {
    id: page
    property string sel: "A"
    property var localRemap: ({})        // staged overrides shown before Save

    function targetCode(src) {                    // -1 = unmapped (Default)
        if (localRemap[src] !== undefined) return localRemap[src]
        var r = bridge.config.remap
        return (r && r[src] !== undefined) ? r[src] : -1
    }
    function targetLabel(src) {
        var c = targetCode(src)
        return c < 0 ? "Default" : bridge.targetLabel(c)
    }
    function assignCode(src, code) {
        var m = Object.assign({}, localRemap); m[src] = code; localRemap = m
        bridge.setRemapCode(src, code)
    }
    Connections { target: bridge; function onConfigLoaded() { page.localRemap = ({}) } }

    // Scroll fallback: fills the viewport in a tall window (content stretches to
    // height via the Math.max below), and scrolls vertically once the stacked
    // cards no longer fit — so nothing clips at small window sizes.
    QQC.ScrollView {
        id: scroller
        anchors.fill: parent
        anchors.bottomMargin: pbar.height + 30   // reserve bar space always (no reflow)
        contentWidth: availableWidth
        QQC.ScrollBar.horizontal.policy: QQC.ScrollBar.AlwaysOff
        clip: true
        topPadding: 20; bottomPadding: 20; leftPadding: 20; rightPadding: 20

    ColumnLayout {
        width: scroller.availableWidth
        height: Math.max(implicitHeight, scroller.availableHeight)
        spacing: 14

        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            spacing: 16

            // -------- LEFT: source list + reset --------
            ColumnLayout {
                visible: bridge.profile > 0
                Layout.fillWidth: true
                Layout.minimumWidth: 250; Layout.preferredWidth: 290; Layout.maximumWidth: 340
                Layout.fillHeight: true
                spacing: 14

                Card {
                    title: "Button Mapping"
                    Layout.fillWidth: true; Layout.fillHeight: true
                    Grid {
                        width: parent.width; columns: 2; spacing: 6
                        Repeater {
                            model: bridge.remapSources
                            delegate: Rectangle {
                                required property string modelData
                                width: (parent.width - 6) / 2; height: 30; radius: 6
                                color: page.sel === modelData ? Theme.cardHover : Theme.button
                                border.color: page.sel === modelData ? Theme.accent : Theme.cardBorder
                                border.width: 1
                                Text {
                                    anchors.left: parent.left; anchors.leftMargin: 8
                                    anchors.right: parent.right; anchors.rightMargin: 8
                                    anchors.verticalCenter: parent.verticalCenter
                                    elide: Text.ElideRight
                                    text: modelData + "  →  " + page.targetLabel(modelData)
                                    color: page.targetCode(modelData) < 0 ? Theme.textDim : Theme.text
                                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                                }
                                TapHandler { onTapped: page.sel = modelData }
                            }
                        }
                    }
                }
            }

            // -------- CENTER: controller + remap indicator --------
            Item {
                id: centerArea
                Layout.fillWidth: true; Layout.fillHeight: true
                Layout.horizontalStretchFactor: 2
                implicitHeight: centerCol.implicitHeight
                Column {
                    id: centerCol
                    width: parent.width
                    y: Math.max(0, (parent.height - implicitHeight) / 2)
                    spacing: 12

                    ControllerView {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: Math.min(implicitWidth, centerArea.width - 24)
                        height: width / aspect
                        highlightSource: bridge.profile > 0 ? page.sel : ""
                        highlightTarget: bridge.profile > 0 ? page.targetLabel(page.sel) : ""
                    }

                    // "<source> → <target>" caption under the pad.
                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        visible: bridge.profile > 0
                        width: capRow.implicitWidth + 28; height: 34; radius: 8
                        color: Theme.card; border.color: Theme.cardBorder; border.width: 1
                        Row {
                            id: capRow; anchors.centerIn: parent; spacing: 8
                            Text {
                                text: page.sel; color: Theme.text; font.bold: true
                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                text: "→"; color: Theme.textDim
                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                text: page.targetCode(page.sel) < 0 ? "unmapped" : page.targetLabel(page.sel)
                                color: page.targetCode(page.sel) < 0 ? Theme.textDim : Theme.accent
                                font.bold: page.targetCode(page.sel) >= 0
                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                    }

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        visible: bridge.profile === 0
                        width: Math.min(implicitWidth, centerArea.width - 24)
                        horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
                        text: "Select a profile (1–4) above to remap buttons."
                        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                    }
                }
            }

            // -------- RIGHT: assign target (+ reset when compact) --------
            ColumnLayout {
                visible: bridge.profile > 0
                Layout.fillWidth: true
                Layout.minimumWidth: 200; Layout.preferredWidth: 240; Layout.maximumWidth: 300
                Layout.fillHeight: true
                spacing: 14

                Card {
                    title: "Assign — " + page.sel; Layout.fillWidth: true
                    Flow {
                        width: parent.width; spacing: 6
                        PillButton {
                            label: "Default"
                            highlight: page.targetCode(page.sel) < 0
                            onClicked: page.assignCode(page.sel, -1)
                        }
                        Repeater {
                            model: bridge.buttonTargets
                            delegate: PillButton {
                                required property var modelData
                                label: modelData.name
                                highlight: page.targetCode(page.sel) === modelData.code
                                onClicked: page.assignCode(page.sel, modelData.code)
                            }
                        }
                    }
                    Text { text: "Keyboard & mouse"; color: Theme.textDim; topPadding: 6
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                    Row {
                        width: parent.width; spacing: 6
                        PillButton { label: "⌨ Keyboard"; onClicked: rebindPicker.open("keyboard") }
                        PillButton { label: "🖱 Mouse";    onClicked: rebindPicker.open("mouse") }
                    }
                }

                Item { Layout.fillHeight: true }
            }
        }
    }
    }

    PendingBar {
        id: pbar
        anchors.left: parent.left; anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 20; anchors.rightMargin: 20; anchors.bottomMargin: 20
    }

    // popout keyboard / mouse picker for rebinds
    TargetPicker {
        id: rebindPicker
        current: page.targetCode(page.sel)
        function open(m) { mode = m }
        onPicked: function (code) { page.assignCode(page.sel, code) }
    }
}

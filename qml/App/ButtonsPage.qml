import QtQuick
import QtQuick.Layouts

// Front page: live controller render, per-profile button remap (master-detail:
// pick a source on the left, assign a target on the right), and the factory
// default-profile reset. Remap edits stage through the config pending/save queue.
Item {
    id: page
    property string sel: "A"
    property var localRemap: ({})        // staged overrides shown before Save

    function targetOf(src) {
        if (localRemap[src] !== undefined) return localRemap[src]
        var r = bridge.config.remap
        return (r && r[src] !== undefined) ? r[src] : "Default"
    }
    function assign(src, target) {
        var m = Object.assign({}, localRemap); m[src] = target; localRemap = m
        bridge.setRemap(src, target)
    }
    Connections { target: bridge; function onConfigLoaded() { page.localRemap = ({}) } }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        anchors.bottomMargin: pbar.visible ? pbar.height + 30 : 20
        spacing: 14

        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            spacing: 16

            // -------- controller + reset --------
            ColumnLayout {
                Layout.preferredWidth: 300; Layout.maximumWidth: 300
                Layout.fillHeight: true
                spacing: 14
                ControllerView {
                    Layout.alignment: Qt.AlignHCenter
                    Layout.preferredWidth: 290
                    Layout.preferredHeight: 290 / aspect
                }
                Card {
                    title: "Default profile"; Layout.fillWidth: true
                    Text {
                        width: parent.width; wrapMode: Text.WordWrap
                        text: bridge.profile > 0
                              ? "Reset Profile " + bridge.profile + " to its out-of-box factory " +
                                "state — buttons, sticks, triggers, vibration, default lighting."
                              : "Select a profile (1–4) above to enable editing."
                        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                    }
                    ConfirmButton {
                        visible: bridge.profile > 0
                        label: "Reset to default"
                        confirmLabel: "Reset Profile " + bridge.profile + "?"
                        onConfirmed: bridge.resetProfileToDefault()
                    }
                }
                Item { Layout.fillHeight: true }
            }

            // -------- source list --------
            Card {
                title: "Button Mapping"; Layout.fillWidth: true; Layout.fillHeight: true
                visible: bridge.profile > 0
                Grid {
                    width: parent.width; columns: 2; spacing: 6
                    Repeater {
                        model: bridge.remapSources
                        delegate: Rectangle {
                            required property string modelData
                            width: (parent.width - 6) / 2; height: 30; radius: 6
                            color: page.sel === modelData ? Theme.cardHover : "#1A1C22"
                            border.color: page.sel === modelData ? Theme.accent : Theme.cardBorder
                            border.width: 1
                            Text {
                                anchors.left: parent.left; anchors.leftMargin: 8
                                anchors.right: parent.right; anchors.rightMargin: 8
                                anchors.verticalCenter: parent.verticalCenter
                                elide: Text.ElideRight
                                text: modelData + "  →  " + page.targetOf(modelData)
                                color: page.targetOf(modelData) === "Default" ? Theme.textDim : Theme.text
                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                            }
                            TapHandler { onTapped: page.sel = modelData }
                        }
                    }
                }
            }

            // -------- assign target --------
            Card {
                title: "Assign — " + page.sel; Layout.preferredWidth: 230; Layout.maximumWidth: 230
                Layout.fillHeight: true
                visible: bridge.profile > 0
                Flow {
                    width: parent.width; spacing: 6
                    Repeater {
                        model: bridge.remapTargets
                        delegate: PillButton {
                            required property string modelData
                            label: modelData
                            highlight: page.targetOf(page.sel) === modelData
                            onClicked: page.assign(page.sel, modelData)
                        }
                    }
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
}

import QtQuick
import QtQuick.Layouts

// Vibration strength (L/R) + poll rate, staged through the config pending/save
// queue, plus a live rumble test (fires immediately).
Item {
    id: page
    property int poll: 2
    property int trigL: 0
    property int trigR: 0
    property bool forceL: false
    property bool syncL: false
    property bool forceR: false
    property bool syncR: false

    function seed() {
        var c = bridge.config
        if (c.vib_l === undefined) return
        vibL.value = c.vib_l; vibR.value = c.vib_r; page.poll = c.poll
        if (bridge.isG7Pro) {
            trigL = c.vib_trigger_l; trigR = c.vib_trigger_r
            forceL = c.vib_force_l; syncL = c.vib_sync_l
            forceR = c.vib_force_r; syncR = c.vib_sync_r
        }
    }
    Component.onCompleted: seed()
    Connections { target: bridge; function onConfigLoaded() { page.seed() } }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        anchors.bottomMargin: pbar.height + 30   // reserve bar space always (no reflow)
        spacing: 14

        Card {
            visible: !bridge.profile
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 460
            title: "No profile selected"
            Text {
                width: parent.width; wrapMode: Text.WordWrap
                text: "Pick a profile (1–4) in the top bar to read and edit its settings."
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
            }
        }

        ColumnLayout {
            visible: bridge.profile > 0
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: 10
            Layout.preferredWidth: 460
            spacing: 16

            Card {
                title: "Vibration strength"; Layout.fillWidth: true
                Row {
                    width: parent.width
                    Text { text: "Left"; color: Theme.textDim
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                    Item { width: parent.width - 70; height: 1 }
                    Text { text: vibL.value + "%"; color: Theme.text
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                }
                AccentSlider {
                    id: vibL; width: parent.width; from: 0; to: 100
                    visible: !bridge.isG7Pro
                    onMoved: bridge.setScalar("vib_l", value)
                }
                Flow {
                    visible: bridge.isG7Pro; width: parent.width; spacing: 6
                    Repeater { model: [0, 25, 50, 75, 100]; delegate: PillButton {
                        required property int modelData; label: modelData + "%"
                        highlight: vibL.value === modelData
                        onClicked: { vibL.value = modelData; bridge.setScalar("vib_l", modelData) }
                    }}
                }
                Row {
                    width: parent.width
                    Text { text: "Right"; color: Theme.textDim
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                    Item { width: parent.width - 70; height: 1 }
                    Text { text: vibR.value + "%"; color: Theme.text
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                }
                AccentSlider {
                    id: vibR; width: parent.width; from: 0; to: 100
                    visible: !bridge.isG7Pro
                    onMoved: bridge.setScalar("vib_r", value)
                }
                Flow {
                    visible: bridge.isG7Pro; width: parent.width; spacing: 6
                    Repeater { model: [0, 25, 50, 75, 100]; delegate: PillButton {
                        required property int modelData; label: modelData + "%"
                        highlight: vibR.value === modelData
                        onClicked: { vibR.value = modelData; bridge.setScalar("vib_r", modelData) }
                    }}
                }
                PillButton {
                    label: "Test rumble"
                    onClicked: bridge.rumbleTest()
                }
            }

            Card {
                visible: bridge.isG7Pro; title: "Trigger motors"; Layout.fillWidth: true
                Repeater {
                    model: [{side: "l", label: "Left trigger"}, {side: "r", label: "Right trigger"}]
                    delegate: Column {
                        required property var modelData
                        width: parent.width; spacing: 6
                        Text { text: modelData.label; color: Theme.text; font.family: Theme.fontFamily }
                        Flow {
                            width: parent.width; spacing: 6
                            Repeater { model: [0, 25, 50, 75, 100]; delegate: PillButton {
                                required property int modelData
                                label: modelData + "%"
                                highlight: (parent.parent.modelData.side === "l" ? page.trigL : page.trigR) === modelData
                                onClicked: {
                                    var side = parent.parent.modelData.side
                                    if (side === "l") page.trigL = modelData; else page.trigR = modelData
                                    bridge.setG7Extra("vib_trigger_" + side, modelData)
                                }
                            }}
                        }
                        Row {
                            spacing: 16
                            Row { spacing: 6; Text { text: "Force"; color: Theme.textDim }
                                ToggleSwitch { checked: modelData.side === "l" ? page.forceL : page.forceR
                                    onToggled: { if (modelData.side === "l") page.forceL = checked; else page.forceR = checked
                                                 bridge.setG7Extra("vib_force_" + modelData.side, checked ? 1 : 0) } } }
                            Row { spacing: 6; Text { text: "Sync"; color: Theme.textDim }
                                ToggleSwitch { checked: modelData.side === "l" ? page.syncL : page.syncR
                                    onToggled: { if (modelData.side === "l") page.syncL = checked; else page.syncR = checked
                                                 bridge.setG7Extra("vib_sync_" + modelData.side, checked ? 1 : 0) } } }
                        }
                    }
                }
            }

            Card {
                title: "Poll rate"; Layout.fillWidth: true
                Flow {
                    width: parent.width; spacing: 8
                    Repeater {
                        model: bridge.pollRates
                        delegate: PillButton {
                            required property string modelData
                            required property int index
                            label: modelData
                            highlight: page.poll === index
                            onClicked: { page.poll = index; bridge.setPoll(index) }
                        }
                    }
                }
            }
        }
        Item { Layout.fillHeight: true }
    }

    PendingBar {
        id: pbar
        anchors.left: parent.left; anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 20; anchors.rightMargin: 20; anchors.bottomMargin: 20
    }
}

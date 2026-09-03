import QtQuick
import QtQuick.Layouts

Item {
    id: page
    property int brightness: 100
    property bool autoOn: false

    function seed() {
        var c = bridge.config
        if (c.dock_brightness === undefined) return
        brightness = c.dock_brightness
        autoOn = c.dock_auto
    }
    Component.onCompleted: seed()
    Connections { target: bridge; function onConfigLoaded() { page.seed() } }

    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(500, parent.width - 40)
        spacing: 14

        Card {
            Layout.fillWidth: true
            title: "G7 Pro configuration session"
            Text {
                width: parent.width; wrapMode: Text.WordWrap
                text: bridge.configStatus + (bridge.configClaimed
                      ? "\nThe controller or dongle is temporarily unavailable to games."
                      : "\nUse Configure controller above to edit or refresh settings.")
                color: bridge.configClaimed ? Theme.warn : Theme.textDim
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
            }
        }

        Card {
            Layout.fillWidth: true
            title: "Charging dock"
            Row {
                width: parent.width
                Text { text: "Auto on / off"; color: Theme.text; font.family: Theme.fontFamily }
                Item { width: parent.width - 150; height: 1 }
                ToggleSwitch {
                    checked: page.autoOn
                    onToggled: { page.autoOn = checked; bridge.setG7Extra("dock_auto", checked ? 1 : 0) }
                }
            }
            Text {
                text: "Brightness  " + page.brightness + "%"; color: Theme.textDim
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
            }
            Flow {
                width: parent.width; spacing: 8
                Repeater {
                    model: [0, 25, 50, 75, 100]
                    delegate: PillButton {
                        required property int modelData
                        label: modelData + "%"; highlight: page.brightness === modelData
                        onClicked: { page.brightness = modelData
                                     bridge.setG7Extra("dock_brightness", modelData) }
                    }
                }
            }
        }
    }

    PendingBar {
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        anchors.margins: 20
    }
}

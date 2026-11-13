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
        dockBright.value = c.dock_brightness   // explicit: a drag breaks a binding
        autoOn = c.dock_auto
    }
    Component.onCompleted: seed()
    Connections { target: bridge; function onConfigLoaded() { page.seed() } }

    // Same frame as VibrationPage (and the other tabs): fill the page, top-aligned,
    // with the pending bar's space always reserved. This used to centre a narrow
    // column in the middle of the window, leaving the only page laid out that way
    // with a large empty band above its first card.
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        anchors.bottomMargin: pbar.height + 30   // reserve bar space always (no reflow)
        spacing: 14

        ColumnLayout {
        Layout.alignment: Qt.AlignHCenter
        Layout.topMargin: 10
        Layout.preferredWidth: 460
        spacing: 16

        Card {
            Layout.fillWidth: true
            title: qsTranslate("UI", "G7 Pro configuration session")
            Text {
                width: parent.width; wrapMode: Text.WordWrap
                text: bridge.configStatus + (bridge.configClaimed
                      ? qsTranslate("UI", "\nThe controller or dongle is temporarily unavailable to games.")
                      : qsTranslate("UI", "\nUse Configure controller above to edit or refresh settings."))
                color: bridge.configClaimed ? Theme.warn : Theme.textDim
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
            }
        }

        Card {
            Layout.fillWidth: true
            title: qsTranslate("UI", "Charging dock")
            Row {
                width: parent.width
                Text { text: qsTranslate("UI", "Auto on / off"); color: Theme.text; font.family: Theme.fontFamily }
                Item { width: parent.width - 150; height: 1 }
                ToggleSwitch {
                    checked: page.autoOn
                    onToggled: { page.autoOn = checked; bridge.setG7Extra("dock_auto", checked ? 1 : 0) }
                }
            }
            Row {
                width: parent.width
                Text { text: qsTranslate("UI", "Brightness"); color: Theme.textDim
                       font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                Item { width: parent.width - 110; height: 1 }
                Text { text: dockBright.value + "%"; color: Theme.text
                       font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
            }
            AccentSlider {
                id: dockBright; width: parent.width; from: 0; to: 100
                onMoved: { page.brightness = value; bridge.setG7Extra("dock_brightness", value) }
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

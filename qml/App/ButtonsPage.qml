import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts

// Front page: live controller render and per-profile button remap (master-detail:
// pick a source on the left, assign a target on the right). Remap edits stage
// through the config pending/save queue. The factory default-profile reset used
// to live here; it's in the header beside the profile pills now.
Item {
    id: page
    objectName: "controllerButtonsPage"
    property string sel: "A"
    property var localRemap: ({})        // staged overrides shown before Save
    property var localContinuous: ({})
    property bool dpadSwap: false
    property bool dpadLock: false
    readonly property bool canRemap: bridge.profileCount > 0 && bridge.profile > 0
                                     && bridge.remapSources.length > 0
    Component.onCompleted: {
        if (bridge.remapSources.indexOf(sel) < 0)
            sel = bridge.remapSources.length ? bridge.remapSources[0] : ""
    }

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
    function continuousState(src) {
        if (localContinuous[src] !== undefined) return localContinuous[src]
        var flags = bridge.config.continuous_trigger
        return flags && flags[src] !== undefined ? flags[src] : -1
    }
    function macroAllowsToggle(src) {
        if (bridge.macroSlots.indexOf(src) < 0) return true
        var m = bridge.macros[src]
        return m !== undefined && !m.enable
    }
    Connections { target: bridge; function onConfigLoaded() {
        page.localRemap = ({})
        page.localContinuous = ({})
        if (bridge.config.dpad_swap !== undefined) page.dpadSwap = bridge.config.dpad_swap
        if (bridge.config.dpad_lock !== undefined) page.dpadLock = bridge.config.dpad_lock
    }
    function onControllerChanged() {
        page.localRemap = ({})
        if (bridge.remapSources.indexOf(page.sel) < 0)
            page.sel = bridge.remapSources.length ? bridge.remapSources[0] : ""
    } }

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

            // -------- LEFT: source list --------
            ColumnLayout {
                visible: page.canRemap
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
                                    text: modelData + (page.targetCode(modelData) >= 0 ? "  →  " + page.targetLabel(modelData) : "")
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
                        highlightSource: page.canRemap ? page.sel : ""
                        highlightTarget: page.canRemap ? page.targetLabel(page.sel) : ""
                    }

                    Card {
                        visible: bridge.remapOnly
                        width: parent.width
                        title: "Live input"
                        Grid {
                            width: parent.width
                            columns: 2; spacing: 8
                            Repeater {
                                model: [
                                    "LT  " + Math.round(bridge.leftTrigger * 100) + "%",
                                    "RT  " + Math.round(bridge.rightTrigger * 100) + "%",
                                    "Left stick  X " + bridge.leftStickX.toFixed(2)
                                        + "  Y " + bridge.leftStickY.toFixed(2),
                                    "Right stick  X " + bridge.rightStickX.toFixed(2)
                                        + "  Y " + bridge.rightStickY.toFixed(2)
                                ]
                                delegate: Text {
                                    required property string modelData
                                    width: (parent.width - 8) / 2
                                    text: modelData
                                    color: Theme.text
                                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }
                    }

                    // "<source> → <target>" caption under the pad.
                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        visible: page.canRemap
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
                        objectName: "remapUnavailableMessage"
                        anchors.horizontalCenter: parent.horizontalCenter
                        visible: !page.canRemap
                        width: Math.min(implicitWidth, centerArea.width - 24)
                        horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
                        text: bridge.profileCount > 0
                              ? "Select a profile above to remap buttons."
                              : "Button remapping is unavailable for " + bridge.controllerName
                                + " in this app. Configuration is disabled."
                        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                    }
                }
            }

            // -------- RIGHT: assign target --------
            ColumnLayout {
                visible: page.canRemap
                enabled: !bridge.remapOnly || (bridge.config.remap !== undefined
                         && bridge.connected && !bridge.backupBusy)
                Layout.fillWidth: true
                Layout.minimumWidth: 200; Layout.preferredWidth: 240; Layout.maximumWidth: 300
                Layout.fillHeight: true
                spacing: 14

                Card {
                    visible: bridge.hasContinuousTrigger
                    title: "Continuous Trigger"; Layout.fillWidth: true
                    RowLayout {
                        width: parent.width
                        Text {
                            text: "Tap to hold / release"
                            Layout.fillWidth: true; wrapMode: Text.WordWrap
                            color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        }
                        ToggleSwitch {
                            objectName: "continuousTriggerSwitch"
                            checked: page.continuousState(page.sel) === 1
                            enabled: page.continuousState(page.sel) >= 0 && page.macroAllowsToggle(page.sel)
                                     && !bridge.backupBusy && bridge.connected
                            opacity: enabled ? 1 : 0.4
                            onToggled: function(on) {
                                if (bridge.setContinuousTrigger(page.sel, on)) {
                                    var flags = Object.assign({}, page.localContinuous)
                                    flags[page.sel] = on ? 1 : 0; page.localContinuous = flags
                                }
                                checked = Qt.binding(function() { return page.continuousState(page.sel) === 1 })
                            }
                        }
                    }
                    Text {
                        width: parent.width; wrapMode: Text.WordWrap
                        text: page.continuousState(page.sel) < 0
                              ? "Waiting for a supported setting from the controller."
                              : !page.macroAllowsToggle(page.sel)
                                ? "Use a normal mapping for this paddle; disable its macro first."
                                : "After Save, tap " + page.sel + " to hold its output, then tap again to release. Saved in this profile; works after Deadband closes."
                        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                    }
                }

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
                    Text { visible: !bridge.remapOnly; text: "Keyboard & mouse"; color: Theme.textDim; topPadding: 6
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                    Flow {
                        visible: !bridge.remapOnly
                        width: parent.width; spacing: 6
                        PillButton { label: "⌨ Keyboard"; onClicked: rebindPicker.open("keyboard") }
                        PillButton { label: "🖱 Mouse";    onClicked: rebindPicker.open("mouse") }
                    }
                }

                Card {
                    visible: bridge.isG7Pro; title: "D-pad options"; Layout.fillWidth: true
                    Row {
                        width: parent.width
                        Text { text: "Swap left stick / D-pad"; color: Theme.textDim }
                        Item { width: parent.width - 190; height: 1 }
                        ToggleSwitch { checked: page.dpadSwap
                            onToggled: { page.dpadSwap = checked
                                         bridge.setG7Extra("dpad_swap", checked ? 1 : 0) } }
                    }
                    Row {
                        width: parent.width
                        Text { text: "Diagonal lock"; color: Theme.textDim }
                        Item { width: parent.width - 120; height: 1 }
                        ToggleSwitch { checked: page.dpadLock
                            onToggled: { page.dpadLock = checked
                                         bridge.setG7Extra("dpad_lock", checked ? 1 : 0) } }
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

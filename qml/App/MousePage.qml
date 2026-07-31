import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts

// G502 X onboard button config — master-detail like the controller ButtonsPage:
// pick a button (from the list or the diagram), then assign a target. Each assign
// calls mouse.remap(), which applies through the backend's backed-up + gated +
// read-back-verified write. Handles the not-connected / needs-permission states.
Item {
    id: page
    property int selIndex: -1
    property string selName: ""
    property string editLayer: "default"        // "default" | "gshift" (alternate bank)

    function committedLabel(i) {
        var map = page.editLayer === "gshift" ? mouse.gbindings : mouse.bindings
        var b = map[String(i)]
        return (b === undefined || b === "" || b === "(empty)") ? "unset" : b
    }
    function pkey(i) { return page.editLayer + ":" + i }
    function isStaged(i) { return mouse.pending[page.pkey(i)] !== undefined }
    // what to show for a button on the current layer: staged target if any, else committed
    function bindLabel(i) {
        return page.isStaged(i) ? mouse.pending[page.pkey(i)] : page.committedLabel(i)
    }
    // assign = STAGE on the current layer (no device write until Apply)
    function stage(spec) { if (page.selIndex >= 0) mouse.stage(page.editLayer, page.selIndex, spec) }
    function nameFor(i) {
        for (var j = 0; j < mv.buttons.length; j++)
            if (mv.buttons[j].i === i) return mv.buttons[j].name
        return "#" + i
    }
    // staged edits across BOTH layers, for the pending-bar chips
    readonly property var pendingList: {
        var out = []; var p = mouse.pending
        for (var k in p) {
            var parts = k.split(":")
            out.push({ layer: parts[0], i: parseInt(parts[1]),
                       name: page.nameFor(parseInt(parts[1])), label: p[k] })
        }
        return out
    }

    // ---------------------------------------------- not connected / no access
    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(parent.width - 60, 460)
        visible: !mouse.present
        spacing: 14

        Text {
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontL; color: Theme.text
            text: mouse.permission === "no-access"
                    ? "Your G502 X is connected, but Deadband can't access it yet."
                    : mouse.permission === "absent"
                    ? "Connect your Logitech G502 X to configure it."
                    : "Looking for a G502 X…"
        }
        Card {
            visible: mouse.permission === "no-access"
            title: "Grant access (one-time)"
            Layout.fillWidth: true
            Text {
                width: parent.width; wrapMode: Text.WrapAnywhere
                color: Theme.textDim; font.family: "monospace"; font.pixelSize: Theme.fontS
                text: "sudo cp packaging/udev/70-deadband-g502x.rules /etc/udev/rules.d/\n"
                    + "sudo udevadm control --reload && sudo udevadm trigger"
            }
            Text {
                width: parent.width; wrapMode: Text.WordWrap; topPadding: 6
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                text: "…then replug the mouse. If ratbagd holds the device, stop it first."
            }
        }
        PillButton { Layout.alignment: Qt.AlignHCenter; label: "Retry"; onClicked: mouse.refresh() }
    }

    // ---------------------------------------------- connected: master-detail
    // Default / G-Shift layer toggle (like the reference's DEFAULT/G-SHIFT switch)
    Row {
        id: layerToggle
        visible: mouse.present
        anchors.top: parent.top; anchors.topMargin: 14
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 8
        PillButton { label: "Default"; highlight: page.editLayer === "default"
                     onClicked: page.editLayer = "default" }
        PillButton { label: "G-Shift"; highlight: page.editLayer === "gshift"
                     onClicked: page.editLayer = "gshift" }
    }

    RowLayout {
        anchors.top: layerToggle.bottom; anchors.topMargin: 12
        anchors.left: parent.left; anchors.right: parent.right
        anchors.bottom: pbar.visible ? pbar.top : parent.bottom
        anchors.leftMargin: 20; anchors.rightMargin: 20; anchors.bottomMargin: 20
        spacing: 16
        visible: mouse.present

        // -------- LEFT: button list --------
        Card {
            title: "Buttons"
            Layout.preferredWidth: 270; Layout.minimumWidth: 230; Layout.fillHeight: true
            Column {
                width: parent.width; spacing: 5
                Repeater {
                    model: mv.buttons
                    delegate: Rectangle {
                        required property var modelData
                        width: parent.width; height: 32; radius: 6
                        color: page.selIndex === modelData.i ? Theme.cardHover : Theme.button
                        border.color: page.selIndex === modelData.i ? Theme.accent : Theme.cardBorder
                        border.width: 1
                        Text {
                            anchors.left: parent.left; anchors.leftMargin: 9
                            anchors.right: parent.right; anchors.rightMargin: 9
                            anchors.verticalCenter: parent.verticalCenter
                            elide: Text.ElideRight
                            text: (page.isStaged(modelData.i) ? "• " : "")
                                  + modelData.name + "  →  " + page.bindLabel(modelData.i)
                            color: page.isStaged(modelData.i) ? Theme.accent
                                   : (page.bindLabel(modelData.i) === "unset" ? Theme.textDim : Theme.text)
                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        }
                        TapHandler {
                            onTapped: { page.selIndex = modelData.i; page.selName = modelData.name }
                        }
                    }
                }
            }
        }

        // -------- CENTER: the mouse diagram --------
        Item {
            Layout.fillWidth: true; Layout.fillHeight: true
            Layout.horizontalStretchFactor: 2
            MouseView {
                id: mv
                anchors.centerIn: parent
                height: Math.min(parent.height - 16, 480)
                width: height * aspect
                selectedIndex: page.selIndex
                onButtonActivated: function (index, name) {
                    page.selIndex = index; page.selName = name
                }
            }
        }

        // -------- RIGHT: assign a target --------
        Card {
            title: (page.selIndex < 0 ? "Assign" : "Assign — " + page.selName)
                   + (page.editLayer === "gshift" ? "  · G-Shift" : "")
            Layout.preferredWidth: 260; Layout.minimumWidth: 220; Layout.fillHeight: true
            Column {
                width: parent.width; spacing: 10
                enabled: page.selIndex >= 0 && !mouse.busy
                opacity: (page.selIndex >= 0 && !mouse.busy) ? 1 : 0.45

                Flow {
                    width: parent.width; spacing: 6
                    PillButton { label: "Disabled";  onClicked: page.stage("disabled") }
                    PillButton { label: "Sniper";    onClicked: page.stage("sniper") }
                    PillButton { label: "DPI +";     onClicked: page.stage("dpi-up") }
                    PillButton { label: "DPI −";     onClicked: page.stage("dpi-down") }
                    PillButton { label: "DPI cycle"; onClicked: page.stage("dpi-cycle") }
                }
                Text {
                    width: parent.width; text: "Mouse buttons"; color: Theme.textDim
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
                Flow {
                    width: parent.width; spacing: 6
                    Repeater {
                        model: 5
                        delegate: PillButton {
                            required property int index
                            label: "M" + (index + 1)
                            onClicked: page.stage("mouse:" + (index + 1))
                        }
                    }
                }
                Text {
                    width: parent.width; text: "Keyboard"; color: Theme.textDim
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
                PillButton {
                    label: "⌨  Choose a key…"
                    onClicked: keyPicker.active = true
                }
                Text {
                    width: parent.width; wrapMode: Text.WordWrap; topPadding: 4
                    visible: !mouse.busy && mouse.status.length > 0
                    text: mouse.status
                    color: Theme.textDim
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
            }
        }
    }

    // -------- staged-changes bar: shows each queued edit; applies all in one write --------
    Rectangle {
        id: pbar
        visible: mouse.present && mouse.pendingCount > 0
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        anchors.leftMargin: 20; anchors.rightMargin: 20; anchors.bottomMargin: 20
        height: Math.max(52, chips.implicitHeight + 20); radius: Theme.radius
        color: Theme.card; border.color: Theme.accent; border.width: 1

        Row {
            id: actions
            anchors.right: parent.right; anchors.rightMargin: 14
            anchors.verticalCenter: parent.verticalCenter; spacing: 8
            PillButton { label: "Discard"; enabled: !mouse.busy; onClicked: mouse.discard() }
            PillButton {
                label: mouse.busy ? "Applying…" : "Apply " + mouse.pendingCount
                highlight: !mouse.busy; enabled: !mouse.busy
                onClicked: mouse.apply()
            }
        }
        // one chip per queued change (✕ removes just that one)
        Flow {
            id: chips
            anchors.left: parent.left; anchors.leftMargin: 14
            anchors.right: actions.left; anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6
            Repeater {
                model: page.pendingList
                delegate: Rectangle {
                    required property var modelData
                    height: 26; radius: 6; implicitWidth: chipRow.implicitWidth + 16
                    color: Theme.button; border.color: Theme.accent; border.width: 1
                    Row {
                        id: chipRow; anchors.centerIn: parent; spacing: 6
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: (modelData.layer === "gshift" ? "G· " : "")
                                  + modelData.name + "  →  " + modelData.label
                            color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: "✕"; color: Theme.textDim; font.pixelSize: Theme.fontS
                            TapHandler { enabled: !mouse.busy; onTapped: mouse.unstage(modelData.layer, modelData.i) }
                        }
                    }
                }
            }
        }
    }

    // modal keyboard picker, opened by the assign panel's "Choose a key…"
    MouseKeyPicker {
        id: keyPicker
        onPicked: function (spec) { page.stage(spec) }
    }
}

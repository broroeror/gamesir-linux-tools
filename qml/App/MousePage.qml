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
    // ---------------------------------------------- not connected / no access
    MouseConnectState {}

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
                    PillButton {
                        label: "G-Shift"; visible: page.editLayer === "default"
                        onClicked: page.stage("gshift-hold")     // makes this button the G-Shift trigger
                    }
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

    // -------- staged-changes bar: shows every queued edit; applies all in one write --------
    MousePendingBar {
        id: pbar
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        anchors.leftMargin: 20; anchors.rightMargin: 20; anchors.bottomMargin: 20
    }

    // modal keyboard picker, opened by the assign panel's "Choose a key…"
    MouseKeyPicker {
        id: keyPicker
        onPicked: function (spec) { page.stage(spec) }
    }
}

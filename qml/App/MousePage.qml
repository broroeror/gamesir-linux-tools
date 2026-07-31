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

    function bindLabel(i) {
        var b = mouse.bindings[String(i)]
        return (b === undefined || b === "" || b === "(empty)") ? "unset" : b
    }
    function apply(spec) { if (page.selIndex >= 0) mouse.remap(page.selIndex, spec) }

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
    RowLayout {
        anchors.fill: parent; anchors.margins: 20; spacing: 16
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
                            text: modelData.name + "  →  " + page.bindLabel(modelData.i)
                            color: page.bindLabel(modelData.i) === "unset" ? Theme.textDim : Theme.text
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
            title: page.selIndex < 0 ? "Assign" : "Assign — " + page.selName
            Layout.preferredWidth: 260; Layout.minimumWidth: 220; Layout.fillHeight: true
            Column {
                width: parent.width; spacing: 10
                enabled: page.selIndex >= 0
                opacity: page.selIndex >= 0 ? 1 : 0.45

                Flow {
                    width: parent.width; spacing: 6
                    PillButton { label: "Disabled";  onClicked: page.apply("disabled") }
                    PillButton { label: "Sniper";    onClicked: page.apply("sniper") }
                    PillButton { label: "DPI +";     onClicked: page.apply("dpi-up") }
                    PillButton { label: "DPI −";     onClicked: page.apply("dpi-down") }
                    PillButton { label: "DPI cycle"; onClicked: page.apply("dpi-cycle") }
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
                            onClicked: page.apply("mouse:" + (index + 1))
                        }
                    }
                }
                Text {
                    width: parent.width; text: "Keyboard key"; color: Theme.textDim
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
                Row {
                    width: parent.width; spacing: 6
                    QQC.TextField {
                        id: keyField
                        width: parent.width - setBtn.width - 6
                        placeholderText: "a, enter, f5…"
                        color: Theme.text
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                        background: Rectangle {
                            color: Theme.button; border.color: Theme.cardBorder
                            border.width: 1; radius: 6
                        }
                    }
                    PillButton {
                        id: setBtn; label: "Set"
                        onClicked: if (keyField.text.length) page.apply("key:" + keyField.text.trim())
                    }
                }
                Text {
                    width: parent.width; wrapMode: Text.WordWrap; topPadding: 4
                    visible: mouse.status.length > 0
                    text: mouse.status; color: Theme.textDim
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
            }
        }
    }
}

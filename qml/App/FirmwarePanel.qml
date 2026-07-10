import QtQuick

// Firmware BACKUP & RESTORE (not a firmware updater). Back up the controller's
// current firmware to a local library, or restore a firmware version you
// previously backed up (your settings/calibration are preserved). Drives
// bridge.backupFirmware / bridge.restoreFirmware. Requires the external
// jl-uboot-tool (bridge.firmwareToolingAvailable); if absent, we explain how to
// enable it instead of failing on click.
Column {
    id: panel
    spacing: 12
    property string status: ""
    property bool statusOk: true
    property string phase: ""
    property string selectedVersion: ""

    function _defaultSelection() {
        var vs = bridge.fwVersions
        if (vs.indexOf(bridge.firmware) >= 0) return bridge.firmware
        return vs.length > 0 ? vs[0] : ""
    }
    Component.onCompleted: selectedVersion = _defaultSelection()
    Connections {
        target: bridge
        function onFwVersionsChanged() {
            if (panel.selectedVersion === "" || bridge.fwVersions.indexOf(panel.selectedVersion) < 0)
                panel.selectedVersion = panel._defaultSelection()
        }
        function onFwProgress(p) { panel.phase = p }
        function onFwStatus(ok, msg) {
            panel.status = msg; panel.statusOk = ok; panel.phase = ""
        }
    }

    Text {
        width: parent.width; wrapMode: Text.WordWrap
        text: "Installed firmware: " + (bridge.firmware.length ? bridge.firmware : "—") +
              ".  Back up the current firmware to your library, or restore a version " +
              "you previously backed up (your settings & calibration are kept)."
        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
    }

    // jl-uboot-tool not installed: firmware backup/restore is unavailable. Explain
    // it instead of offering buttons that would error.
    Rectangle {
        visible: !bridge.firmwareToolingAvailable
        width: parent.width; radius: Theme.radiusSm
        color: "transparent"; border.color: Theme.cardBorder; border.width: 1
        implicitHeight: toolText.implicitHeight + 16
        Text {
            id: toolText
            anchors.fill: parent; anchors.margins: 8
            width: parent.width - 16; wrapMode: Text.WordWrap
            text: "Firmware backup/restore needs the external tool jl-uboot-tool " +
                  "(not bundled). Install it alongside the app to enable this — see " +
                  "FIRMWARE.md. Everything else works without it."
            color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
        }
    }

    // --- everything below only when the tooling is present -------------------
    Column {
        visible: bridge.firmwareToolingAvailable
        width: parent.width; spacing: 12

        // saved firmware versions (your backups)
        Flow {
            width: parent.width; spacing: 8
            Repeater {
                model: bridge.fwVersions
                delegate: Rectangle {
                    required property string modelData
                    readonly property bool sel: panel.selectedVersion === modelData
                    readonly property bool installed: bridge.firmware === modelData
                    height: 30; radius: 8
                    width: vlabel.implicitWidth + 24
                    color: sel ? Theme.accent : (chipHov.hovered ? Theme.cardHover : Theme.card)
                    border.color: sel ? Theme.accent : Theme.cardBorder; border.width: 1
                    opacity: bridge.fwBusy ? 0.5 : 1
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Text {
                        id: vlabel; anchors.centerIn: parent
                        text: "v" + parent.modelData + (parent.installed ? "  • installed" : "")
                        color: parent.sel ? "white" : Theme.text
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                    }
                    HoverHandler { id: chipHov }
                    TapHandler { onTapped: if (!bridge.fwBusy) panel.selectedVersion = parent.modelData }
                }
            }
            Text {
                visible: bridge.fwVersions.length === 0
                text: "No firmware backed up yet — use “Back up current firmware” to make a restore point."
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
            }
        }

        // actions: restore a backed-up version, or back up the current one
        Row {
            spacing: 8
            ConfirmButton {
                enabled: !bridge.fwBusy && panel.selectedVersion.length > 0
                opacity: enabled ? 1 : 0.5
                label: panel.selectedVersion.length ? "Restore v" + panel.selectedVersion : "Restore…"
                confirmLabel: "Restore v" + panel.selectedVersion + "?"
                onConfirmed: bridge.restoreFirmware(panel.selectedVersion)
            }
            PillButton {
                label: "Back up current firmware"
                opacity: bridge.fwBusy ? 0.5 : 1
                onClicked: if (!bridge.fwBusy) bridge.backupFirmware("")
            }
        }
    }

    // progress (indeterminate: a sweeping segment while busy) + phase text
    Rectangle {
        visible: bridge.fwBusy
        width: parent.width; height: 8; radius: 4; color: Theme.track; clip: true
        Rectangle {
            id: seg; height: parent.height; radius: 4; color: Theme.accent
            width: parent.width * 0.35
            SequentialAnimation on x {
                running: bridge.fwBusy; loops: Animation.Infinite
                NumberAnimation { from: -seg.width; to: panel.width; duration: 1100; easing.type: Easing.InOutQuad }
            }
        }
    }
    Text {
        visible: bridge.fwBusy
        text: panel.phase.length ? panel.phase : "Working…"
        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
    }
    Text {
        visible: panel.status.length > 0 && !bridge.fwBusy
        width: parent.width; wrapMode: Text.WordWrap
        text: panel.status
        color: panel.statusOk ? Theme.ok : Theme.accent
        font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
    }

    // Connection banner: restoring writes to whatever is connected, so a strong
    // callout if that's the 2.4GHz dongle (writing to it bricks it); a reassuring
    // note when wired. The in-loader identity guard is the authoritative backstop.
    Rectangle {
        visible: bridge.firmwareToolingAvailable
        width: parent.width; radius: Theme.radiusSm
        color: bridge.onDongle ? "#3A2A14" : "transparent"
        border.color: bridge.onDongle ? Theme.warn
                    : (bridge.connectionKind === "Wired" ? Theme.ok : Theme.cardBorder)
        border.width: 1
        implicitHeight: connText.implicitHeight + 16
        Text {
            id: connText
            anchors.fill: parent; anchors.margins: 8
            width: parent.width - 16; wrapMode: Text.WordWrap
            text: bridge.onDongle
                  ? "⚠ Connected through the 2.4GHz DONGLE. A restore now writes to the " +
                    "DONGLE (and bricks it) — connect the controller DIRECTLY with a USB-C " +
                    "cable first. The app refuses a dongle in the loader anyway."
                  : (bridge.connectionKind === "Wired"
                     ? "✓ Wired controller detected — safe to restore. (The loader also " +
                       "confirms the exact device by its flash-header identity before writing.)"
                     : "Connect the controller DIRECTLY with a USB-C cable to restore — NOT " +
                       "over the 2.4GHz dongle (writing the dongle bricks it).")
            color: bridge.onDongle ? Theme.warn
                 : (bridge.connectionKind === "Wired" ? Theme.ok : Theme.textDim)
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
        }
    }

    Text {
        visible: bridge.firmwareToolingAvailable
        width: parent.width; wrapMode: Text.WordWrap
        text: "Safe: an interrupted restore isn’t fatal — the controller re-enters its " +
              "loader on the next power-cycle so you can retry. It briefly disconnects; " +
              "don’t unplug until it finishes."
        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
        opacity: 0.8
    }
}

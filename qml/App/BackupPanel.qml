import QtQuick
import QtQuick.Dialogs
import QtCore

// Backup / restore the whole controller (all 4 profiles + lighting) to/from a
// JSON file, with live progress. Drives bridge.exportBackup / importBackup.
Column {
    id: panel
    spacing: 12
    property string status: ""
    property bool statusOk: true
    property int progDone: 0
    property int progTotal: 0

    Connections {
        target: bridge
        function onBackupProgress(d, t) { panel.progDone = d; panel.progTotal = t }
        function onBackupStatus(ok, msg) {
            panel.status = msg; panel.statusOk = ok
            panel.progDone = 0; panel.progTotal = 0
        }
    }

    Text {
        width: parent.width; wrapMode: Text.WordWrap
        text: qsTranslate("UI", "Snapshot every profile + lighting to a file, or write a saved snapshot back. Restoring overwrites the controller.")
        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
    }

    Row {
        spacing: 8
        PillButton {
            label: qsTranslate("UI", "Back up to file…")
            highlight: true
            opacity: bridge.backupBusy ? 0.5 : 1
            onClicked: if (!bridge.backupBusy) {
                // Pre-fill a dated filename so the user only has to confirm.
                saveDlg.selectedFile = saveDlg.currentFolder + "/" + bridge.defaultBackupName
                saveDlg.open()
            }
        }
        PillButton {
            label: qsTranslate("UI", "Restore from file…")
            opacity: bridge.backupBusy ? 0.5 : 1
            onClicked: if (!bridge.backupBusy) openDlg.open()
        }
    }

    // Reset every profile back to defaults — the "all 4" counterpart to the top
    // bar's single-profile reset. Destructive, so it confirms first.
    ConfirmButton {
        visible: bridge.profileResetSupported
        enabled: !bridge.backupBusy
        opacity: enabled ? 1 : 0.5
        label: qsTranslate("UI", "Reset all profiles to defaults")
        confirmLabel: qsTranslate("UI", "Reset all %1 profiles?").arg(bridge.profileCount)
        onConfirmed: bridge.resetAllProfiles()
    }

    // progress
    Rectangle {
        visible: bridge.backupBusy || panel.progTotal > 0
        width: parent.width; height: 8; radius: 4; color: Theme.track
        Rectangle {
            height: parent.height; radius: 4; color: Theme.accent
            width: panel.progTotal > 0 ? parent.width * panel.progDone / panel.progTotal : 0
        }
    }
    Text {
        visible: bridge.backupBusy
        text: qsTranslate("UI", "Working… ") + panel.progDone + " / " + panel.progTotal + qsTranslate("UI", " blocks")
        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
    }
    Text {
        visible: panel.status.length > 0 && !bridge.backupBusy
        width: parent.width; wrapMode: Text.WordWrap
        text: panel.status
        color: panel.statusOk ? Theme.ok : Theme.accent
        font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
    }

    FileDialog {
        id: saveDlg
        fileMode: FileDialog.SaveFile
        title: qsTranslate("UI", "Save controller backup")
        nameFilters: [qsTranslate("UI", "JSON files (*.json)")]
        defaultSuffix: "json"
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: bridge.exportBackup(selectedFile)
    }
    FileDialog {
        id: openDlg
        fileMode: FileDialog.OpenFile
        title: qsTranslate("UI", "Restore controller backup")
        nameFilters: [qsTranslate("UI", "JSON files (*.json)")]
        onAccepted: bridge.importBackup(selectedFile)
    }
}

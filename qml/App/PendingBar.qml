import QtQuick

// Sticky "unsaved changes" bar for the config pages. Visible only when the
// bridge has queued edits; pushes them to the active profile or discards them.
Rectangle {
    id: bar
    implicitHeight: 46
    visible: bridge.pendingCount > 0
    color: "#241B0E"
    border.color: Theme.warn; border.width: 1; radius: Theme.radius

    Text {
        anchors.left: parent.left; anchors.leftMargin: 14
        anchors.verticalCenter: parent.verticalCenter
        text: qsTranslate("UI", "Unsaved changes: %1").arg(bridge.pendingCount)
        color: Theme.warn
        font.family: Theme.fontFamily; font.pixelSize: Theme.fontM; font.weight: Font.DemiBold
    }

    Row {
        anchors.right: parent.right; anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8

        Rectangle {
            width: dl.implicitWidth + 24; height: 30; radius: 7
            color: dh.hovered ? Theme.cardHover : "transparent"
            border.color: Theme.cardBorder; border.width: 1
            Text { id: dl; anchors.centerIn: parent; text: qsTranslate("UI", "Discard")
                   color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontM }
            HoverHandler { id: dh }
            TapHandler { onTapped: bridge.discardConfig() }
        }
        Rectangle {
            width: sl.implicitWidth + 24; height: 30; radius: 7
            color: Theme.accent
            Text { id: sl; anchors.centerIn: parent
                   // lighting is global: only say "to Profile N" when a profile setting is staged
                   text: bridge.pendingHasProfileEdits ? qsTranslate("UI", "Save to Profile %1").arg(bridge.profile || "?") : qsTranslate("UI", "Save")
                   color: Theme.textOnAccent; font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                   font.weight: Font.DemiBold }
            TapHandler { onTapped: bridge.applyConfig() }
        }
    }
}

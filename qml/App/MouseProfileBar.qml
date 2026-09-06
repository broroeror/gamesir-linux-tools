import QtQuick

// The mouse's onboard profile selector. Two different things have to read at a
// glance here, so they use two different channels:
//   * SELECTED (accent fill) — the profile the pages are editing.
//   * ACTIVE (dot) — the one the mouse is actually running right now.
// They're usually the same profile, but they don't have to be: picking a pill
// costs no device write, so you can edit a profile you aren't currently using.
// Single-click selects, double-click makes it the profile the mouse runs, and
// renaming is the pencil button (file-manager conventions: click to pick, double
// -click to use, explicit action to rename).
Row {
    id: root
    property bool compact: false
    property int renaming: -1                 // sector being renamed, -1 = none

    // Called by the toolbar's pencil: rename whichever profile is selected.
    function startRename() {
        if (mouse.selectedProfile > 0)
            root.renaming = mouse.selectedProfile
    }

    spacing: compact ? 5 : 8
    visible: mouse.present && mouse.profiles.length > 0

    function commitRename(sector, text) {
        root.renaming = -1
        var t = text.trim()
        var cur = ""
        for (var i = 0; i < mouse.profiles.length; i++)
            if (mouse.profiles[i].sector === sector) cur = mouse.profiles[i].name
        if (t !== cur) mouse.renameProfile(sector, t)
    }

    Repeater {
        model: mouse.profiles
        delegate: Rectangle {
            id: pill
            required property var modelData
            readonly property bool sel: mouse.selectedProfile === modelData.sector
            readonly property bool act: mouse.activeProfile === modelData.sector
            readonly property bool editing: root.renaming === modelData.sector

            width: root.compact ? (pill.modelData.name ? 64 : 42) : 96
            height: 32; radius: 8
            color: sel ? Theme.accent : (hov.hovered ? Theme.cardHover : Theme.card)
            border.color: sel ? Qt.lighter(Theme.accent, 1.2) : Theme.cardBorder
            border.width: 1
            Behavior on color { ColorAnimation { duration: 120 } }

            Row {
                anchors.centerIn: parent
                spacing: 5
                // "the mouse is running this one" — kept visible in both states
                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: pill.act
                    width: 6; height: 6; radius: 3
                    color: pill.sel ? "white" : Theme.ok
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: !pill.editing
                    width: Math.min(implicitWidth, (root.compact ? (pill.modelData.name ? 50 : 28) : 74) - (pill.act ? 11 : 0))
                    elide: Text.ElideRight
                    // Compact still shows a NAME when one is set — otherwise
                    // renaming a profile looks like it did nothing at narrow
                    // window widths, which is exactly how it was reported.
                    text: root.compact
                          ? (pill.modelData.name || ("P" + pill.modelData.index))
                          : pill.modelData.label
                    color: pill.sel ? "white" : Theme.textDim
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                    font.weight: pill.sel ? Font.DemiBold : Font.Normal
                }
                TextInput {
                    id: nameEdit
                    anchors.verticalCenter: parent.verticalCenter
                    visible: pill.editing
                    width: (root.compact ? (pill.modelData.name ? 50 : 28) : 74) - (pill.act ? 11 : 0)
                    maximumLength: 24                 // the mouse stores 24 chars
                    color: pill.sel ? "white" : Theme.text
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                    selectByMouse: true
                    onEditingFinished: if (pill.editing) root.commitRename(pill.modelData.sector, text)
                    Keys.onEscapePressed: root.renaming = -1
                    // works however the rename started -- pencil or keyboard
                    onVisibleChanged: if (visible) {
                        text = pill.modelData.name
                        forceActiveFocus()
                        selectAll()
                    }
                }
            }

            HoverHandler { id: hov }
            TapHandler {
                onTapped: if (!pill.editing) mouse.selectProfile(pill.modelData.sector)
                onDoubleTapped: if (!pill.editing) {
                    mouse.selectProfile(pill.modelData.sector)
                    mouse.makeActive(pill.modelData.sector)   // switch the mouse to it
                }
            }
        }
    }
}

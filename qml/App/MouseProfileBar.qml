import QtQuick

// The mouse's onboard profile selector. Two different things have to read at a
// glance here, so they use two different channels:
//   * SELECTED (accent fill) — the profile the pages are editing.
//   * ACTIVE (dot) — the one the mouse is actually running right now.
// They're usually the same profile, but they don't have to be: picking a pill
// costs no device write, so you can edit a profile you aren't currently using.
// Double-click a pill to rename it in place.
Row {
    id: root
    property bool compact: false
    property int renaming: -1                 // sector being renamed, -1 = none

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

            width: root.compact ? 42 : 96
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
                    width: Math.min(implicitWidth, (root.compact ? 28 : 74) - (pill.act ? 11 : 0))
                    elide: Text.ElideRight
                    text: root.compact ? ("P" + pill.modelData.index) : pill.modelData.label
                    color: pill.sel ? "white" : Theme.textDim
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                    font.weight: pill.sel ? Font.DemiBold : Font.Normal
                }
                TextInput {
                    id: nameEdit
                    anchors.verticalCenter: parent.verticalCenter
                    visible: pill.editing
                    width: (root.compact ? 28 : 74) - (pill.act ? 11 : 0)
                    maximumLength: 24                 // the mouse stores 24 chars
                    color: pill.sel ? "white" : Theme.text
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                    selectByMouse: true
                    onEditingFinished: if (pill.editing) root.commitRename(pill.modelData.sector, text)
                    Keys.onEscapePressed: root.renaming = -1
                }
            }

            HoverHandler { id: hov }
            TapHandler {
                onTapped: if (!pill.editing) mouse.selectProfile(pill.modelData.sector)
                onDoubleTapped: {
                    mouse.selectProfile(pill.modelData.sector)
                    root.renaming = pill.modelData.sector
                    nameEdit.text = pill.modelData.name
                    nameEdit.forceActiveFocus(); nameEdit.selectAll()
                }
            }
        }
    }
}

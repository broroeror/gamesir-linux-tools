import QtQuick

// The controller's profile selector. Same two channels as MouseProfileBar, so
// "which profile" reads identically on every device:
//   * SELECTED (accent fill) — the profile the pages are editing.
//   * ACTIVE (dot) — the one the controller is actually running right now.
// On the Cyclone and the 8K, picking a pill also switches the controller to it,
// and the controller's own profile button moves both — so the dot normally sits
// inside the filled pill. On the G7 Pro, editing a bank is independent of the
// active one, so the two can differ. The dot used to be G7-only, which left the
// other controllers with no way to tell "running" from "editing" at a glance.
Row {
    id: root
    // Compact mode shrinks the pills ("P1".."P4") so the top bar fits at narrow
    // window widths; full "Profile N" labels are shown when there's room.
    property bool compact: false
    spacing: compact ? 5 : 8
    Repeater {
        model: bridge.profileCount
        delegate: Rectangle {
            id: pill
            required property int index
            readonly property int n: index + 1
            readonly property bool sel: bridge.profile === n
            readonly property bool act: bridge.activeProfile === n
            width: root.compact ? 40 : Math.max(92, profileText.implicitWidth + 28); height: 32; radius: 8
            color: sel ? Theme.accent
                       : (hov.hovered ? Theme.cardHover : Theme.card)
            border.color: sel ? Qt.lighter(Theme.accent, 1.2) : Theme.cardBorder
            border.width: 1
            Behavior on color { ColorAnimation { duration: 120 } }

            Row {
                anchors.centerIn: parent
                spacing: 5
                // "the controller is running this one" — visible in both states.
                // textOnAccent, not white: on light accents (Emerald, Amber) white
                // drops below a 3:1 contrast ratio — see Theme.textOnAccent.
                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: pill.act
                    width: 6; height: 6; radius: 3
                    color: pill.sel ? Theme.textOnAccent : Theme.ok
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    id: profileText
                    text: root.compact ? ("P" + pill.n) : qsTranslate("UI", "Profile %1").arg(pill.n)
                    color: pill.sel ? Theme.textOnAccent : Theme.textDim
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontM
                    font.weight: pill.sel ? Font.DemiBold : Font.Normal
                }
            }
            HoverHandler { id: hov }
            TapHandler { onTapped: bridge.setProfile(pill.n) }
        }
    }
}

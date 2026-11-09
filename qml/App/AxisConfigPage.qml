import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts

// Sticks / Triggers config, laid out as MIRRORED HALVES: the left side's controls
// hug the left edge and the right side's hug the right edge, with the two curve
// graphs + live views pulled toward the centre — matching the physical controller
// (left-of-screen edits the left stick/trigger, right edits the right). Both halves
// show at once (no side-switching). `sideKeys` supplies the two sides
// ([label, key] each) and `isStick` swaps the stick/trigger specifics.
Item {
    id: page
    property var sideKeys: [["Left Stick", "st"], ["Right Stick", "rs"]]
    property bool isStick: true

    // Cards keep their contents full-size but COMPRESS their vertical padding to
    // fit the window (FitScroll drives Theme.vComp); once maximally compressed it
    // scrolls. The bottom margin permanently reserves the pending-bar's height so
    // making an edit (which shows the bar) never reflows or resizes the page.
    FitScroll {
        id: scroller
        anchors.fill: parent
        anchors.margins: 20
        anchors.bottomMargin: pbar.height + 30
        content: fitBox

        Column {
            id: fitBox
            width: scroller.availableWidth
            spacing: Math.max(6, Math.round(14 * Theme.vComp))

            // ---- no-profile hint -------------------------------------------------
            Card {
                visible: !bridge.profile
                width: parent.width
                title: "No profile selected"
                Text {
                    width: parent.width; wrapMode: Text.WordWrap
                    text: "Pick a profile (1–4) in the top bar to read and edit its settings."
                    color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                }
            }

            // ---- mirrored halves: left side | divider | right side --------------
            RowLayout {
                visible: bridge.profile > 0
                width: parent.width
                spacing: 20

                AxisSide {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    isStick: page.isStick
                    title: page.sideKeys[0][0]
                    side: page.sideKeys[0][1]
                }

                Rectangle {                     // centre divider
                    Layout.fillHeight: true
                    Layout.topMargin: 30; Layout.bottomMargin: 8
                    Layout.preferredWidth: 1
                    color: Theme.cardBorder
                }

                AxisSide {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    isStick: page.isStick
                    title: page.sideKeys[1][0]
                    side: page.sideKeys[1][1]
                    mirror: true
                }
            }
        }
    }

    // Bottom-anchored overlay so it stays visible regardless of content height.
    PendingBar {
        id: pbar
        anchors.left: parent.left; anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 20; anchors.rightMargin: 20; anchors.bottomMargin: 20
    }
}

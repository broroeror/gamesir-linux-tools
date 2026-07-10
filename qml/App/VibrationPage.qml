import QtQuick
import QtQuick.Layouts

// Vibration strength (L/R) + poll rate, staged through the config pending/save
// queue, plus a live rumble test (fires immediately).
Item {
    id: page
    property int poll: 2

    function seed() {
        var c = bridge.config
        if (c.vib_l === undefined) return
        vibL.value = c.vib_l; vibR.value = c.vib_r; page.poll = c.poll
    }
    Component.onCompleted: seed()
    Connections { target: bridge; function onConfigLoaded() { page.seed() } }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        anchors.bottomMargin: pbar.height + 30   // reserve bar space always (no reflow)
        spacing: 14

        Card {
            visible: !bridge.profile
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 460
            title: "No profile selected"
            Text {
                width: parent.width; wrapMode: Text.WordWrap
                text: "Pick a profile (1–4) in the top bar to read and edit its settings."
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
            }
        }

        ColumnLayout {
            visible: bridge.profile > 0
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: 10
            Layout.preferredWidth: 460
            spacing: 16

            Card {
                title: "Vibration strength"; Layout.fillWidth: true
                Row {
                    width: parent.width
                    Text { text: "Left"; color: Theme.textDim
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                    Item { width: parent.width - 70; height: 1 }
                    Text { text: vibL.value + "%"; color: Theme.text
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                }
                AccentSlider {
                    id: vibL; width: parent.width; from: 0; to: 100
                    onMoved: bridge.setScalar("vib_l", value)
                }
                Row {
                    width: parent.width
                    Text { text: "Right"; color: Theme.textDim
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                    Item { width: parent.width - 70; height: 1 }
                    Text { text: vibR.value + "%"; color: Theme.text
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                }
                AccentSlider {
                    id: vibR; width: parent.width; from: 0; to: 100
                    onMoved: bridge.setScalar("vib_r", value)
                }
                PillButton {
                    label: "Test rumble"
                    onClicked: bridge.rumbleTest()
                }
            }

            Card {
                title: "Poll rate"; Layout.fillWidth: true
                Flow {
                    width: parent.width; spacing: 8
                    Repeater {
                        model: bridge.pollRates
                        delegate: PillButton {
                            required property string modelData
                            required property int index
                            label: modelData
                            highlight: page.poll === index
                            onClicked: { page.poll = index; bridge.setPoll(index) }
                        }
                    }
                }
            }
        }
        Item { Layout.fillHeight: true }
    }

    PendingBar {
        id: pbar
        anchors.left: parent.left; anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 20; anchors.rightMargin: 20; anchors.bottomMargin: 20
    }
}

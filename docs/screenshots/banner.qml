import QtQuick
import App 1.0

Rectangle {
    id: root
    width: 1440; height: 360
    gradient: Gradient {
        orientation: Gradient.Vertical
        GradientStop { position: 0.0; color: "#2A0F12" }
        GradientStop { position: 0.55; color: Theme.bg }
        GradientStop { position: 1.0; color: "#0B0A0C" }
    }

    // subtle accent glow behind the wordmark
    Rectangle {
        x: 120; y: -140; width: 600; height: 420; radius: 300
        color: Theme.accent; opacity: 0.07
    }

    Row {
        anchors.verticalCenter: parent.verticalCenter
        anchors.left: parent.left; anchors.leftMargin: 110
        spacing: 44

        Rectangle {
            width: 132; height: 132; radius: 30
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.accent
            Image {
                source: bannerAssets + "glyph-pad.png"
                anchors.centerIn: parent
                width: 84; height: 84
                fillMode: Image.PreserveAspectFit
                smooth: true; mipmap: true
            }
        }

        Column {
            anchors.verticalCenter: parent.verticalCenter
            spacing: 14
            Text {
                text: "DEADBAND"
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: 76; font.weight: Font.Black; font.letterSpacing: 6
            }
            Text {
                text: "Controllers & mice, configured on Linux"
                color: Theme.text; opacity: 0.92
                font.family: Theme.fontFamily
                font.pixelSize: 30
            }
            Row {
                spacing: 12
                Repeater {
                    model: ["reverse-engineered", "local-only", "verified writes"]
                    delegate: Rectangle {
                        required property string modelData
                        radius: 15; height: 30
                        width: chipText.implicitWidth + 26
                        color: "transparent"
                        border.color: Qt.rgba(Theme.text.r, Theme.text.g, Theme.text.b, 0.35)
                        border.width: 1
                        Text {
                            id: chipText
                            anchors.centerIn: parent
                            text: parent.modelData
                            color: Theme.text; opacity: 0.75
                            font.family: Theme.fontFamily; font.pixelSize: 16
                        }
                    }
                }
            }
        }
    }

    // theme swatches: one dot per preset accent — "it themes"
    Row {
        anchors.right: parent.right; anchors.rightMargin: 120
        anchors.verticalCenter: parent.verticalCenter
        spacing: 18
        Repeater {
            model: ["#E03A2F", "#3B82F6", "#2FBF71", "#8B5CF6", "#F59E0B", "#E9ECF1"]
            delegate: Rectangle {
                required property string modelData
                required property int index
                width: 26 + (index === 0 ? 10 : 0); height: width; radius: width / 2
                anchors.verticalCenter: parent.verticalCenter
                color: modelData
                border.color: Qt.rgba(1, 1, 1, 0.25); border.width: 1
            }
        }
    }
}

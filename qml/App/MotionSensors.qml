import QtQuick
import QtQuick.Layouts
import App 1.0

Card {
    id: sensors
    objectName: "motionSensors"
    title: "Live Sensors"
    readonly property var readings: bridge.motionSensors
    readonly property bool streaming: readings.available === true
    headerValue: streaming ? "Streaming · raw counts" : "No live data"

    RowLayout {
        width: parent.width
        spacing: 24
        Repeater {
            model: ["Gyroscope", "Accelerometer"]
            delegate: Column {
                id: group
                required property string modelData
                required property int index
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                spacing: 6
                readonly property var values: index === 0 ? sensors.readings.gyro : sensors.readings.accel

                Text {
                    text: group.modelData
                    color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
                Text {
                    text: group.index === 0 ? "Rotation · near zero at rest"
                                           : "Acceleration · includes gravity"
                    color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
                Repeater {
                    model: ["X", "Y", "Z"]
                    delegate: RowLayout {
                        required property string modelData
                        required property int index
                        width: group.width
                        spacing: 10
                        readonly property int reading: sensors.streaming && group.values
                                                       && group.values.length > index ? group.values[index] : 0
                        Text {
                            text: modelData
                            color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        }
                        Rectangle {
                            id: track
                            Layout.fillWidth: true
                            height: 8; radius: 4; color: Theme.track
                            opacity: sensors.streaming ? 1 : 0.4
                            readonly property real amount: Math.max(-1, Math.min(1, parent.reading / 32768))
                            Rectangle {
                                x: track.amount >= 0 ? track.width / 2 : track.width / 2 + track.width / 2 * track.amount
                                width: Math.abs(track.amount) * track.width / 2
                                height: parent.height; radius: 3; color: Theme.accent
                            }
                            Rectangle {
                                x: parent.width / 2; width: 1; height: parent.height; color: Theme.textDim
                            }
                        }
                        Text {
                            Layout.preferredWidth: 62
                            horizontalAlignment: Text.AlignRight
                            text: sensors.streaming ? parent.reading : "—"
                            color: Theme.text; font.family: "monospace"; font.pixelSize: Theme.fontS
                        }
                    }
                }
            }
        }
    }
    Text {
        width: parent.width; wrapMode: Text.WordWrap
        visible: !sensors.streaming
        text: bridge.configClaimed ? "Waiting for sensor reports…"
                                  : "Choose Configure controller to view live sensors."
        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
    }
}

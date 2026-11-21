import QtQuick
import QtQuick.Shapes
import App 1.0

// Drawing of the original Tarantula Pro for its own pages. Same outline and
// control positions as ControllerView's "tarantula" layout (traced from
// GameSir Connect's render; the 8K and the original share the body), but fed
// by T3ProBridge: face buttons, HOME and the bar show the pad's real LED
// colours, `selected` gets an accent ring, `marked` buttons get a dot (macro /
// remap set), and clicking a control emits picked(name).
Item {
    id: root
    property string selected: ""
    property var marked: []                 // names with a custom setting
    property var colors: t3.ledColors       // {A,B,X,Y,HOME,BAR: "#rrggbb"}
    property var pickable: []               // names that react to clicks ([] = all)
    property bool showBackHint: true
    signal picked(string name)

    readonly property real aspect: 1.6146
    // the shoulder buttons poke above the body outline: reserve a top margin
    readonly property real topPad: width * 0.035
    implicitWidth: 520
    implicitHeight: implicitWidth / aspect + implicitWidth * 0.035

    readonly property var body: [
        [0.088,0.165],[0.105,0.128],[0.132,0.098],[0.168,0.075],[0.212,0.060],
        [0.260,0.054],[0.315,0.054],[0.332,0.062],[0.356,0.095],[0.388,0.135],
        [0.422,0.168],[0.455,0.186],[0.480,0.193],[0.500,0.195],[0.520,0.193],
        [0.545,0.186],[0.578,0.168],[0.612,0.135],[0.644,0.095],[0.668,0.062],
        [0.685,0.054],[0.740,0.054],[0.788,0.060],[0.832,0.075],[0.868,0.098],
        [0.895,0.128],[0.912,0.165],[0.932,0.255],[0.955,0.380],[0.974,0.510],
        [0.988,0.635],[0.995,0.745],[0.995,0.820],[0.989,0.880],[0.977,0.930],
        [0.958,0.968],[0.934,0.990],[0.905,0.997],[0.878,0.994],[0.852,0.976],
        [0.828,0.940],[0.802,0.880],[0.775,0.795],[0.750,0.705],[0.734,0.668],
        [0.714,0.650],[0.688,0.644],[0.312,0.644],[0.286,0.650],[0.266,0.668],
        [0.250,0.705],[0.225,0.795],[0.198,0.880],[0.172,0.940],[0.148,0.976],
        [0.122,0.994],[0.095,0.997],[0.066,0.990],[0.042,0.968],[0.023,0.930],
        [0.011,0.880],[0.005,0.820],[0.005,0.745],[0.012,0.635],[0.026,0.510],
        [0.045,0.380],[0.068,0.255]
    ]
    readonly property var shell: [
        [0.088,0.165],[0.102,0.112],[0.124,0.072],[0.148,0.038],[0.168,0.016],
        [0.192,0.010],[0.225,0.016],[0.285,0.010],[0.335,0.004],[0.410,0.004],
        [0.455,0.016],[0.545,0.016],[0.590,0.004],[0.665,0.004],[0.715,0.010],
        [0.775,0.016],[0.808,0.010],[0.832,0.016],[0.852,0.038],[0.876,0.072],
        [0.898,0.112],[0.912,0.165],[0.700,0.260],[0.300,0.260]
    ]
    // name -> [x, y, diameter, label]  (diameter as a fraction of the width)
    readonly property var ctl: ({
        "LT": [0.150, 0.022, 0.050, "LT"], "RT": [0.850, 0.022, 0.050, "RT"],
        "LB": [0.118, 0.114, 0.050, "LB"], "RB": [0.882, 0.114, 0.050, "RB"],
        "C1": [0.300, 0.112, 0.036, "C1"], "C2": [0.364, 0.175, 0.036, "C2"],
        "C3": [0.636, 0.175, 0.036, "C3"], "C4": [0.700, 0.112, 0.036, "C4"],
        "T1": [0.448, 0.082, 0.036, "T1"], "T3": [0.500, 0.130, 0.036, "T3"],
        "T2": [0.552, 0.082, 0.036, "T2"],
        "VIEW": [0.445, 0.232, 0.033, "⧉"], "CAMERA": [0.500, 0.232, 0.033, "◉"],
        "MENU": [0.555, 0.232, 0.033, "≡"],
        "UP": [0.200, 0.200, 0.044, "▲"], "DOWN": [0.200, 0.362, 0.044, "▼"],
        "LEFT": [0.150, 0.281, 0.044, "◀"], "RIGHT": [0.250, 0.281, 0.044, "▶"],
        "Y": [0.800, 0.182, 0.0645, "Y"], "X": [0.740, 0.278, 0.0645, "X"],
        "B": [0.860, 0.278, 0.0645, "B"], "A": [0.800, 0.374, 0.0645, "A"],
        "L3": [0.3465, 0.480, 0.120, "L3"], "R3": [0.6535, 0.480, 0.120, "R3"],
        "HOME": [0.500, 0.448, 0.068, ""], "M": [0.500, 0.565, 0.036, "M"],
        "L4": [0.422, 0.820, 0.060, "L4"], "R4": [0.578, 0.820, 0.060, "R4"]
    })
    readonly property var faceLabels: t3.layout === 2
        ? ({ "A": "B", "B": "A", "X": "Y", "Y": "X" })   // Switch layout swaps the legends
        : ({})

    function path(pts) {
        var h = canvas.height
        var s = "M " + (pts[0][0] * width) + "," + (pts[0][1] * h)
        for (var i = 1; i < pts.length; i++) s += " L " + (pts[i][0] * width) + "," + (pts[i][1] * h)
        return s + " Z"
    }
    function canPick(n) { return pickable.length === 0 || pickable.indexOf(n) >= 0 }

    Item {
        id: canvas
        y: root.topPad
        width: root.width
        height: root.width / root.aspect
        Shape {
            anchors.fill: parent; antialiasing: true
            ShapePath {
                strokeColor: "#3C414C"; strokeWidth: 1.5; fillColor: "#161920"
                PathSvg { path: root.path(root.shell) }
            }
        }
        Shape {
            anchors.fill: parent; antialiasing: true
            ShapePath {
                strokeColor: "#3C414C"; strokeWidth: 1.5
                fillGradient: LinearGradient {
                    x1: 0; y1: 0; x2: 0; y2: canvas.height
                    GradientStop { position: 0.0; color: "#2B2F3A" }
                    GradientStop { position: 0.55; color: "#1C1F27" }
                    GradientStop { position: 1.0; color: "#101218" }
                }
                PathSvg { path: root.path(root.body) }
            }
        }
        // light bar under the centre buttons
        Rectangle {
            x: root.width * 0.455; y: canvas.height * 0.318
            width: root.width * 0.09; height: Math.max(4, canvas.height * 0.022); radius: height / 2
            color: root.colors.BAR || "#33373F"
            border.width: root.selected === "BAR" ? 2 : 0; border.color: Theme.accent
            TapHandler { enabled: root.canPick("BAR"); onTapped: root.picked("BAR") }
        }

        Repeater {
            model: Object.keys(root.ctl)
            delegate: Item {
                required property string modelData
                readonly property var c: root.ctl[modelData]
                readonly property bool face: ["A", "B", "X", "Y"].indexOf(modelData) >= 0
                readonly property bool sel: root.selected === modelData
                readonly property real d: c[2] * root.width
                x: c[0] * root.width - d / 2; y: c[1] * canvas.height - d / 2
                width: d; height: d
                opacity: root.canPick(modelData) ? 1 : 0.45
                Rectangle {
                    anchors.fill: parent; radius: width / 2
                    color: modelData === "HOME" ? (root.colors.HOME || "#2a2e37")
                           : (modelData === "L3" || modelData === "R3") ? "#22262E" : "#2A2E37"
                    border.width: sel ? 3 : (face ? 2 : 1)
                    border.color: sel ? Theme.accent : (face ? (root.colors[modelData] || "#555") : "#4A505C")
                }
                Text {
                    anchors.centerIn: parent
                    text: root.faceLabels[modelData] || c[3]
                    color: face ? (root.colors[modelData] || Theme.text) : (sel ? Theme.accent : Theme.textDim)
                    font.family: Theme.fontFamily; font.weight: Font.DemiBold
                    font.pixelSize: Math.max(8, Math.min(parent.width * 0.45, 15))
                }
                Rectangle {     // custom setting marker
                    visible: root.marked.indexOf(modelData) >= 0
                    width: 8; height: 8; radius: 4; color: Theme.ok
                    anchors.right: parent.right; anchors.top: parent.top
                }
                HoverHandler { id: hh; enabled: root.canPick(modelData); cursorShape: Qt.PointingHandCursor }
                TapHandler { enabled: root.canPick(modelData); onTapped: root.picked(modelData) }
                Rectangle {
                    visible: hh.hovered && !sel
                    anchors.fill: parent; anchors.margins: -3; radius: width / 2
                    color: "transparent"; border.width: 1; border.color: Theme.textDim
                }
            }
        }
        Text {
            visible: root.showBackHint
            anchors.horizontalCenter: parent.horizontalCenter
            y: canvas.height * 0.70
            text: qsTranslate("UI", "L4 / R4, C1–C4 and T1–T3 are on the back of the controller")
            color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
        }

    }
}

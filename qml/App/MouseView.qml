import QtQuick
import QtQuick.Shapes

// Stylised top-down Logitech G502 X, matched to the real device. Built the SAME way
// as ControllerView: a normalized point-path scaled to px (dark graphite body), with
// theme-token accents so it recolors live with the app palette. Each of the 11
// buttons is a clickable marker; the SELECTED one (the button being edited) and any
// HOVERED one light up in Theme.accent, so the mouse config pages can drive and
// reflect selection here.
//
// Silhouette traced from a CC-BY 3D model — "Logitech G502 X Lightspeed" by Okopchi
// (https://skfb.ly/p8PWQ, CC-BY 4.0). Attribution required; see CREDITS.
Item {
    id: root
    readonly property real aspect: 0.589            // width/height, from the 3D model
    implicitWidth: 260
    implicitHeight: implicitWidth / aspect

    // ---- API ---------------------------------------------------------------
    // The button being configured (device button index, or -1 for none). A page
    // binds this to highlight the active button; clicking a marker emits
    // buttonActivated so the page can open that button's editor.
    property int selectedIndex: -1
    signal buttonActivated(int index, string name)

    // Device button table: index -> display name + normalized position. Indices
    // match the onboard-profile button slots (0=primary … 10=prev-dpi). Pages read
    // this for their button list so the map lives in ONE place.
    readonly property var buttons: [
        { i: 0,  name: "Left Click",     nx: 0.400, ny: 0.140, r: 0.043 },
        { i: 1,  name: "Right Click",    nx: 0.730, ny: 0.130, r: 0.043 },
        { i: 2,  name: "Middle Click",   nx: 0.566, ny: 0.250, wheel: true },
        { i: 6,  name: "Scroll L/T",     nx: 0.492, ny: 0.250, r: 0.021 },
        { i: 7,  name: "Scroll R/T",     nx: 0.640, ny: 0.250, r: 0.021 },
        { i: 9,  name: "DPI Up",         nx: 0.240, ny: 0.130, r: 0.030 },
        { i: 10, name: "DPI Down",       nx: 0.200, ny: 0.270, r: 0.030 },
        { i: 8,  name: "Profile Cycle",  nx: 0.566, ny: 0.400, r: 0.032 },
        { i: 4,  name: "DPI Shift",      nx: 0.160, ny: 0.440, r: 0.037 },
        { i: 5,  name: "Forward",        nx: 0.120, ny: 0.560, r: 0.031 },
        { i: 3,  name: "Backward",       nx: 0.090, ny: 0.640, r: 0.031 }
    ]

    // Traced silhouette, normalized 0..1 (front = top, thumb wing = left).
    readonly property var bodyPts: [
        [0.559,1.000],[0.700,0.986],[0.837,0.938],[0.844,0.923],[0.837,0.900],
        [0.854,0.886],[0.863,0.886],[0.883,0.900],[0.940,0.846],[0.973,0.786],
        [0.993,0.712],[1.000,0.403],[0.989,0.316],[0.951,0.241],[0.913,0.143],
        [0.865,0.079],[0.756,0.033],[0.651,0.000],[0.477,0.022],[0.285,0.056],
        [0.225,0.081],[0.130,0.254],[0.096,0.376],[0.103,0.411],[0.058,0.451],
        [0.000,0.687],[0.007,0.710],[0.127,0.769],[0.181,0.827],[0.210,0.868],
        [0.280,0.938],[0.416,0.986]
    ]
    // Catmull-Rom -> cubic-bezier smoothing over the closed loop; returns an SVG path.
    function bodyPath(w, h) {
        var p = root.bodyPts, n = p.length
        function X(i) { return p[((i % n) + n) % n][0] * w }
        function Y(i) { return p[((i % n) + n) % n][1] * h }
        var d = "M " + X(0) + "," + Y(0) + " "
        for (var i = 0; i < n; i++) {
            var c1x = X(i)   + (X(i + 1) - X(i - 1)) / 6
            var c1y = Y(i)   + (Y(i + 1) - Y(i - 1)) / 6
            var c2x = X(i + 1) - (X(i + 2) - X(i)) / 6
            var c2y = Y(i + 1) - (Y(i + 2) - Y(i)) / 6
            d += "C " + c1x + "," + c1y + " " + c2x + "," + c2y
                 + " " + X(i + 1) + "," + Y(i + 1) + " "
        }
        return d + "Z"
    }

    // ----------------------------------------------------------------- body
    Shape {
        anchors.fill: parent
        antialiasing: true
        ShapePath {
            strokeColor: "#3C414C"
            strokeWidth: 1.4
            fillGradient: LinearGradient {
                x1: 0; y1: 0; x2: 0; y2: root.height
                GradientStop { position: 0.0;  color: "#2B2F3A" }
                GradientStop { position: 0.55; color: "#1C1F27" }
                GradientStop { position: 1.0;  color: "#101218" }
            }
            PathSvg { path: root.bodyPath(root.width, root.height) }
        }
    }

    // center seam between the two click halves
    Shape {
        anchors.fill: parent
        antialiasing: true
        ShapePath {
            strokeColor: "#454B57"
            strokeWidth: 1
            fillColor: "transparent"
            PathSvg {
                path: "M " + (0.565 * root.width) + "," + (0.045 * root.height)
                      + " C " + (0.55 * root.width) + "," + (0.13 * root.height)
                      + " " + (0.55 * root.width) + "," + (0.21 * root.height)
                      + " " + (0.566 * root.width) + "," + (0.275 * root.height)
            }
        }
    }

    // ----------------------------------------------------------------- buttons
    Repeater {
        model: root.buttons
        delegate: Item {
            id: mk
            required property var modelData
            readonly property bool isWheel: modelData.wheel === true
            readonly property bool active: root.selectedIndex === modelData.i || ma.containsMouse
            x: root.width * modelData.nx - width / 2
            y: root.height * modelData.ny - height / 2
            width:  isWheel ? root.width * 0.075 : root.width * (modelData.r * 2)
            height: isWheel ? root.width * 0.16  : width

            Rectangle {
                anchors.fill: parent
                radius: mk.isWheel ? width * 0.45 : width / 2
                color: mk.active ? Theme.accent : "#2A2E38"
                border.color: mk.active ? Qt.lighter(Theme.accent, 1.3) : "#3E4350"
                border.width: Math.max(1, width * 0.06)
                Behavior on color { ColorAnimation { duration: 90 } }
            }
            // scroll-wheel grip lines
            Column {
                anchors.centerIn: parent
                spacing: parent.height * 0.14
                visible: mk.isWheel
                Repeater {
                    model: mk.isWheel ? 3 : 0
                    delegate: Rectangle {
                        width: mk.width * 0.44; height: Math.max(1, mk.height * 0.05)
                        radius: height / 2; color: "#3E4350"
                    }
                }
            }
            MouseArea {
                id: ma
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.buttonActivated(mk.modelData.i, mk.modelData.name)
            }
        }
    }
}

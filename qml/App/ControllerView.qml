import QtQuick
import QtQuick.Shapes

// Stylised vector Cyclone 2 (Shadow Black), matched to the real controller:
// dark body, a glowing RING around the guide button (Home zone), a small Profile
// LED low-centre, and two long curved grip light bars. The body outline is
// traced from the controller silhouette so control positions match calibration.
// Four RGB zones bind to bridge.lightColors, so this one view drives both the
// Buttons (input highlights) and Lights (zone colours) pages.
Item {
    id: root

    // ---- per-model drawings -------------------------------------------------
    // Each layout = outline (+ optional top shell), where every control sits, and
    // element sizes, all normalised 0..1 to the drawing's box. The bridge says
    // which one the connected controller uses (bridge.diagram).
    //   cyclone   -- the original drawing, traced from the Cyclone 2 (the 8K and
    //                G7 Pro use it too). Numbers unchanged from before layouts.
    //   tarantula -- traced from GameSir Connect's render of the Tarantula Pro 8K:
    //                body and shell from its pixels, every control from the white
    //                callout dot GameSir puts on it (face buttons, sticks and D-pad
    //                from their own shapes, since their dots sit on the edge).
    readonly property var cycloneLayout: ({
        key: "cyclone", aspect: 1.4379,
        body: [
        [0.2927,0.0],[0.32,0.0026],[0.3491,0.0327],[0.4755,0.0275],[0.6491,0.0327],
        [0.6764,0.0039],[0.7055,0.0],[0.7736,0.0196],[0.8218,0.0601],[0.8564,0.1242],
        [0.8936,0.2497],[0.9509,0.4693],[0.9864,0.6458],[0.9982,0.7464],[0.9982,0.8261],
        [0.9855,0.8967],[0.9645,0.9438],[0.9355,0.9778],[0.8955,0.9974],[0.83,0.915],
        [0.7391,0.7608],[0.69,0.7216],[0.6645,0.7163],[0.3345,0.7163],[0.2982,0.7268],
        [0.26,0.7608],[0.1691,0.915],[0.1036,0.9974],[0.0764,0.9869],[0.0445,0.9582],
        [0.0218,0.919],[0.0064,0.868],[0.0,0.7634],[0.0218,0.5935],[0.0755,0.3595],
        [0.1427,0.1242],[0.1627,0.081],[0.1909,0.0444],[0.2182,0.0235]
    ],
        shell: [],
        pos: {
            "A": [0.756, 0.373], "B": [0.823, 0.275], "X": [0.689, 0.275], "Y": [0.755, 0.177],
            "LS": [0.235, 0.285], "RS": [0.627, 0.492],
            "Dpad Up": [0.355, 0.463], "Dpad Down": [0.355, 0.537],
            "Dpad Left": [0.317, 0.500], "Dpad Right": [0.393, 0.500], "Dpad": [0.355, 0.500],
            "View": [0.425, 0.265], "Menu": [0.566, 0.265],
            "LT": [0.305, 0.050], "LB": [0.405, 0.050], "RB": [0.595, 0.050], "RT": [0.695, 0.050],
            // L5/R5 are extra SHOULDER buttons on the top edge, between the bumpers
            // (G7 Pro and 8K alike, confirmed by hand) -- not underside paddles.
            "L5": [0.465, 0.050], "R5": [0.535, 0.050],
            "L4": [0.390, 0.660], "R4": [0.610, 0.660],
            // the small button below Home: Share on the 8K, Capture on the Cyclone
            "Home": [0.50, 0.165], "Share": [0.50, 0.280], "Capture": [0.50, 0.280],
            "LED": [0.50, 0.405]
        },
        size: { stick: 0.115, face: 0.072, dpad: 0.11, mini: 0.042, home: 0.085 }
    })
    readonly property var tarantulaLayout: ({
        key: "tarantula", aspect: 1.6146,
        // Symmetric, corner-smoothed body and top-shell outlines for the Tarantula 8K
        body: [
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
        ],
        shell: [
            [0.088,0.165],[0.102,0.112],[0.124,0.072],[0.148,0.038],[0.168,0.016],
            [0.192,0.010],[0.225,0.016],[0.285,0.010],[0.335,0.004],[0.410,0.004],
            [0.455,0.016],[0.545,0.016],[0.590,0.004],[0.665,0.004],[0.715,0.010],
            [0.775,0.016],[0.808,0.010],[0.832,0.016],[0.852,0.038],[0.876,0.072],
            [0.898,0.112],[0.912,0.165],[0.700,0.260],[0.300,0.260]
        ],
        pos: {
            "LT": [0.150, 0.022],
            "RT": [0.850, 0.022],
            "LB": [0.118, 0.114],
            "RB": [0.882, 0.114],
            "C1": [0.300, 0.112],
            "C2": [0.364, 0.175],
            "C3": [0.636, 0.175],
            "C4": [0.700, 0.112],
            "T1": [0.448, 0.082],
            "T3": [0.500, 0.130],
            "T2": [0.552, 0.082],
            "View": [0.445, 0.232],
            "Share": [0.500, 0.232],
            "Screenshot": [0.500, 0.232],
            "Menu": [0.555, 0.232],
            "Dpad Up": [0.200, 0.182],
            "Dpad Down": [0.200, 0.380],
            "Dpad Left": [0.138, 0.281],
            "Dpad Right": [0.262, 0.281],
            "Dpad": [0.200, 0.281],
            "Y": [0.800, 0.182],
            "X": [0.740, 0.278],
            "B": [0.860, 0.278],
            "A": [0.800, 0.374],
            "LS": [0.3465, 0.480],
            "RS": [0.6535, 0.480],
            "Home": [0.500, 0.448],
            "M": [0.500, 0.565],
            "LED": [0.500, 0.335],
            "L4": [0.422, 0.820],
            "R4": [0.578, 0.820]
        },
        size: { stick: 0.138, face: 0.0645, dpad: 0.142, mini: 0.033, home: 0.076, paddle: 0.092 }
    })
    readonly property var lay: bridge.diagram === "tarantula" ? tarantulaLayout : cycloneLayout
    // A picture the user chose for this model (Settings → Appearance) replaces
    // the drawn body; `template` draws the plain outline even when one is set,
    // for the template export. Back to the drawing if the file won't load.
    property bool template: false
    readonly property string customPicture: template ? ""
        : (Theme.ctrlPictures[bridge.controllerName] || "")
    readonly property bool pictureShown: customPicture !== "" && picture.status === Image.Ready
    readonly property bool isTar: lay.key === "tarantula"
    function at(n) { return root.lay.pos[n] !== undefined ? root.lay.pos[n] : [0, 0] }

    readonly property real aspect: lay.aspect
    implicitWidth: 560
    implicitHeight: implicitWidth / aspect

    // ---- remap indicator API (used by the Buttons page) --------------------
    // Set highlightSource to the control being edited and highlightTarget to the
    // control it's mapped to; the view pulses a ring on the source, rings the
    // target, and draws a dashed link between them. "Default" target = unmapped
    // (source ring only); "Disabled" = a ⊘ badge on the source, no link.
    property string highlightSource: ""
    property string highlightTarget: ""
    readonly property bool remapMode: highlightSource !== ""

    readonly property var ctrlPos: lay.pos
    function hasPos(n) { return n !== undefined && n !== "" && root.ctrlPos[n] !== undefined }
    function supportsControl(n) { return bridge.remapSources.indexOf(n) !== -1 }
    readonly property point srcPt: hasPos(highlightSource)
        ? Qt.point(ctrlPos[highlightSource][0] * width, ctrlPos[highlightSource][1] * height)
        : Qt.point(0, 0)
    readonly property point tgtPt: hasPos(highlightTarget)
        ? Qt.point(ctrlPos[highlightTarget][0] * width, ctrlPos[highlightTarget][1] * height)
        : Qt.point(0, 0)

    function btn(name) { return bridge.buttons[name] === true }
    function zone(i) { return bridge.lightColors[i] !== undefined
                              ? bridge.lightColors[i] : "#000000" }
    function isLit(c) { return (c.r + c.g + c.b) > 0.05 }

    function bodyPath(w, h, pts) {
        var p = pts
        var s = "M " + (p[0][0]*w) + "," + (p[0][1]*h)
        for (var i = 1; i < p.length; i++) s += " L " + (p[i][0]*w) + "," + (p[i][1]*h)
        return s + " Z"
    }

    // ----------------------------------------------------------------- body
    // Tarantula: the top shell (bumpers + centre panel) sits behind the body,
    // which is how the real controller is built -- a shade darker than the body
    // so it still reads as its own part in the shared slate style.
    Image {
        id: picture
        anchors.fill: parent
        source: root.customPicture
        fillMode: Image.Stretch            // the template is the drawing's own box
        asynchronous: true; smooth: true; mipmap: true
        sourceSize.width: root.width * 2   // crisp on HiDPI without holding a huge image
        visible: root.pictureShown
    }
    Shape {
        anchors.fill: parent
        antialiasing: true
        visible: root.lay.shell.length > 0 && !root.pictureShown
        ShapePath {
            strokeColor: "#3C414C"; strokeWidth: 1.5
            fillColor: "#161920"
            PathSvg { path: root.lay.shell.length ? root.bodyPath(root.width, root.height, root.lay.shell) : "" }
        }
    }
    Shape {
        anchors.fill: parent
        antialiasing: true
        visible: !root.pictureShown
        ShapePath {
            strokeColor: "#3C414C"
            strokeWidth: 1.5
            fillGradient: LinearGradient {
                x1: 0; y1: 0; x2: 0; y2: root.height
                GradientStop { position: 0.0;  color: "#2B2F3A" }
                GradientStop { position: 0.55; color: "#1C1F27" }
                GradientStop { position: 1.0;  color: "#101218" }
            }
            PathSvg { path: root.bodyPath(root.width, root.height, root.lay.body) }
        }
    }

    // ============================ light zones ============================
    // Curved grip light bar (left, or mirrored to the right grip).
    component GripLight: Shape {
        id: grip
        property color col: "#000000"
        property bool mirror: false
        readonly property bool lit: root.isLit(col)
        anchors.fill: parent
        antialiasing: true
        function fx(nx) { return (mirror ? 1 - nx : nx) * root.width }
        function fy(ny) { return ny * root.height }
        // soft bloom underneath
        ShapePath {
            strokeColor: grip.lit ? Qt.rgba(grip.col.r, grip.col.g, grip.col.b, 0.28)
                                  : "transparent"
            strokeWidth: root.width * 0.06
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            startX: grip.fx(0.19); startY: grip.fy(0.33)
            PathQuad { x: grip.fx(0.17); y: grip.fy(0.83)
                       controlX: grip.fx(0.06); controlY: grip.fy(0.58) }
        }
        // bright core
        ShapePath {
            strokeColor: grip.lit ? grip.col : "#33373F"
            strokeWidth: root.width * 0.022
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            startX: grip.fx(0.19); startY: grip.fy(0.33)
            PathQuad { x: grip.fx(0.17); y: grip.fy(0.83)
                       controlX: grip.fx(0.06); controlY: grip.fy(0.58) }
        }
    }
    // Grip light bars + the separate profile-LED dot are the Cyclone's addressable
    // RGB; models without it (e.g. the 8K, whose only indicator is the home ring)
    // shouldn't show them.
    readonly property bool hasZoneRGB: bridge.lightingStyle === "cyclone_keyframe"
    GripLight { col: root.zone(0); mirror: false; visible: root.hasZoneRGB }   // Left grip
    GripLight { col: root.zone(1); mirror: true;  visible: root.hasZoneRGB }   // Right grip

    // Profile LED (small dot, low-centre) — Cyclone only
    Item {
        visible: root.hasZoneRGB
        property color col: root.zone(2)
        property bool lit: root.isLit(col)
        x: root.width * root.at("LED")[0] - width / 2
        y: root.height * root.at("LED")[1] - height / 2
        width: root.width * 0.028; height: width
        Rectangle {
            anchors.centerIn: parent; width: parent.width * 2.2; height: width
            radius: width / 2; color: parent.col
            opacity: parent.lit ? 0.3 : 0; visible: parent.lit
        }
        Rectangle {
            anchors.fill: parent; radius: width / 2
            color: parent.lit ? parent.col : "#33373F"
            Behavior on color { ColorAnimation { duration: 120 } }
        }
    }

    // Home: glowing ring around the guide button (top-centre) -- Cyclone drawing
    Item {
        visible: !root.isTar
        property color col: root.zone(3)
        property bool lit: root.isLit(col)
        x: root.width * root.at("Home")[0] - width / 2
        y: root.height * root.at("Home")[1] - height / 2
        width: root.width * root.lay.size.home; height: width
        Rectangle {              // bloom
            anchors.centerIn: parent; width: parent.width * 1.6; height: width
            radius: width / 2; color: parent.col
            opacity: parent.lit ? 0.22 : 0; visible: parent.lit
        }
        Rectangle {              // the ring
            anchors.fill: parent; radius: width / 2; color: "transparent"
            border.color: parent.lit ? parent.col : "#33373F"
            border.width: Math.max(2, width * 0.13)
            Behavior on border.color { ColorAnimation { duration: 120 } }
        }
        Rectangle {              // guide button in the middle
            anchors.centerIn: parent; width: parent.width * 0.46; height: width
            radius: width / 2; color: "#15171D"
            border.color: "#3A3E48"; border.width: 1
        }
    }

    // ============================ controls ============================
    component FaceBtn: Item {
        property real nx: 0
        property real ny: 0
        property string glyph: ""
        property color gcol: "#888"
        property bool on: false
        property real dia: root.lay.size.face
        x: root.width * nx - width / 2
        y: root.height * ny - height / 2
        width: root.width * dia; height: width
        Rectangle {
            anchors.fill: parent; radius: width / 2
            color: parent.on ? Theme.accent : "#2A2E38"
            border.color: parent.on ? Qt.lighter(Theme.accent, 1.3) : "#3E4350"
            border.width: Math.max(1, width * 0.04)
            Behavior on color { ColorAnimation { duration: 80 } }
        }
        Text {
            anchors.centerIn: parent; text: parent.glyph
            color: parent.on ? Theme.textOnAccent : parent.gcol
            font.family: Theme.fontFamily; font.bold: true
            font.pixelSize: parent.width * 0.46
        }
    }

    component Stick: Item {
        property real nx: 0
        property real ny: 0
        property real ax: 0
        property real ay: 0
        property bool clicked: false
        property real dia: root.lay.size.stick
        x: root.width * nx - width / 2
        y: root.height * ny - height / 2
        width: root.width * dia; height: width
        Rectangle {
            anchors.fill: parent; radius: width / 2
            color: "#262A33"
            border.color: "#3E4350"
            border.width: Math.max(1, width * 0.03)
        }
        Rectangle {
            width: parent.width * 0.56; height: width; radius: width / 2
            color: parent.clicked ? Theme.accent : "#454A56"
            border.color: "#555B68"; border.width: 1
            x: parent.width / 2 - width / 2 + parent.ax * parent.width * 0.20
            y: parent.height / 2 - height / 2 + parent.ay * parent.width * 0.20
            Behavior on color { ColorAnimation { duration: 80 } }
            // NO Behavior on x/y. Stick position updates every 16ms (the input
            // timer runs at ~60Hz), so a 40ms tween never finished -- each new
            // sample restarted it, leaving the dot permanently chasing a target
            // it never reached, ~40ms behind the thumb, with its velocity reset
            // every frame. It read as a low frame rate. The data is already at
            // display rate; tweening it can only add lag. (The D-pad below DOES
            // animate, and should: `dir` is a discrete nine-position state that
            // changes rarely, so there the tween is a glide, not a chase.)
        }
    }

    component MiniBtn: Item {
        property real nx: 0
        property real ny: 0
        property bool on: false
        property string glyph: ""
        property real dia: root.lay.size.mini
        x: root.width * nx - width / 2
        y: root.height * ny - height / 2
        width: root.width * dia; height: width
        Rectangle {
            anchors.fill: parent; radius: width / 2
            color: parent.on ? Theme.accent : "#2A2E38"
            border.color: "#3E4350"
            Behavior on color { ColorAnimation { duration: 80 } }
        }
        Text {
            anchors.centerIn: parent; text: parent.glyph
            color: parent.on ? Theme.textOnAccent : "#9AA0AC"
            font.pixelSize: parent.width * 0.5
        }
    }

    // D-pad (cross + direction highlight)
    Item {
        property string dir: bridge.dpad
        property real sz: root.width * root.lay.size.dpad
        x: root.width * root.at("Dpad")[0] - sz / 2
        y: root.height * root.at("Dpad")[1] - sz / 2
        width: sz; height: sz
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            width: parent.width * 0.34; height: parent.height; radius: width * 0.2
            color: "#2A2E38"; border.color: "#3E4350"
        }
        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width; height: parent.height * 0.34; radius: height * 0.2
            color: "#2A2E38"; border.color: "#3E4350"
        }
        Rectangle {
            anchors.centerIn: parent
            width: parent.width * 0.34 - 2; height: parent.height * 0.34
            color: "#2A2E38"
        }
        Rectangle {
            visible: parent.dir !== "neutral"
            color: Theme.accent; radius: width * 0.08
            width: parent.width * 0.30; height: parent.height * 0.30
            x: parent.width / 2 - width / 2
               + (parent.dir.indexOf("left") >= 0 ? -parent.width * 0.34
                  : parent.dir.indexOf("right") >= 0 ? parent.width * 0.34 : 0)
            y: parent.height / 2 - height / 2
               + (parent.dir.indexOf("up") >= 0 ? -parent.height * 0.34
                  : parent.dir.indexOf("down") >= 0 ? parent.height * 0.34 : 0)
            Behavior on x { NumberAnimation { duration: 60 } }
            Behavior on y { NumberAnimation { duration: 60 } }
        }
    }

    Stick { nx: root.at("LS")[0]; ny: root.at("LS")[1]; ax: bridge.leftStickX;  ay: bridge.leftStickY
            clicked: root.btn("ls") }
    Stick { nx: root.at("RS")[0]; ny: root.at("RS")[1]; ax: bridge.rightStickX; ay: bridge.rightStickY
            clicked: root.btn("rs") }

    FaceBtn { nx: root.at("A")[0]; ny: root.at("A")[1]; glyph: "A"; gcol: "#5BBF6A"; on: root.btn("a") }
    FaceBtn { nx: root.at("B")[0]; ny: root.at("B")[1]; glyph: "B"; gcol: "#E06A6A"; on: root.btn("b") }
    FaceBtn { nx: root.at("X")[0]; ny: root.at("X")[1]; glyph: "X"; gcol: "#5B96E0"; on: root.btn("x") }
    FaceBtn { nx: root.at("Y")[0]; ny: root.at("Y")[1]; glyph: "Y"; gcol: "#E0C04A"; on: root.btn("y") }

    MiniBtn { nx: root.at("View")[0]; ny: root.at("View")[1]; glyph: "❐"; on: root.btn("view") }
    MiniBtn { nx: root.at("Menu")[0]; ny: root.at("Menu")[1]; glyph: "☰"; on: root.btn("menu") }

    // The button below Home reports as Share on the vendor input channel (#50,
    // tested on an Aimlabs G7 Pro 8K); the Tarantula's sits between View and Menu.
    MiniBtn { nx: root.at("Share")[0]; ny: root.at("Share")[1]; glyph: root.isTar ? "○" : "⛶"
              on: root.btn("share") }

    // ---- Tarantula-only parts ----
    // The GameSir-logo Home button between the sticks (with its status LED above it)
    // and the M function button below it.
    Item {
        visible: root.isTar
        property bool on: root.btn("home")
        x: root.width * root.at("Home")[0] - width / 2
        y: root.height * root.at("Home")[1] - height / 2
        width: root.width * root.lay.size.home; height: width
        Rectangle {
            anchors.fill: parent; radius: width / 2
            color: parent.on ? Theme.accent : "#2A2E38"
            border.color: parent.on ? Qt.lighter(Theme.accent, 1.3) : "#3E4350"
            border.width: Math.max(1, width * 0.06)
            Behavior on color { ColorAnimation { duration: 80 } }
        }
        Rectangle {
            anchors.centerIn: parent; width: parent.width * 0.62; height: width
            radius: width / 2; color: parent.on ? Theme.accent : "#1C1F27"
            Behavior on color { ColorAnimation { duration: 80 } }
        }
        Text {
            anchors.centerIn: parent; text: "G"
            color: parent.on ? Theme.textOnAccent : "#9AA0AC"
            font.bold: true; font.pixelSize: parent.width * 0.4
        }
    }
    MiniBtn {
        visible: root.isTar
        nx: root.at("M")[0]; ny: root.at("M")[1]
        glyph: "M"; on: root.btn("m")
    }
    Rectangle {
        visible: root.isTar
        width: root.width * 0.012; height: width * 0.6; radius: height / 2; color: "#454A56"
        x: root.width * root.at("LED")[0] - width / 2; y: root.height * root.at("LED")[1] - height / 2
    }

    // ===================== off-body edge markers =========================
    // Bumpers / triggers (top edge) and back paddles (low-centre) aren't part of
    // the moulded front body, so we label them. They brighten when involved in
    // the current remap so every source/target can be shown on the graphic.
    component EdgeMarker: Item {
        property string name: ""
        property real nx: root.at(name)[0]
        property real ny: root.at(name)[1]
        property real scale_: 1.0         // the Tarantula's dense top row uses smaller tags
        property bool on: false          // live input pressed (lights red like the face buttons)
        readonly property bool hot: root.highlightSource === name || root.highlightTarget === name
        readonly property bool active: hot || on
        x: root.width * nx - width / 2
        y: root.height * ny - height / 2
        width: root.width * 0.078 * scale_; height: root.width * 0.042 * scale_
        Rectangle {
            anchors.fill: parent; radius: height / 2
            color: parent.active ? Theme.accent : "#20232B"
            border.color: parent.active ? Qt.lighter(Theme.accent, 1.3) : "#3A3E48"
            border.width: 1
            Behavior on color { ColorAnimation { duration: 80 } }
        }
        Text {
            anchors.centerIn: parent; text: parent.name
            color: parent.active ? Theme.textOnAccent : Theme.textDim
            font.family: Theme.fontFamily; font.bold: true; font.pixelSize: parent.height * 0.5
        }
    }
    EdgeMarker { name: "LT"; on: bridge.leftTrigger > 0.06 }
    EdgeMarker { name: "LB"; on: root.btn("lb") }
    EdgeMarker { name: "RB"; on: root.btn("rb") }
    EdgeMarker { name: "RT"; on: bridge.rightTrigger > 0.06 }
    EdgeMarker { name: "L4"; on: root.btn("l4"); visible: !root.isTar && root.supportsControl(name) }
    EdgeMarker { name: "L5"; on: root.btn("l5"); visible: root.supportsControl(name) }
    EdgeMarker { name: "R5"; on: root.btn("r5"); visible: root.supportsControl(name) }
    EdgeMarker { name: "R4"; on: root.btn("r4"); visible: !root.isTar && root.supportsControl(name) }

    // Tarantula's programmable buttons: C1-C4 along the face, T1-T3 on the top
    // panel. Small labelled tags at the spots GameSir's own render marks.
    Repeater {
        model: root.isTar ? ["C1", "C2", "C3", "C4", "T1", "T2", "T3"] : []
        delegate: EdgeMarker {
            required property string modelData
            name: modelData; scale_: 0.72
            on: root.btn(modelData.toLowerCase())
            visible: root.supportsControl(modelData)
        }
    }
    // Tarantula back paddles, drawn in the notch the way GameSir's app shows them.
    Repeater {
        model: root.isTar ? ["L4", "R4"] : []
        delegate: Item {
            required property string modelData
            readonly property bool active: root.highlightSource === modelData
                                           || root.highlightTarget === modelData
                                           || root.btn(modelData.toLowerCase())
            visible: root.supportsControl(modelData)
            x: root.width * root.at(modelData)[0] - width / 2
            y: root.height * root.at(modelData)[1] - height / 2
            width: root.width * root.lay.size.paddle; height: width * 0.86
            Rectangle {
                anchors.fill: parent; radius: width * 0.28
                color: parent.active ? Theme.accent : "#20232B"
                border.color: parent.active ? Qt.lighter(Theme.accent, 1.3) : "#3A3E48"
                border.width: Math.max(1, width * 0.05)
                Behavior on color { ColorAnimation { duration: 80 } }
            }
            Text {
                anchors.centerIn: parent; text: parent.modelData
                color: parent.active ? Theme.textOnAccent : Theme.textDim
                font.family: Theme.fontFamily; font.bold: true; font.pixelSize: parent.height * 0.32
            }
        }
    }

    // ===================== remap source → target link ====================
    // Dashed connector (drawn under the rings).
    Shape {
        anchors.fill: parent; antialiasing: true
        visible: root.remapMode && root.hasPos(root.highlightSource)
                 && root.hasPos(root.highlightTarget)
        ShapePath {
            strokeColor: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.85)
            strokeWidth: Math.max(2, root.width * 0.007)
            strokeStyle: ShapePath.DashLine
            dashPattern: [4, 3]
            fillColor: "transparent"
            startX: root.srcPt.x; startY: root.srcPt.y
            PathLine { x: root.tgtPt.x; y: root.tgtPt.y }
        }
    }

    function ringScale(name) {
        if (!root.isTar) return 1.0
        if (name === "C1" || name === "C2" || name === "C3" || name === "C4"
                || name === "T1" || name === "T2" || name === "T3"
                || name === "View" || name === "Share" || name === "Screenshot"
                || name === "Menu" || name === "M")
            return 0.62
        if (name === "Dpad Up" || name === "Dpad Down"
                || name === "Dpad Left" || name === "Dpad Right"
                || name === "A" || name === "B" || name === "X" || name === "Y")
            return 0.80
        return 0.90
    }
    readonly property real tgtRingDia: root.width * 0.11 * ringScale(root.highlightTarget)
    readonly property real srcRingDia: root.width * 0.13 * ringScale(root.highlightSource)

    // Dark halos under both rings, so they stay visible on a bright body
    // (the Tarantula is orange; the accent is red).
    Rectangle {
        visible: root.remapMode && root.hasPos(root.highlightTarget)
        width: root.tgtRingDia + root.width * 0.012; height: width; radius: width / 2
        x: root.tgtPt.x - width / 2; y: root.tgtPt.y - height / 2
        color: "transparent"; border.color: "#000000"; opacity: 0.55
        border.width: Math.max(2, root.tgtRingDia * 0.08) + root.width * 0.006
    }

    // Target ring (static, light).
    Rectangle {
        visible: root.remapMode && root.hasPos(root.highlightTarget)
        width: root.tgtRingDia; height: width; radius: width / 2
        x: root.tgtPt.x - width / 2; y: root.tgtPt.y - height / 2
        color: "transparent"; opacity: 0.9
        border.color: "#F2F3F5"; border.width: Math.max(2, root.tgtRingDia * 0.08)
    }

    // Source ring (pulsing accent).
    Rectangle {
        id: srcRing
        visible: root.remapMode && root.hasPos(root.highlightSource)
        width: root.srcRingDia; height: width; radius: width / 2
        x: root.srcPt.x - width / 2; y: root.srcPt.y - height / 2
        color: "transparent"
        border.color: Theme.accent; border.width: Math.max(2, root.srcRingDia * 0.095)
        SequentialAnimation on scale {
            running: srcRing.visible; loops: Animation.Infinite
            NumberAnimation { from: 0.82; to: 1.12; duration: 700; easing.type: Easing.InOutQuad }
            NumberAnimation { from: 1.12; to: 0.82; duration: 700; easing.type: Easing.InOutQuad }
        }
    }

    // "Disabled" badge on the source when the control is mapped to nothing.
    Text {
        visible: root.remapMode && root.highlightTarget === "Disabled"
                 && root.hasPos(root.highlightSource)
        text: "⊘"; color: Theme.accent; font.bold: true
        font.pixelSize: root.width * 0.07
        x: root.srcPt.x + root.width * 0.05; y: root.srcPt.y - root.height * 0.13
    }
}

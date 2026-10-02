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
            "Home": [0.50, 0.165], "LED": [0.50, 0.405]
        },
        size: { stick: 0.115, face: 0.072, dpad: 0.11, mini: 0.042, home: 0.085 }
    })
    readonly property var tarantulaLayout: ({
        key: "tarantula", aspect: 1.6146,
        // mirrored from the cleaner right half about the centre line (the
        // controller is symmetric; the left edge was crossed by GameSir's callout
        // lines), then corner-smoothed
        body: [[0.004,0.748],[0.0078,0.7173],[0.0223,0.6903],[0.0298,0.4863],[0.0664,0.2623],[0.0901,0.1517],[0.0965,0.1396],[0.1089,0.1324],[0.1234,0.1106],[0.1556,0.0845],[0.196,0.0663],[0.2449,0.0556],[0.2798,0.0556],[0.2884,0.059],[0.296,0.0522],[0.3196,0.0489],[0.3395,0.076],[0.3535,0.1018],[0.3605,0.0996],[0.3696,0.1107],[0.3809,0.1318],[0.4159,0.1706],[0.439,0.1914],[0.447,0.2882],[0.4567,0.2823],[0.4669,0.2675],[0.4728,0.2639],[0.4798,0.265],[0.4922,0.284],[0.4987,0.2882],[0.5089,0.2817],[0.5207,0.2654],[0.5298,0.264],[0.5444,0.2846],[0.5508,0.2882],[0.5573,0.2079],[0.5605,0.1933],[0.6126,0.1388],[0.6234,0.1254],[0.6352,0.1037],[0.6481,0.0991],[0.6583,0.0794],[0.6825,0.0463],[0.7035,0.0526],[0.7116,0.0608],[0.7207,0.053],[0.7266,0.0556],[0.7578,0.0556],[0.8067,0.0665],[0.8556,0.0918],[0.8707,0.1043],[0.8922,0.1343],[0.9019,0.137],[0.9089,0.1485],[0.9191,0.1881],[0.9331,0.2606],[0.9723,0.5017],[0.9793,0.6876],[0.9804,0.6975],[0.9938,0.7192],[0.9952,0.7257],[0.9977,0.7751],[0.9971,0.8118],[0.9969,0.8168],[0.9922,0.8732],[0.9863,0.9059],[0.9766,0.9386],[0.9632,0.9622],[0.9513,0.9767],[0.9358,0.989],[0.9169,0.9965],[0.8847,0.9964],[0.8626,0.9855],[0.8454,0.9686],[0.8159,0.9176],[0.7901,0.8427],[0.7508,0.6922],[0.739,0.6654],[0.7218,0.6504],[0.7056,0.6458],[0.6745,0.6457],[0.6653,0.6366],[0.6562,0.645],[0.6497,0.6424],[0.3481,0.6424],[0.3427,0.6447],[0.3336,0.6366],[0.3239,0.6457],[0.2917,0.6459],[0.2728,0.6533],[0.2567,0.6725],[0.2433,0.7087],[0.2185,0.8105],[0.2008,0.8722],[0.1836,0.918],[0.1583,0.9631],[0.147,0.9767],[0.1315,0.989],[0.1126,0.9965],[0.0815,0.9965],[0.0497,0.9791],[0.0293,0.95],[0.0196,0.9271],[0.011,0.8925],[0.0067,0.8627],[0.0024,0.7952],[0.0036,0.7542]],
        shell: [[0.0019,0.748],[0.0056,0.7173],[0.0202,0.6903],[0.0277,0.4863],[0.046,0.3701],[0.0519,0.3452],[0.0578,0.2984],[0.0788,0.1892],[0.0874,0.1532],[0.097,0.135],[0.1024,0.1306],[0.1094,0.1011],[0.1277,0.0717],[0.1411,0.0557],[0.1487,0.0378],[0.1583,0.0281],[0.1653,0.0158],[0.182,0.0105],[0.2046,0.0104],[0.2137,0.0197],[0.2218,0.0208],[0.275,0.0113],[0.2825,0.0138],[0.2933,0.0071],[0.3169,0.0069],[0.3239,0.0035],[0.3895,0.0035],[0.3954,0.0009],[0.4164,0.0036],[0.4535,0.0174],[0.5492,0.0173],[0.5825,0.0035],[0.6433,0.0035],[0.6513,0.0069],[0.6734,0.0035],[0.6809,0.0069],[0.7089,0.0071],[0.7196,0.0138],[0.7427,0.0139],[0.7761,0.0208],[0.7831,0.0203],[0.7965,0.0106],[0.8196,0.0104],[0.8358,0.0162],[0.8427,0.0296],[0.8497,0.0352],[0.8605,0.0586],[0.8696,0.0674],[0.8884,0.0977],[0.8949,0.129],[0.903,0.1355],[0.9105,0.1473],[0.9207,0.1857],[0.9449,0.3154],[0.9745,0.5017],[0.9815,0.6876],[0.9825,0.6975],[0.996,0.7192],[0.9974,0.7257],[0.9999,0.7751],[0.9993,0.8118],[0.9991,0.8168],[0.9917,0.8911],[0.9831,0.9262],[0.9745,0.9475],[0.9594,0.9715],[0.9427,0.9888],[0.9191,0.9999],[0.8868,0.9998],[0.868,0.9922],[0.8519,0.9791],[0.8411,0.9657],[0.8137,0.9176],[0.7879,0.8427],[0.7497,0.6954],[0.7401,0.6714],[0.7282,0.6574],[0.7083,0.6494],[0.6761,0.6491],[0.6659,0.64],[0.6573,0.6482],[0.6519,0.6458],[0.3503,0.6458],[0.3444,0.6484],[0.3347,0.64],[0.3255,0.6492],[0.2944,0.6493],[0.2798,0.6531],[0.261,0.6689],[0.2454,0.7087],[0.2207,0.8105],[0.204,0.8689],[0.1917,0.9039],[0.1755,0.9386],[0.1556,0.9708],[0.1374,0.9889],[0.1153,0.9998],[0.0836,1.0],[0.0637,0.9922],[0.0481,0.9797],[0.0277,0.951],[0.018,0.9287],[0.0094,0.8951],[0.0046,0.8627],[0.0002,0.7952],[0.0014,0.7542]],
        pos: {
            "LT": [0.1456, 0.0163],
            "RT": [0.8467, 0.0194],
            "LB": [0.1153, 0.1125],
            "RB": [0.8957, 0.1184],
            "C1": [0.2983, 0.1125],
            "C2": [0.3632, 0.1753],
            "C3": [0.6312, 0.1764],
            "C4": [0.6959, 0.1125],
            "T1": [0.4514, 0.0837],
            "T3": [0.4929, 0.1267],
            "T2": [0.5503, 0.0833],
            "View": [0.4441, 0.225],
            "Share": [0.4978, 0.2253],
            "Menu": [0.5516, 0.2253],
            "Dpad Up": [0.1996, 0.1757],
            "Dpad Down": [0.1998, 0.3851],
            "Dpad Left": [0.1333, 0.283],
            "Dpad Right": [0.263, 0.2833],
            "Dpad": [0.2, 0.2812],
            "Y": [0.7972, 0.1819],
            "X": [0.7383, 0.2764],
            "B": [0.8598, 0.2799],
            "A": [0.8015, 0.3733],
            "LS": [0.3465, 0.4802],
            "RS": [0.6535, 0.4802],
            "Home": [0.5, 0.4479],
            "LED": [0.5, 0.3351],
            "L4": [0.4146, 0.9351],
            "R4": [0.583, 0.9361]
        },
        size: { stick: 0.1398, face: 0.0645, dpad: 0.1505, mini: 0.0323, home: 0.0774, paddle: 0.1075 }
    })
    readonly property var lay: bridge.diagram === "tarantula" ? tarantulaLayout : cycloneLayout
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
    // Tarantula: the black top shell (bumpers + centre panel) sits behind the
    // orange body, which is how the real controller is built.
    Shape {
        anchors.fill: parent
        antialiasing: true
        visible: root.lay.shell.length > 0
        ShapePath {
            strokeColor: "#2C2C30"; strokeWidth: 1.5
            fillColor: "#1B1B1D"
            PathSvg { path: root.lay.shell.length ? root.bodyPath(root.width, root.height, root.lay.shell) : "" }
        }
    }
    Shape {
        anchors.fill: parent
        antialiasing: true
        ShapePath {
            strokeColor: root.isTar ? "#B33A12" : "#3C414C"
            strokeWidth: 1.5
            fillGradient: LinearGradient {
                x1: 0; y1: 0; x2: 0; y2: root.height
                GradientStop { position: 0.0;  color: root.isTar ? "#FF6229" : "#2B2F3A" }
                GradientStop { position: 0.55; color: root.isTar ? "#F44C1A" : "#1C1F27" }
                GradientStop { position: 1.0;  color: root.isTar ? "#D8410F" : "#101218" }
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
            color: parent.on ? Theme.accent : (root.isTar ? "#121214" : "#2A2E38")
            border.color: parent.on ? Qt.lighter(Theme.accent, 1.3) : (root.isTar ? "#2A2A2E" : "#3E4350")
            border.width: Math.max(1, width * 0.04)
            Behavior on color { ColorAnimation { duration: 80 } }
        }
        Text {
            anchors.centerIn: parent; text: parent.glyph
            // the Tarantula's face buttons are black with plain white letters
            color: parent.on ? Theme.textOnAccent : (root.isTar ? "#F2F2F2" : parent.gcol)
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
            color: root.isTar ? "#0E0E10" : "#262A33"
            border.color: root.isTar ? "#2A2A2E" : "#3E4350"
            border.width: Math.max(1, width * 0.03)
        }
        Rectangle {
            width: parent.width * 0.56; height: width; radius: width / 2
            color: parent.clicked ? Theme.accent : (root.isTar ? "#26262A" : "#454A56")
            border.color: root.isTar ? "#38383E" : "#555B68"; border.width: 1
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
            color: parent.on ? Theme.accent : (root.isTar ? "#121214" : "#2A2E38")
            border.color: root.isTar ? "#2A2A2E" : "#3E4350"
            Behavior on color { ColorAnimation { duration: 80 } }
        }
        Text {
            anchors.centerIn: parent; text: parent.glyph
            color: parent.on ? Theme.textOnAccent : (root.isTar ? "#D8D8D8" : "#9AA0AC")
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
            color: root.isTar ? "#121214" : "#2A2E38"; border.color: root.isTar ? "#2A2A2E" : "#3E4350"
        }
        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width; height: parent.height * 0.34; radius: height * 0.2
            color: root.isTar ? "#121214" : "#2A2E38"; border.color: root.isTar ? "#2A2A2E" : "#3E4350"
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

    // ---- Tarantula-only parts ----
    // The small round button between View and Menu, and the GameSir-logo Home
    // button between the sticks (with its status LED above it).
    MiniBtn { visible: root.isTar; nx: root.at("Share")[0]; ny: root.at("Share")[1]; glyph: "○" }
    Item {
        visible: root.isTar
        x: root.width * root.at("Home")[0] - width / 2
        y: root.height * root.at("Home")[1] - height / 2
        width: root.width * root.lay.size.home; height: width
        Rectangle { anchors.fill: parent; radius: width / 2; color: "#F2F2F2"; border.color: "#121214"; border.width: Math.max(1, width * 0.08) }
        Rectangle { anchors.centerIn: parent; width: parent.width * 0.62; height: width; radius: width / 2; color: "#121214" }
        Text { anchors.centerIn: parent; text: "G"; color: "#F2F2F2"; font.bold: true; font.pixelSize: parent.width * 0.4 }
    }
    Rectangle {
        visible: root.isTar
        width: root.width * 0.012; height: width * 0.6; radius: height / 2; color: "#F2F2F2"
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
                color: parent.active ? Theme.accent : "#E8481A"
                border.color: parent.active ? Qt.lighter(Theme.accent, 1.3) : "#A9350E"
                border.width: Math.max(1, width * 0.05)
                Behavior on color { ColorAnimation { duration: 80 } }
            }
            Text {
                anchors.centerIn: parent; text: parent.modelData
                color: parent.active ? Theme.textOnAccent : "#FFF3EC"
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

    // Dark halos under both rings, so they stay visible on a bright body
    // (the Tarantula is orange; the accent is red).
    Rectangle {
        visible: root.remapMode && root.hasPos(root.highlightTarget)
        width: root.width * 0.11 + root.width * 0.012; height: width; radius: width / 2
        x: root.tgtPt.x - width / 2; y: root.tgtPt.y - height / 2
        color: "transparent"; border.color: "#000000"; opacity: 0.55
        border.width: Math.max(2, root.width * 0.009) + root.width * 0.006
    }

    // Target ring (static, light).
    Rectangle {
        visible: root.remapMode && root.hasPos(root.highlightTarget)
        width: root.width * 0.11; height: width; radius: width / 2
        x: root.tgtPt.x - width / 2; y: root.tgtPt.y - height / 2
        color: "transparent"; opacity: 0.9
        border.color: "#F2F3F5"; border.width: Math.max(2, root.width * 0.009)
    }

    // Source ring (pulsing accent).
    Rectangle {
        id: srcRing
        visible: root.remapMode && root.hasPos(root.highlightSource)
        width: root.width * 0.13; height: width; radius: width / 2
        x: root.srcPt.x - width / 2; y: root.srcPt.y - height / 2
        color: "transparent"
        border.color: Theme.accent; border.width: Math.max(2, root.width * 0.013)
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

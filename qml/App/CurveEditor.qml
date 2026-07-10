import QtQuick

// Response-curve graph with three draggable control points (each 0..255). The
// rendered curve runs (0,0) -> p0 -> p1 -> p2 -> (255,255). Emits edited(points)
// when a drag finishes. setPoints() loads without emitting.
Item {
    id: ce
    property var points: [[40, 41], [128, 128], [215, 214]]
    property bool interactive: true
    // Curve kind (0 linear, 1 concave, 2 S, 3 custom) + intensity. The S-curve is
    // a true rounded sigmoid (a Catmull-Rom through its 3 points renders a flat
    // middle); the others draw a smooth spline through the control points.
    property int curveKind: 3
    property int intensity: 100
    signal edited(var pts)
    onCurveKindChanged: canvas.requestPaint()
    onIntensityChanged: canvas.requestPaint()

    // Themed graph colors. Canvas paints imperatively (can't bind inside onPaint),
    // so mirror the theme tokens as properties and repaint when they change.
    property color gBg:    Theme.bg
    property color gGrid:  Theme.cardBorder
    property color gCurve: Theme.accent
    onGBgChanged: canvas.requestPaint()
    onGGridChanged: canvas.requestPaint()
    onGCurveChanged: canvas.requestPaint()

    implicitWidth: 200; implicitHeight: 200

    function setPoints(p) {
        var q = []
        for (var i = 0; i < p.length; i++) q.push([p[i][0], p[i][1]])
        points = q
        canvas.requestPaint()
    }
    function px(x) { return x / 255 * canvas.width }
    function py(y) { return (1 - y / 255) * canvas.height }
    onPointsChanged: canvas.requestPaint()

    // Output fraction (0..1) for an input fraction (0..1), matching the drawn
    // curve — used by the live-stick preview so it reflects the actual response,
    // not just the raw physical position. S-curve uses the same sigmoid as the
    // graph; the others sample the piecewise line through the control points
    // (which is what the firmware LUT interpolates, so it matches the device).
    function sampleFrac(xf) {
        xf = Math.max(0, Math.min(1, xf))
        if (curveKind === 2) {
            if (xf <= 0) return 0
            if (xf >= 1) return 1
            var a = Math.pow(2, (intensity - 50) / 50)
            return Math.pow(xf, a) / (Math.pow(xf, a) + Math.pow(1 - xf, a))
        }
        var xs = 255 * xf
        var knots = [[0, 0]].concat(points).concat([[255, 255]])
        for (var i = 1; i < knots.length; i++) {
            if (xs <= knots[i][0]) {
                var x0 = knots[i - 1][0], y0 = knots[i - 1][1]
                var x1 = knots[i][0], y1 = knots[i][1]
                var t = (x1 > x0) ? (xs - x0) / (x1 - x0) : 0
                return Math.max(0, Math.min(1, (y0 + t * (y1 - y0)) / 255))
            }
        }
        return 1
    }

    Canvas {
        id: canvas
        anchors.fill: parent
        onPaint: {
            var ctx = getContext('2d')
            ctx.clearRect(0, 0, width, height)
            ctx.fillStyle = ce.gBg; ctx.fillRect(0, 0, width, height)
            ctx.strokeStyle = ce.gGrid; ctx.lineWidth = 1
            for (var i = 1; i < 4; i++) {
                var gx = i / 4 * width
                ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, height); ctx.stroke()
                var gy = i / 4 * height
                ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(width, gy); ctx.stroke()
            }
            ctx.strokeStyle = ce.gCurve; ctx.lineWidth = 2; ctx.beginPath()
            if (ce.curveKind === 2) {
                // S-curve: symmetric sigmoid y = x^a/(x^a+(1-x)^a).
                // a = 2^((intensity-50)/50): 2 = steep-middle standard S,
                // 1 = linear, 0.5 = flat-middle inverse.
                var a = Math.pow(2, (ce.intensity - 50) / 50)
                for (var i = 0; i <= 64; i++) {
                    var x = i / 64
                    var y = (x <= 0) ? 0 : (x >= 1) ? 1
                            : Math.pow(x, a) / (Math.pow(x, a) + Math.pow(1 - x, a))
                    if (i === 0) ctx.moveTo(ce.px(x * 255), ce.py(y * 255))
                    else ctx.lineTo(ce.px(x * 255), ce.py(y * 255))
                }
            } else {
                // Smooth Catmull-Rom spline through (0,0)..points..(255,255).
                var pts = [[0, 0]].concat(ce.points).concat([[255, 255]])
                var g = [pts[0]].concat(pts).concat([pts[pts.length - 1]])
                ctx.moveTo(ce.px(pts[0][0]), ce.py(pts[0][1]))
                for (var s = 1; s < g.length - 2; s++) {
                    var p0 = g[s - 1], p1 = g[s], p2 = g[s + 1], p3 = g[s + 2]
                    for (var t = 1; t <= 16; t++) {
                        var u = t / 16, u2 = u * u, u3 = u2 * u
                        var cx = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * u
                                  + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * u2
                                  + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * u3)
                        var cy = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * u
                                  + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * u2
                                  + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * u3)
                        ctx.lineTo(ce.px(Math.max(0, Math.min(255, cx))),
                                   ce.py(Math.max(0, Math.min(255, cy))))
                    }
                }
            }
            ctx.stroke()
        }
    }

    Repeater {
        model: ce.interactive ? 3 : 0
        delegate: Rectangle {
            required property int index
            width: 12; height: 12; radius: 6
            color: Theme.accent; border.color: "white"; border.width: 2
            x: ce.px(ce.points[index][0]) - 6
            y: ce.py(ce.points[index][1]) - 6
        }
    }

    MouseArea {
        anchors.fill: parent
        enabled: ce.interactive
        property int active: -1
        function toData(mx, my) {
            return [Math.max(0, Math.min(255, Math.round(mx / width * 255))),
                    Math.max(0, Math.min(255, Math.round((1 - my / height) * 255)))]
        }
        function move(mx, my) {
            var d = toData(mx, my)
            var p = ce.points.slice()
            var lo = active > 0 ? p[active - 1][0] + 1 : 1
            var hi = active < 2 ? p[active + 1][0] - 1 : 254
            d[0] = Math.max(lo, Math.min(hi, d[0]))
            p[active] = d; ce.points = p; canvas.requestPaint()
        }
        onPressed: {
            var best = 0, bd = 1e9
            for (var i = 0; i < 3; i++) {
                var dx = mouseX - ce.px(ce.points[i][0]), dy = mouseY - ce.py(ce.points[i][1])
                var dd = dx * dx + dy * dy
                if (dd < bd) { bd = dd; best = i }
            }
            active = best; move(mouseX, mouseY)
        }
        onPositionChanged: if (pressed) move(mouseX, mouseY)
        onReleased: ce.edited(ce.points)
    }
}

import QtQuick

// Response-curve graph with three draggable control points (each 0..255). The
// rendered curve runs (0,0) -> p0 -> p1 -> p2 -> (255,255). Emits edited(points)
// when a drag finishes. setPoints() loads without emitting.
Item {
    id: ce
    property var points: [[40, 41], [128, 128], [215, 214]]
    property bool interactive: true
    signal edited(var pts)

    implicitWidth: 200; implicitHeight: 200

    function setPoints(p) {
        var q = []
        for (var i = 0; i < p.length; i++) q.push([p[i][0], p[i][1]])
        points = q
        canvas.requestPaint()
    }
    function px(x) { return x / 255 * canvas.width }
    function py(y) { return (1 - y / 255) * canvas.height }

    Canvas {
        id: canvas
        anchors.fill: parent
        onPaint: {
            var ctx = getContext('2d')
            ctx.clearRect(0, 0, width, height)
            ctx.fillStyle = '#15171D'; ctx.fillRect(0, 0, width, height)
            ctx.strokeStyle = '#2A2E38'; ctx.lineWidth = 1
            for (var i = 1; i < 4; i++) {
                var gx = i / 4 * width
                ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, height); ctx.stroke()
                var gy = i / 4 * height
                ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(width, gy); ctx.stroke()
            }
            var pts = [[0, 0]].concat(ce.points).concat([[255, 255]])
            ctx.strokeStyle = '#E03A2F'; ctx.lineWidth = 2; ctx.beginPath()
            for (var j = 0; j < pts.length; j++) {
                var X = ce.px(pts[j][0]), Y = ce.py(pts[j][1])
                if (j === 0) ctx.moveTo(X, Y); else ctx.lineTo(X, Y)
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

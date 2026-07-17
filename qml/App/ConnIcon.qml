import QtQuick
import App 1.0

// Connection-type indicator, read at a glance like a network status icon:
//   wired === true   -> a USB plug
//   wired === false  -> wifi-style bands (the controller is on its dongle)
//   wired === null   -> unknown (G7-family / nothing detected): a neutral dot
// `live` false dims it — the device is a dongle with no controller behind it.
Item {
    id: icon
    property var wired: null
    property bool live: true
    property color tint: Theme.textDim

    width: 14; height: 14
    opacity: live ? 1 : 0.45

    Canvas {
        id: cv
        anchors.fill: parent
        // Canvas can't bind these inside onPaint, so mirror + repaint on change.
        property var w_: icon.wired
        property color c_: icon.tint
        onW_Changed: requestPaint()
        onC_Changed: requestPaint()

        onPaint: {
            var ctx = getContext('2d')
            ctx.clearRect(0, 0, width, height)
            ctx.strokeStyle = c_; ctx.fillStyle = c_
            ctx.lineWidth = 1.4; ctx.lineCap = 'round'
            var cx = width / 2

            if (w_ === true) {                       // ---- USB plug
                ctx.beginPath()                      // cable
                ctx.moveTo(cx, height - 0.5); ctx.lineTo(cx, height - 4.5)
                ctx.stroke()
                // plain rects: Qt's roundedRect() wants BOTH radii and silently
                // draws nothing if you pass one — and at 6x5px rounding is invisible
                ctx.fillRect(cx - 3.2, height - 9.5, 6.4, 5)    // body
                ctx.fillRect(cx - 2.6, height - 12.5, 1.5, 3)   // prongs
                ctx.fillRect(cx + 1.1, height - 12.5, 1.5, 3)
            } else if (w_ === false) {               // ---- wireless bands
                var by = height - 2.2
                ctx.beginPath()                      // emitter dot
                ctx.arc(cx, by, 1.5, 0, 2 * Math.PI); ctx.fill()
                var radii = [4.4, 7.2]               // bands radiating up
                for (var i = 0; i < radii.length; i++) {
                    ctx.beginPath()
                    ctx.arc(cx, by, radii[i], -Math.PI * 0.80, -Math.PI * 0.20)
                    ctx.stroke()
                }
            } else {                                 // ---- unknown
                ctx.globalAlpha = 0.6
                ctx.beginPath()
                ctx.arc(cx, height / 2, 2.2, 0, 2 * Math.PI); ctx.fill()
            }
        }
    }
}

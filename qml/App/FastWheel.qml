import QtQuick

// Mouse-wheel scrolling at a normal desktop pace (same component as Ambience/vpn-split).
// Qt's Flickable default is sluggish here: on KWin/Wayland a hi-res wheel (the
// G502 X, free-spin or not) arrives as device "touchpad", 7-8 events per notch
// whose angle deltas sum to 120 but whose pixel deltas sum to ~15, and Flickable
// scrolls by the pixel deltas.
// So wheel vs touchpad is decided by the scroll PHASE: touchpads report a gesture
// (begin / update / end), wheels report none. Wheels go by notches (the system's
// "lines per scroll" x Theme.wheelPixelsPerLine, eased); touchpads follow the
// fingers 1:1 via their pixel deltas.
WheelHandler {
    id: wheel
    property Flickable flick   // set explicitly: inside a Flickable, parent is its contentItem
    property real notchPixels: Qt.styleHints.wheelScrollLines * Theme.wheelPixelsPerLine
    property real goal: 0
    target: null
    acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
    onWheel: (ev) => handle(ev)

    function handle(ev) {
        if (!flick) return
        const touchpad = ev.phase !== Qt.NoScrollPhase
        const dy = touchpad ? (ev.pixelDelta.y !== 0 ? ev.pixelDelta.y : ev.angleDelta.y / 8)
                            : ev.angleDelta.y / 120 * notchPixels
        if (dy === 0) return
        const top = flick.originY
        const max = Math.max(top, top + flick.contentHeight - flick.height)
        const from = ease.running ? goal : flick.contentY
        goal = Math.max(top, Math.min(max, from - dy))
        if (touchpad) { ease.stop(); flick.contentY = goal }
        else { ease.to = goal; ease.restart() }
    }

    property NumberAnimation ease: NumberAnimation {
        target: wheel.flick; property: "contentY"
        duration: 160; easing.type: Easing.OutCubic
    }
}

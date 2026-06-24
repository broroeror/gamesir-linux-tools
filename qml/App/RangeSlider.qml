import QtQuick

// Dual-handle range slider (e.g. deadzone min..max). Emits moved(lo, hi) live.
Item {
    id: r
    property real from: 0
    property real to: 100
    property real lo: 0
    property real hi: 100
    signal moved(real lo, real hi)

    implicitHeight: 18
    function frac(v) { return to > from ? (v - from) / (to - from) : 0 }

    Rectangle {
        id: track
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width; height: 6; radius: 3; color: Theme.track
        Rectangle {
            x: r.frac(r.lo) * parent.width
            width: (r.frac(r.hi) - r.frac(r.lo)) * parent.width
            height: parent.height; radius: 3; color: Theme.accent
        }
    }
    Repeater {
        model: 2
        delegate: Rectangle {
            required property int index
            width: 16; height: 16; radius: 8; color: "white"
            border.color: Theme.accent; border.width: 2
            y: (r.height - height) / 2
            x: r.frac(index === 0 ? r.lo : r.hi) * track.width - width / 2
        }
    }
    MouseArea {
        anchors.fill: parent
        property int active: -1
        function val(mx) { return r.from + Math.max(0, Math.min(1, mx / track.width)) * (r.to - r.from) }
        function apply(v) {
            v = Math.round(v)
            if (active === 0) r.lo = Math.min(v, r.hi)
            else r.hi = Math.max(v, r.lo)
            r.moved(r.lo, r.hi)
        }
        onPressed: {
            var v = val(mouseX)
            active = Math.abs(v - r.lo) <= Math.abs(v - r.hi) ? 0 : 1
            apply(v)
        }
        onPositionChanged: if (pressed) apply(val(mouseX))
    }
}

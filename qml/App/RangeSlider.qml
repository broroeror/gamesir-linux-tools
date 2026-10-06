import QtQuick

// Dual-handle range slider (e.g. deadzone min..max). Emits moved(lo, hi) live.
//
// Below the track, Min and Max are also TYPABLE: dragging to an exact value is
// hard at 0.1% steps (the 8K and Tarantula store deadzones at 16-bit resolution),
// so each end has a small number box. Enter or clicking away commits -- snapped
// to `step`, clamped to the range and to `minGap` from the other end -- and
// emits moved() exactly like a drag; Esc cancels. Every range slider in the app
// gets this, so the behaviour is the same on every page and controller.
Item {
    id: r
    property real from: 0
    property real to: 100
    property real lo: 0
    property real hi: 100
    // Snap increment. 1 = whole units (Cyclone %); 0.1 lets the 8K expose its finer
    // (16-bit) deadzone resolution.
    property real step: 1
    // Handles can never collapse onto each other: the firmware bricks a stick
    // when deadzone min == max, and equal handles can't be pulled back apart.
    property real minGap: 1
    property bool showInputs: true
    property string unit: "%"
    signal moved(real lo, real hi)

    readonly property int decimals: step < 1 ? 1 : 0
    implicitHeight: trackArea.height + (showInputs ? inputs.height + 8 : 0)
    function frac(v) { return to > from ? (v - from) / (to - from) : 0 }
    function snap(v) {
        v = Math.round(v / r.step) * r.step
        return Math.round(v * 10) / 10           // kill float drift at 0.1 steps
    }
    function setLo(v) { r.lo = Math.max(r.from, Math.min(snap(v), r.hi - r.minGap)); r.moved(r.lo, r.hi) }
    function setHi(v) { r.hi = Math.min(r.to, Math.max(snap(v), r.lo + r.minGap)); r.moved(r.lo, r.hi) }

    Item {
        id: trackArea
        width: parent.width; height: 18
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
                y: (trackArea.height - height) / 2
                x: r.frac(index === 0 ? r.lo : r.hi) * track.width - width / 2
            }
        }
        MouseArea {
            anchors.fill: parent
            property int active: -1
            function val(mx) { return r.from + Math.max(0, Math.min(1, mx / track.width)) * (r.to - r.from) }
            function apply(v) {
                // Enforce the gap so the handles can never sit on top of each other.
                if (active === 0) r.setLo(v)
                else r.setHi(v)
            }
            onPressed: {
                var v = val(mouseX)
                // When the handles are close (incl. a broken collapsed range), pick by
                // drag direction so either one can always be pulled back out.
                if (Math.abs(r.hi - r.lo) <= r.minGap + 1) active = v >= r.lo ? 1 : 0
                else active = Math.abs(v - r.lo) <= Math.abs(v - r.hi) ? 0 : 1
                apply(v)
            }
            onPositionChanged: if (pressed) apply(val(mouseX))
        }
    }

    // ---- typable ends ----
    component NumberBox: Row {
        id: nb
        property string label: ""
        property real value: 0
        signal committed(real v)
        spacing: 6
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: nb.label; color: Theme.textDim
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
        }
        Rectangle {
            width: 64; height: 24; radius: 6
            color: Theme.button
            border.color: field.activeFocus ? Theme.accent : Theme.cardBorder; border.width: 1
            TextInput {
                id: field
                anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 22
                verticalAlignment: TextInput.AlignVCenter; horizontalAlignment: TextInput.AlignRight
                color: Theme.text; selectionColor: Theme.accent; selectedTextColor: Theme.textOnAccent
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                selectByMouse: true; clip: true
                inputMethodHints: Qt.ImhFormattedNumbersOnly
                validator: DoubleValidator { bottom: r.from; top: r.to; decimals: r.decimals
                                             notation: DoubleValidator.StandardNotation }
                // show the live value unless the user is typing
                text: nb.value.toFixed(r.decimals)
                Binding on text { when: !field.activeFocus; value: nb.value.toFixed(r.decimals) }
                function commit() {
                    var v = parseFloat(text)
                    if (!isNaN(v) && Math.abs(v - nb.value) > 1e-9) nb.committed(v)
                    text = nb.value.toFixed(r.decimals)
                }
                onAccepted: { commit(); focus = false }
                onActiveFocusChanged: if (!activeFocus) commit()
                Keys.onEscapePressed: { text = nb.value.toFixed(r.decimals); focus = false }
            }
            Text {
                anchors.right: parent.right; anchors.rightMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                text: r.unit; color: Theme.textDim
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
            }
        }
    }
    Item {
        id: inputs
        visible: r.showInputs
        anchors.top: trackArea.bottom; anchors.topMargin: 8
        width: parent.width; height: 24
        NumberBox { anchors.left: parent.left; label: "Min"; value: r.lo; onCommitted: (v) => r.setLo(v) }
        NumberBox { anchors.right: parent.right; label: "Max"; value: r.hi; onCommitted: (v) => r.setHi(v) }
    }
}

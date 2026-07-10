import QtQuick
import QtQuick.Controls as QQC

// A vertical scroll area that first COMPRESSES its cards (via Theme.vComp) to fit
// the available height, and only scrolls once it can't compress any further — so a
// tall page packs more rows as the window shrinks (down to a floor) WITHOUT
// shrinking fonts/controls. Point `content` at the inner Column so it can read the
// natural height. Only the visible page's FitScroll drives the (global) vComp.
QQC.ScrollView {
    id: scroller
    property Item content: null
    property real floor: 0.45          // most-compressed vComp before it just scrolls

    clip: true
    contentWidth: availableWidth
    QQC.ScrollBar.horizontal.policy: QQC.ScrollBar.AlwaysOff

    // COMPRESS-ONLY fit: from a full-size baseline, only ever LOWER vComp until the
    // content fits. Lowering vComp lowers the height, so this is monotone and can't
    // oscillate. (An earlier version also grew vComp back on slack — that limit-
    // cycled: compress→slack→grow→overflow→compress…, which showed up as a page
    // that visibly jittered between two heights.) Growth is handled by reflow()
    // resetting to full size on a resize, then re-compressing from there.
    function refit(iter) {
        if (!visible || !content || (iter || 0) > 8)
            return
        var A = availableHeight, H = content.implicitHeight
        if (A <= 8 || H <= 8)
            return
        var vc = Theme.vComp
        if (H > A + 1) {                       // still overflowing -> compress further
            var nv = Math.max(floor, vc * A / H)
            if (vc - nv > 0.004) {
                Theme.vComp = nv
                Qt.callLater(refit, (iter || 0) + 1)
            }
        }
    }

    // Reset to full size, then compress to fit. Used when the available space changes
    // (window resize, tab shown) so a grown window reclaims its padding instead of
    // staying squished. NOT called from the content-height watcher below (resetting
    // there would ping-pong against the compression).
    function reflow() {
        if (!visible)
            return
        Theme.vComp = 1
        Qt.callLater(refit)
    }

    onAvailableHeightChanged: reflow()
    onVisibleChanged: if (visible) reflow()
    Component.onCompleted: reflow()

    // The content changed height on its own (e.g. config populated the cards): just
    // (compress-)refit. We deliberately DON'T reflow-to-full here — a compress step
    // can slightly overshoot (content ends a touch shorter than the viewport), and
    // reflowing on that self-induced slack would ping-pong full<->compressed forever
    // (the "page jitters between two heights" bug). Growth is reclaimed on resize /
    // tab-switch via reflow() instead; a little over-compression just leaves a bit of
    // extra room, which is harmless.
    Connections {
        target: scroller.content
        enabled: scroller.content !== null
        function onImplicitHeightChanged() { Qt.callLater(scroller.refit) }
    }
}

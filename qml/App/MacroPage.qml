import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts
import App 1.0

// Per-paddle macro editor. Pick a back paddle, switch the macro on, then build a
// sequence of button events (each with a hold + delay time). Applies immediately
// to the active profile bank. Shared by the Cyclone (L4/R4) and 8K (L4/R4/L5/R5).
Item {
    id: page

    property int pad: 0
    readonly property string paddle: bridge.macroSlots.length > pad ? bridge.macroSlots[pad] : ""
    property bool enable: false
    property var events: []            // [{target, hold, delay}]
    property int sel: -1               // selected event index, -1 = none
    property var clip: null            // copied step (in-app clipboard)
    property int dupN: 2

    function defaultTarget() { return 9 }                 // gamepad A
    function targetName(code) { return bridge.targetLabel(code) }

    function seed() {
        var m = bridge.macros[paddle]
        enable = m ? m.enable === true : false
        events = m && m.events ? m.events.map(function (e) {
            return {target: e.target, hold: e.hold, delay: e.delay}
        }) : []
        sel = events.length ? 0 : -1
        macroSw.checked = enable        // set imperatively — a binding breaks on tap
    }
    Component.onCompleted: seed()
    Connections { target: bridge; function onMacroLoaded() { page.seed() } }
    onVisibleChanged: if (visible) seed()
    onPadChanged: seed()

    function commit() { bridge.setMacroEvents(paddle, events) }
    function touch() { events = events.slice() }     // re-trigger bindings
    // rewriting the whole block on every slider tick would get dropped; debounce.
    Timer { id: commitTimer; interval: 300; onTriggered: page.commit() }

    function addEvent() {
        if (events.length >= bridge.macroMax) return
        events.push({target: defaultTarget(), hold: 100, delay: 100})
        touch(); sel = events.length - 1; commit()
    }
    function removeEvent(i) {
        events.splice(i, 1); touch()
        if (sel >= events.length) sel = events.length - 1
        commit()
    }
    function setField(i, key, val) { events[i][key] = val; touch() }
    function copyStep()  { if (sel >= 0) { var e = events[sel]; clip = {target: e.target, hold: e.hold, delay: e.delay} } }
    function pasteStep() {
        if (!clip || events.length >= bridge.macroMax) return
        events.splice(sel + 1, 0, {target: clip.target, hold: clip.hold, delay: clip.delay})
        touch(); sel = sel + 1; commit()
    }
    function duplicate(n) {
        if (sel < 0) return
        var src = events[sel], room = bridge.macroMax - events.length
        n = Math.max(1, Math.min(n, room))
        for (var k = 0; k < n; k++)
            events.splice(sel + 1, 0, {target: src.target, hold: src.hold, delay: src.delay})
        touch(); commit()
    }
    function move(dir) {
        var j = sel + dir
        if (sel < 0 || j < 0 || j >= events.length) return
        var t = events[sel]; events[sel] = events[j]; events[j] = t
        sel = j; touch(); commit()
    }

    // small editable number field (lets you type / copy-paste hold & delay in ms)
    component NumField: Rectangle {
        property int value: 0
        property int maxVal: 65535
        signal committed(int v)
        width: 66; height: 24; radius: Theme.radiusSm
        color: Theme.bg; border.width: 1
        border.color: input.activeFocus ? Theme.accent : Theme.cardBorder
        TextInput {
            id: input
            anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 8
            verticalAlignment: TextInput.AlignVCenter
            text: parent.value
            color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
            selectByMouse: true; validator: IntValidator { bottom: 0; top: parent.maxVal }
            onEditingFinished: parent.committed(parseInt(text) || 0)
        }
    }

    // Content stays at its natural (preset) size and SCROLLS if the window is
    // too short — text never scales down, so nothing gets illegibly narrow.
    // Cards compress their vertical padding (Theme.vComp via FitScroll) to fit
    // the window before scrolling — contents stay full-size.
    FitScroll {
        id: scroller
        anchors.fill: parent
        anchors.margins: 20
        content: fitBox

        Column {
            id: fitBox
            width: scroller.availableWidth
            spacing: Math.max(6, Math.round(14 * Theme.vComp))

            // ---- paddle selector + enable ----
            RowLayout {
                width: parent.width; spacing: 12
                Row {
                    spacing: 8
                    Repeater {
                        model: bridge.macroSlots
                        delegate: PillButton {
                            required property string modelData
                            required property int index
                            label: modelData
                            highlight: page.pad === index
                            onClicked: page.pad = index
                        }
                    }
                }
                Item { Layout.fillWidth: true }
                Text { text: "Macro"; color: Theme.textDim
                       font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                       anchors.verticalCenter: parent.verticalCenter }
                ToggleSwitch {
                    id: macroSw
                    onToggled: { page.enable = macroSw.checked
                                 bridge.setMacroEnable(page.paddle, macroSw.checked) }
                }
            }

            RowLayout {
                width: parent.width; spacing: 20
                enabled: page.enable                 // toggle off = editor is inert
                opacity: page.enable ? 1.0 : 0.45

                // ============ left: event list ============
                ColumnLayout {
                    Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 12
                    Card {
                        title: "Sequence"
                        headerValue: page.events.length + " / " + bridge.macroMax + " steps"
                        Layout.fillWidth: true
                        ListView {
                            id: eventList
                            width: parent.width
                            height: page.events.length ? Math.min(7, page.events.length) * 40 : 0
                            clip: true; spacing: 6
                            boundsBehavior: Flickable.StopAtBounds
                            model: page.events.length
                            // default wheel step is tiny; scroll a few rows per notch
                            WheelHandler {
                                onWheel: function (ev) {
                                    var max = Math.max(0, eventList.contentHeight - eventList.height)
                                    eventList.contentY = Math.max(0, Math.min(max,
                                        eventList.contentY - ev.angleDelta.y))
                                }
                            }
                            delegate: Rectangle {
                                required property int index
                                width: ListView.view.width; height: 34; radius: Theme.radius
                                color: page.sel === index ? Theme.cardHover : "transparent"
                                border.color: page.sel === index ? Theme.accent : Theme.cardBorder
                                border.width: 1
                                Row {
                                    anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 28
                                    spacing: 8
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: 18; text: (index + 1); color: Theme.textDim
                                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: 60; text: page.targetName(page.events[index].target)
                                        color: Theme.text; font.bold: true
                                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: page.events[index].hold + " / " + page.events[index].delay + " ms"
                                        color: Theme.textDim
                                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                                    }
                                }
                                Text {
                                    anchors.right: parent.right; anchors.rightMargin: 10
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "✕"; color: Theme.textDim
                                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                                    TapHandler { onTapped: page.removeEvent(index) }
                                }
                                TapHandler { onTapped: page.sel = index }
                            }
                        }
                        Text {
                            visible: page.events.length === 0
                            text: "No events yet — add one to start the sequence."
                            color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        }
                        PillButton {
                            label: "+ Add event"
                            enabled: page.events.length < bridge.macroMax
                            onClicked: page.addEvent()
                        }
                    }
                    Item { Layout.fillHeight: true }
                }

                Rectangle { Layout.fillHeight: true; Layout.topMargin: 8; Layout.bottomMargin: 8
                            Layout.preferredWidth: 1; color: Theme.cardBorder }

                // ============ right: selected event editor ============
                ColumnLayout {
                    Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 12
                    Card {
                        title: page.sel >= 0 ? "Step " + (page.sel + 1) : "Step"
                        Layout.fillWidth: true
                        visible: page.sel >= 0 && page.sel < page.events.length
                        Text { text: "Button"; color: Theme.textDim
                               font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        // macros are controller-buttons only (the firmware's macro
                        // player doesn't emit keyboard/mouse — those are Rebinds).
                        Flow {
                            width: parent.width; spacing: 6
                            Repeater {
                                model: bridge.buttonTargets
                                delegate: PillButton {
                                    required property var modelData
                                    label: modelData.name
                                    highlight: page.sel >= 0 && page.events[page.sel].target === modelData.code
                                    onClicked: { page.setField(page.sel, "target", modelData.code); page.commit() }
                                }
                            }
                        }
                        Row {
                            width: parent.width; topPadding: 6; spacing: 10
                            Text { text: "Hold"; color: Theme.textDim; width: 84
                                   anchors.verticalCenter: parent.verticalCenter
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                            AccentSlider {
                                id: holdSlider; width: parent.width - 84 - 76; from: 0; to: 2000
                                anchors.verticalCenter: parent.verticalCenter
                                value: page.sel >= 0 ? page.events[page.sel].hold : 100
                                onMoved: if (page.sel >= 0) { page.setField(page.sel, "hold", Math.round(value)); commitTimer.restart() }
                            }
                            NumField {
                                anchors.verticalCenter: parent.verticalCenter
                                value: page.sel >= 0 ? page.events[page.sel].hold : 0
                                onCommitted: function (v) { if (page.sel >= 0) { page.setField(page.sel, "hold", v); page.commit() } }
                            }
                        }
                        Row {
                            width: parent.width; topPadding: 2; spacing: 10
                            Text { text: "Delay after"; color: Theme.textDim; width: 84
                                   anchors.verticalCenter: parent.verticalCenter
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                            AccentSlider {
                                id: delaySlider; width: parent.width - 84 - 76; from: 0; to: 2000
                                anchors.verticalCenter: parent.verticalCenter
                                value: page.sel >= 0 ? page.events[page.sel].delay : 100
                                onMoved: if (page.sel >= 0) { page.setField(page.sel, "delay", Math.round(value)); commitTimer.restart() }
                            }
                            NumField {
                                anchors.verticalCenter: parent.verticalCenter
                                value: page.sel >= 0 ? page.events[page.sel].delay : 0
                                onCommitted: function (v) { if (page.sel >= 0) { page.setField(page.sel, "delay", v); page.commit() } }
                            }
                        }

                        Text { text: "Step tools"; color: Theme.textDim; topPadding: 6
                               font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        Flow {
                            width: parent.width; spacing: 6
                            PillButton { label: "Duplicate"; enabled: page.events.length < bridge.macroMax
                                         onClicked: page.duplicate(1) }
                            PillButton { label: "Copy"; onClicked: page.copyStep() }
                            PillButton { label: "Paste"; enabled: page.clip !== null && page.events.length < bridge.macroMax
                                         onClicked: page.pasteStep() }
                            PillButton { label: "Move ▲"; enabled: page.sel > 0; onClicked: page.move(-1) }
                            PillButton { label: "Move ▼"; enabled: page.sel >= 0 && page.sel < page.events.length - 1
                                         onClicked: page.move(1) }
                        }
                        Row {
                            width: parent.width; spacing: 8; topPadding: 2
                            Text { text: "Duplicate ×"; color: Theme.textDim
                                   anchors.verticalCenter: parent.verticalCenter
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                            NumField {
                                anchors.verticalCenter: parent.verticalCenter
                                width: 48; value: page.dupN; maxVal: bridge.macroMax
                                onCommitted: function (v) { page.dupN = Math.max(1, v) }
                            }
                            PillButton {
                                label: "Go"; enabled: page.events.length < bridge.macroMax
                                onClicked: page.duplicate(page.dupN)
                            }
                        }
                    }
                    Item { Layout.fillHeight: true }
                }
            }
        }
    }

}

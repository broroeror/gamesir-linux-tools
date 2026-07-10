import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import QtQuick.Dialogs
import QtQuick.Controls as QQC
import QtCore
import App 1.0

Window {
    id: win
    width: 1040
    height: 720
    minimumWidth: 840
    minimumHeight: 620
    visible: true
    color: Theme.bg
    title: "GameSir Cyclone 2"

    property int currentTab: 0
    property bool settingsOpen: false
    readonly property var tabs: ["Rebinds", "Sticks", "Motion", "Triggers", "Vibration", "Lights", "Macros"]
    // Card vertical-compression is global (only one page shows at a time); reset it
    // to full on every tab switch so the newly-shown page's FitScroll re-fits from
    // scratch and a page never inherits another's compression.
    onCurrentTabChanged: Theme.vComp = 1

    // Persisted appearance prefs, applied to the Theme singleton on load and
    // whenever the user changes them in Settings → Appearance. Theme colors are
    // stored as a JSON {token: "#rrggbb"} map so a partial theme only overrides
    // the tokens the user actually touched; the rest fall back to Theme's defaults.
    Settings {
        id: appearance
        category: "appearance"
        property string density: "comfortable"
        property string themeJson: "{}"     // {token: colorString} overrides
        property string bgImage: ""         // background image file url ("" = none)
        property real   bgDim: 0.55          // 0 = full image .. 1 = full theme bg
        property string bgFill: "crop"       // crop | fit | stretch | tile
    }
    Component.onCompleted: {
        Theme.density = appearance.density
        applyThemeJson()
    }
    function setDensity(d) { Theme.density = d; appearance.density = d }

    // --- theme helpers (apply live + persist) --------------------------------
    function _parseTheme() {
        try { return JSON.parse(appearance.themeJson || "{}") } catch (e) { return {} }
    }
    function applyThemeJson() { Theme.applyColors(_parseTheme()) }
    function setThemeColor(key, c) {
        Theme[key] = c
        var o = _parseTheme(); o[key] = c.toString(); appearance.themeJson = JSON.stringify(o)
    }
    function applyPreset(colors) {
        Theme.resetColors(); Theme.applyColors(colors)
        var o = {}
        for (var i = 0; i < Theme.themeKeys.length; i++) {
            var k = Theme.themeKeys[i].key; o[k] = Theme[k].toString()
        }
        appearance.themeJson = JSON.stringify(o)
    }
    function resetTheme() { Theme.resetColors(); appearance.themeJson = "{}" }

    // Is the chosen background a video (played by MediaPlayer) vs a still/gif
    // image (AnimatedImage)? Drives which background layer is active.
    readonly property bool bgIsVideo: /\.(webm|mp4|mkv|mov|m4v)$/i.test("" + appearance.bgImage)

    // File picker for the background (png / jpeg / gif image, or webm / mp4 video).
    FileDialog {
        id: bgDialog
        title: "Choose a background image or video"
        nameFilters: ["Images & video (*.png *.jpg *.jpeg *.gif *.webm *.mp4 *.mkv *.mov *.m4v)",
                      "Images (*.png *.jpg *.jpeg *.gif)",
                      "Video (*.webm *.mp4 *.mkv *.mov *.m4v)",
                      "All files (*)"]
        onAccepted: appearance.bgImage = selectedFile.toString()
    }

    // Base wash: a faint themed glow at the top (Theme.bgGlow) fading into the
    // background, like the first-party app. Bound to the theme tokens so it
    // recolors live when the user picks a new palette.
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            orientation: Gradient.Vertical
            GradientStop { position: 0.0; color: Theme.bgGlow }
            GradientStop { position: 0.45; color: Theme.bg }
            GradientStop { position: 1.0; color: Theme.bg }
        }
    }

    // Optional user background. Two layers, one active at a time: AnimatedImage for
    // stills/gifs (png/jpeg/gif), a muted looping MediaPlayer→VideoOutput for video
    // (webm/mp4/…). Both sit above the base wash and below all content; a themed dim
    // overlay keeps cards/text readable over busy media (0 = full media, 1 = theme bg).
    AnimatedImage {
        id: bgImg
        anchors.fill: parent
        visible: source != "" && !win.bgIsVideo
        source: win.bgIsVideo ? "" : appearance.bgImage
        fillMode: appearance.bgFill === "fit" ? Image.PreserveAspectFit
                : appearance.bgFill === "stretch" ? Image.Stretch
                : appearance.bgFill === "tile" ? Image.Tile
                : Image.PreserveAspectCrop
        asynchronous: true
        cache: false
        speed: 1.0
    }
    // Video layer, loaded LAZILY and only when a video is chosen — it lives in a
    // separate file that imports QtMultimedia, so a system WITHOUT the multimedia
    // backend still runs the app (and image backgrounds) fine; only video degrades.
    Loader {
        id: bgVideoLoader
        anchors.fill: parent
        active: win.bgIsVideo
        source: Qt.resolvedUrl("App/VideoBackground.qml")
        onLoaded: { item.src = appearance.bgImage; item.fillModeStr = appearance.bgFill }
        Connections {
            target: appearance
            function onBgImageChanged() { if (bgVideoLoader.item) bgVideoLoader.item.src = appearance.bgImage }
            function onBgFillChanged()  { if (bgVideoLoader.item) bgVideoLoader.item.fillModeStr = appearance.bgFill }
        }
    }
    Rectangle {
        anchors.fill: parent
        visible: appearance.bgImage != ""
        color: Theme.bg
        opacity: appearance.bgDim
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ---------------------------------------------------------- top bar
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 58
            color: Theme.navBar
            z: 100   // keep the mouse-mode help tooltip above the nav/content below
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 20
                anchors.rightMargin: 68     // reserve space for the pinned gear (right)
                spacing: win.width < 1000 ? 10 : 18

                // Logo — doubles as the DEMO indicator: in demo mode the icon shows
                // "!" (warn colour) and the wordmark reads "DEMO", so demo state is
                // obvious without a separate badge crowding the bar.
                RowLayout {
                    spacing: 8
                    Rectangle {
                        width: 26; height: 26; radius: 6
                        color: bridge.demoMode ? Theme.warn : Theme.accent
                        Text {
                            anchors.centerIn: parent
                            text: bridge.demoMode ? "!" : "G"; color: "white"
                            font.bold: true; font.pixelSize: 16
                        }
                    }
                    Text {
                        // "DEMO" is short so it always shows; the longer "GAMESIR"
                        // wordmark hides when the bar is tight (the icon still brands it).
                        visible: bridge.demoMode || win.width >= 940
                        text: bridge.demoMode ? "DEMO" : "GAMESIR"
                        color: bridge.demoMode ? Theme.warn : Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontL
                        font.weight: Font.Bold
                        font.letterSpacing: 1
                    }
                }

                ControllerPicker { Layout.alignment: Qt.AlignVCenter }

                ProfileBar { compact: win.width < 1200 }

                // Reset the ACTIVE profile to its factory defaults — lives beside
                // the profile pills since it acts on whichever profile is selected
                // (moved here from the Rebinds page). Hidden for controllers with
                // no reset path (G7/G7 Pro) or when no profile is selected.
                ConfirmButton {
                    Layout.alignment: Qt.AlignVCenter
                    visible: bridge.profile > 0 && bridge.profileResetSupported
                    label: win.width < 1200 ? "↺" : "↺ Reset profile"
                    confirmLabel: "Reset Profile " + bridge.profile + "?"
                    onConfirmed: bridge.resetProfileToDefault()
                }

                Item { Layout.fillWidth: true }

                // Loads/unloads KDE's Game Controller (KWin) plugin so the
                // sticks drive the desktop cursor. Labelled by what it does, with
                // a help icon spelling out the plugin + on/off behaviour.
                Row {
                    visible: bridge.mouseModeAvailable
                    Layout.alignment: Qt.AlignVCenter
                    spacing: 8
                    Text {
                        visible: win.width >= 1000   // hide label when narrow; help icon still explains
                        text: "Sticks → cursor"; color: Theme.textDim
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    HelpIcon {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Toggles KDE's Game Controller (KWin) plugin.\n\n" +
                              "On: the controller's sticks move your mouse pointer " +
                              "and the triggers click — handy from the couch.\n\n" +
                              "Off: the controller acts as a normal gamepad (games " +
                              "still read it directly).\n\n" +
                              "Same setting as System Settings → Game Controller; " +
                              "applied live and remembered."
                    }
                    ToggleSwitch {
                        id: mmSwitch
                        anchors.verticalCenter: parent.verticalCenter
                        checked: bridge.mouseModeOn
                        onToggled: bridge.setMouseMode(mmSwitch.checked)
                    }
                }

                Rectangle {
                    visible: bridge.mouseModeAvailable
                    Layout.alignment: Qt.AlignVCenter
                    width: 1; height: 24; color: Theme.cardBorder
                }

                StatusPill { compact: win.width < 1000 }
            }

            // Settings gear — pinned to the bar's right edge, OUTSIDE the RowLayout,
            // so a tight/overflowing bar can never push it off-screen (the StatusPill
            // to its left clips behind it instead). Declared after the RowLayout so
            // it draws on top; the RowLayout's rightMargin reserves its space.
            Rectangle {
                anchors.right: parent.right; anchors.rightMargin: 20
                anchors.verticalCenter: parent.verticalCenter
                width: 34; height: 34; radius: 8
                color: win.settingsOpen ? Theme.accent
                                        : (gearHov.hovered ? Theme.cardHover : "transparent")
                Behavior on color { ColorAnimation { duration: 120 } }
                Text {
                    anchors.centerIn: parent; text: "⚙"; font.pixelSize: 18
                    color: win.settingsOpen ? "white" : Theme.textDim
                }
                HoverHandler { id: gearHov }
                TapHandler { onTapped: win.settingsOpen = !win.settingsOpen }
            }
        }

        // ------------------------------------------------------------- nav
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 52
            color: Theme.bg
            Row {
                anchors.centerIn: parent
                spacing: 6
                Repeater {
                    model: win.tabs
                    delegate: NavTab {
                        required property int index
                        required property string modelData
                        label: modelData
                        active: win.currentTab === index
                        onClicked: win.currentTab = index
                    }
                }
            }
            Rectangle { anchors.bottom: parent.bottom; width: parent.width
                        height: 1; color: Theme.cardBorder }
        }

        // --------------------------------------------------------- content
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            // Buttons tab (front page): live controller + remap + reset.
            ButtonsPage {
                anchors.fill: parent
                visible: win.currentTab === 0
            }

            // Vibration tab.
            VibrationPage {
                anchors.fill: parent
                visible: win.currentTab === 4
            }

            // Sticks tab.
            AxisConfigPage {
                anchors.fill: parent
                visible: win.currentTab === 1
                isStick: true
                sideKeys: [["Left Stick", "st"], ["Right Stick", "rs"]]
            }

            // Triggers tab.
            AxisConfigPage {
                anchors.fill: parent
                visible: win.currentTab === 3
                isStick: false
                sideKeys: [["Left Trigger", "lt"], ["Right Trigger", "rt"]]
            }

            // Lights tab. Only the Cyclone's keyframe/palette RGB is wired up; other
            // models (e.g. the 8K's mode/brightness/home-ring) get a placeholder
            // until their lighting page is built, so the Cyclone controls never
            // drive a controller with a different lighting layout.
            LightsPage {
                anchors.fill: parent
                visible: win.currentTab === 5 && bridge.lightingStyle === "cyclone_keyframe"
            }
            Lights8kPage {
                anchors.fill: parent
                visible: win.currentTab === 5 && bridge.lightingStyle === "simple_8k"
            }
            Item {
                anchors.fill: parent
                visible: win.currentTab === 5 && bridge.lightingStyle === "none"
                Card {
                    anchors.centerIn: parent
                    width: 440
                    title: "Lighting"
                    Text {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: "This controller has no app-configurable lighting."
                        color: Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontM
                    }
                }
            }

            // Macros tab — per-paddle macro editor (Cyclone L4/R4, 8K adds L5/R5).
            MacroPage {
                anchors.fill: parent
                visible: win.currentTab === 6 && bridge.hasMacros
            }
            Item {
                anchors.fill: parent
                visible: win.currentTab === 6 && !bridge.hasMacros
                Card {
                    anchors.centerIn: parent
                    width: 440
                    title: "Macros"
                    Text {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: "This controller has no app-configurable macros."
                        color: Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontM
                    }
                }
            }

            // Motion tab — gyro Aim/Tilt editor for models that have it (8K); a
            // placeholder for models whose motion isn't reverse-engineered.
            MotionPage {
                anchors.fill: parent
                visible: win.currentTab === 2 && bridge.hasMotion
            }
            Item {
                anchors.fill: parent
                visible: win.currentTab === 2 && !bridge.hasMotion
                Card {
                    anchors.centerIn: parent
                    width: 440
                    title: "Motion"
                    Text {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: "This controller has no app-configurable motion / gyro."
                        color: Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontM
                    }
                }
            }
        }
    }

    // -------------------------------------------------- settings overlay
    Rectangle {
        anchors.fill: parent
        visible: win.settingsOpen
        color: Qt.rgba(0, 0, 0, 0.55)
        MouseArea { anchors.fill: parent; onClicked: win.settingsOpen = false }

        Rectangle {
            id: panel
            anchors.centerIn: parent
            width: 540
            height: Math.min(Math.round(win.height * 0.86), body.implicitHeight + 110)
            radius: Theme.radius
            color: Theme.card
            border.color: Theme.cardBorder; border.width: 1
            MouseArea { anchors.fill: parent }   // swallow clicks so they don't close

            component SectionHeader: Text {
                color: Theme.text; font.family: Theme.fontFamily
                font.pixelSize: Theme.fontM; font.weight: Font.DemiBold
            }
            component Divider: Rectangle { width: body.width; height: 1; color: Theme.cardBorder }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12

                // header (pinned above the scroll area)
                Item {
                    id: hdr
                    Layout.fillWidth: true; implicitHeight: 26
                    Text {
                        anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                        text: "Settings"; color: Theme.text
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontL
                        font.weight: Font.DemiBold
                    }
                    Rectangle {
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                        width: 26; height: 26; radius: 6
                        color: closeHov.hovered ? Theme.cardHover : "transparent"
                        Text { anchors.centerIn: parent; text: "✕"; color: Theme.textDim; font.pixelSize: 14 }
                        HoverHandler { id: closeHov }
                        TapHandler { onTapped: win.settingsOpen = false }
                    }
                }
                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.cardBorder }

                QQC.ScrollView {
                    id: scroller
                    Layout.fillWidth: true; Layout.fillHeight: true
                    clip: true
                    contentWidth: availableWidth
                    QQC.ScrollBar.horizontal.policy: QQC.ScrollBar.AlwaysOff

                    Column {
                        id: body
                        width: scroller.availableWidth
                        spacing: 16

                        // ------------------------------------------ Appearance
                        SectionHeader { text: "Appearance" }
                        Row {
                            width: parent.width; spacing: 8
                            Text {
                                text: "Density"; color: Theme.textDim; width: 72
                                anchors.verticalCenter: parent.verticalCenter
                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                            }
                            Repeater {
                                model: [["Compact", "compact"],
                                        ["Comfortable", "comfortable"],
                                        ["Cozy", "cozy"]]
                                delegate: PillButton {
                                    required property var modelData
                                    label: modelData[0]
                                    highlight: Theme.density === modelData[1]
                                    onClicked: win.setDensity(modelData[1])
                                }
                            }
                        }

                        Divider {}

                        // ------------------------------------------ Demo mode
                        SectionHeader { text: "Demo mode" }
                        Row {
                            width: parent.width; spacing: 12
                            ToggleSwitch {
                                id: demoSw
                                anchors.verticalCenter: parent.verticalCenter
                                checked: bridge.demoMode
                                onToggled: bridge.setDemoMode(demoSw.checked)
                            }
                            Text {
                                width: parent.width - 60; wrapMode: Text.WordWrap
                                anchors.verticalCenter: parent.verticalCenter
                                text: "Preview one of each supported controller in software, "
                                    + "with no hardware connected — pick a model from the top-bar "
                                    + "selector. Ignores real controllers while on; turns off on restart."
                                color: Theme.textDim; font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontS
                            }
                        }

                        Divider {}

                        // ------------------------------------------ Theme colors
                        Item {
                            width: body.width; height: themeHdr.height
                            SectionHeader { id: themeHdr; text: "Theme" }
                            PillButton {
                                anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                                label: "Reset colors"; onClicked: win.resetTheme()
                            }
                        }
                        Text {
                            text: "Presets"; color: Theme.textDim; topPadding: 2
                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        }
                        Flow {
                            width: parent.width; spacing: 8
                            Repeater {
                                model: Theme.presets
                                delegate: PillButton {
                                    required property var modelData
                                    label: modelData.name
                                    onClicked: win.applyPreset(modelData.colors)
                                }
                            }
                        }
                        Text {
                            text: "Custom colors"; color: Theme.textDim; topPadding: 4
                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        }
                        Flow {
                            width: parent.width; spacing: 14
                            Repeater {
                                model: Theme.themeKeys
                                delegate: ColorField {
                                    required property var modelData
                                    width: 168
                                    label: modelData.label
                                    value: Theme[modelData.key]
                                    onPicked: function (c) { win.setThemeColor(modelData.key, c) }
                                }
                            }
                        }

                        Divider {}

                        // ------------------------------------------ Background
                        SectionHeader { text: "Background" }
                        Text {
                            width: parent.width; wrapMode: Text.WordWrap
                            text: "Use a PNG, JPEG, animated GIF — or a WEBM/MP4 video (played "
                                + "muted on loop) — behind the app. The dim slider keeps cards "
                                + "and text readable over busy media."
                            color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        }
                        Row {
                            width: parent.width; spacing: 8
                            PillButton { label: "Choose…"; onClicked: bgDialog.open() }
                            PillButton {
                                label: "Clear"; visible: appearance.bgImage !== ""
                                onClicked: appearance.bgImage = ""
                            }
                        }
                        Text {
                            visible: appearance.bgImage !== ""
                            width: parent.width; elide: Text.ElideMiddle
                            text: "▸ " + decodeURIComponent(("" + appearance.bgImage).split('/').pop())
                            color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        }
                        // fill mode + dim (only meaningful once an image is set)
                        Row {
                            visible: appearance.bgImage !== ""
                            width: parent.width; spacing: 8
                            Text {
                                text: "Fit"; color: Theme.textDim; width: 72
                                anchors.verticalCenter: parent.verticalCenter
                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                            }
                            Repeater {
                                model: [["Crop", "crop"], ["Fit", "fit"],
                                        ["Stretch", "stretch"], ["Tile", "tile"]]
                                delegate: PillButton {
                                    required property var modelData
                                    label: modelData[0]
                                    highlight: appearance.bgFill === modelData[1]
                                    onClicked: appearance.bgFill = modelData[1]
                                }
                            }
                        }
                        Row {
                            visible: appearance.bgImage !== ""
                            width: parent.width; spacing: 8
                            Text {
                                text: "Dim"; color: Theme.textDim; width: 72
                                anchors.verticalCenter: parent.verticalCenter
                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                            }
                            AccentSlider {
                                width: parent.width - 130
                                anchors.verticalCenter: parent.verticalCenter
                                from: 0; to: 1; integer: false; value: appearance.bgDim
                                onMoved: function (v) { appearance.bgDim = v }
                            }
                            Text {
                                text: Math.round(appearance.bgDim * 100) + "%"
                                color: Theme.textDim; width: 40
                                anchors.verticalCenter: parent.verticalCenter
                                horizontalAlignment: Text.AlignRight
                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                            }
                        }

                        Divider {}

                        // ------------------------------------------ Backup & Restore
                        SectionHeader { text: "Backup & Restore" }
                        BackupPanel { width: parent.width }

                        // Firmware backup/restore is Cyclone/BR23-only; hide the
                        // whole section for controllers that don't support it.
                        Divider { visible: bridge.fwSupported }
                        SectionHeader { text: "Firmware Backup & Restore"; visible: bridge.fwSupported }
                        FirmwarePanel { width: parent.width; visible: bridge.fwSupported }

                        Divider {}
                        SectionHeader { text: "Lighting" }
                        ConfirmButton {
                            label: "Restore default lighting"
                            confirmLabel: "Restore default lighting?"
                            onConfirmed: bridge.restoreLighting()
                        }
                    }
                }
            }
        }
    }

    // Transient toast: read-back result of the last "Save to Profile" (Apply).
    // Confirms an edit actually landed on the hardware (vs. a silently-dropped
    // vendor write) — the answer to "I can't tell if it's applying".
    Rectangle {
        id: applyToast
        property bool ok: bridge.applyStatus.indexOf("✓") >= 0
        property bool busy: bridge.applyStatus === "Applying…"
        visible: bridge.applyStatus.length > 0
        z: 9999
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 24
        radius: Theme.radius
        implicitWidth: toastText.implicitWidth + 34
        implicitHeight: 40
        color: Theme.card
        border.width: 1
        border.color: applyToast.busy ? Theme.cardBorder
                                       : (applyToast.ok ? Theme.ok : Theme.warn)
        Text {
            id: toastText
            anchors.centerIn: parent
            text: bridge.applyStatus
            color: applyToast.busy ? Theme.textDim
                                   : (applyToast.ok ? Theme.ok : Theme.warn)
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
            font.weight: Font.DemiBold
        }
        // Auto-hide the settled result after a few seconds ("Applying…" stays
        // until the verify replaces it).
        Timer {
            id: toastTimer; interval: 4500
            onTriggered: bridge.clearApplyStatus()
        }
        Connections {
            target: bridge
            function onApplyStatusChanged() {
                if (bridge.applyStatus.length > 0 && !applyToast.busy)
                    toastTimer.restart()
                else
                    toastTimer.stop()
            }
        }
    }
}

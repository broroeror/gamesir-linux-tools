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
    title: "Deadband"

    property int currentTab: 0
    property bool settingsOpen: false
    // Which device the app drives: the controller shell or the G502 X mouse. The
    // device picker flips this, which swaps the nav tabs + content below.
    property string activeDevice: "controller"       // "controller" | "mouse"
    // Name of the mouse profile currently being edited — used by the reset
    // button's label, confirm prompt and tooltip so they always agree.
    readonly property string selectedProfileLabel: {
        for (var i = 0; i < mouse.profiles.length; i++)
            if (mouse.profiles[i].sector === mouse.selectedProfile)
                return mouse.profiles[i].label
        return "this profile"
    }
    readonly property var controllerTabs: ["Rebinds", "Sticks", "Motion", "Triggers", "Vibration", "Lights", "Macros"]
    readonly property var mouseTabs: ["Buttons", "DPI", "Macros"]
    readonly property var tabs: activeDevice === "mouse" ? mouseTabs : controllerTabs
    // Card vertical-compression is global (only one page shows at a time); reset it
    // to full on every tab switch so the newly-shown page's FitScroll re-fits from
    // scratch and a page never inherits another's compression.
    onCurrentTabChanged: Theme.vComp = 1
    onActiveDeviceChanged: { currentTab = 0; Theme.vComp = 1 }

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

    // Friendly per-controller names ("Black", "White"), keyed by USB PORT.
    //
    // Port is the ONLY key available: identical models report the same PID, the same
    // bcdDevice, and a USB serial that is a firmware constant shared across models —
    // the genuinely unique id (an RF MAC) lives in dongle flash and is readable only
    // from the bootloader, i.e. never while the device is in use. So a name follows
    // the PORT, not the hardware: move a dongle to another socket and its name stays
    // behind. That's a real limitation, surfaced in the UI rather than hidden.
    Settings {
        id: ctrlNames
        category: "controllers"
        property string namesJson: "{}"     // {usb port id: friendly name}
    }
    Component.onCompleted: {
        Theme.density = appearance.density
        applyThemeJson()
        _loadNames()
    }
    // If the mouse is unplugged while it's the active device, fall back to controller.
    Connections {
        target: mouse
        function onPresenceChanged() {
            if (!mouse.present && win.activeDevice === "mouse")
                win.activeDevice = "controller"
        }
    }
    function setDensity(d) { Theme.density = d; appearance.density = d }

    // --- controller naming (port-keyed; see the ctrlNames Settings note) ------
    property var controllerNames: ({})
    function _loadNames() {
        try { controllerNames = JSON.parse(ctrlNames.namesJson || "{}") }
        catch (e) { controllerNames = ({}) }
    }
    // friendly name for a port id, or "" when the user hasn't named it
    function nameFor(id) {
        var n = controllerNames[id]
        return (n && n.length) ? n : ""
    }
    function setControllerName(id, name) {
        var o = {}
        for (var k in controllerNames) o[k] = controllerNames[k]
        name = (name || "").trim()
        if (name.length) o[id] = name; else delete o[id]     // blank clears it
        controllerNames = o                                  // reassign: notifies bindings
        ctrlNames.namesJson = JSON.stringify(o)
    }

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
                // NOTE: do NOT clip this row to stop overflow reaching the gear --
                // HelpIcon's bubble is a plain child drawn BELOW the 58px bar (not a
                // Popup), so clipping here cuts the mouse-mode tooltip in half. The
                // compact thresholds below are what keep the bar inside its bounds.
                spacing: win.width < 1000 ? 10 : 18

                // Logo — doubles as the DEMO indicator: in demo mode the tile shows
                // "!" (warn colour) and the wordmark reads "DEMO", so demo state is
                // obvious without a separate badge crowding the bar.
                RowLayout {
                    spacing: 8
                    // The app's gamepad mark on a THEMED tile. The launcher icon can't
                    // follow the theme (it's a static PNG the desktop renders), but this
                    // one can, so it's drawn as accent + a bare white glyph rather than
                    // the launcher art — which bakes in the default red and would clash
                    // once the user picks another palette. White on accent stays legible
                    // on every preset, since accent is always a saturated colour.
                    Rectangle {
                        Layout.preferredWidth: 26; Layout.preferredHeight: 26
                        radius: 6
                        color: bridge.demoMode ? Theme.warn : Theme.accent
                        Image {
                            visible: !bridge.demoMode
                            // Two pre-tinted glyphs rather than a runtime colour
                            // overlay: recolouring an Image needs QtQuick.Effects,
                            // and the app deliberately avoids optional QML modules
                            // that may not be installed (see VideoBackground).
                            source: assetsDir + (Theme.accentIsLight ? "glyph-pad-dark.png"
                                                                     : "glyph-pad.png")
                            anchors.centerIn: parent
                            width: 17; height: 17
                            fillMode: Image.PreserveAspectFit
                            smooth: true; mipmap: true
                        }
                        // Demo mode swaps the glyph for a "!" on the warn tile.
                        Text {
                            visible: bridge.demoMode
                            anchors.centerIn: parent
                            text: "!"; color: "white"
                            font.bold: true; font.pixelSize: 16
                        }
                    }
                    Text {
                        // "DEMO" is short so it always shows; the longer wordmark
                        // hides when the bar is tight (the tile still brands it).
                        visible: bridge.demoMode || win.width >= 940
                        text: bridge.demoMode ? "DEMO" : "DEADBAND"
                        color: bridge.demoMode ? Theme.warn : Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontL
                        font.weight: Font.Bold
                        font.letterSpacing: 1
                    }
                }

                // names are port-keyed and live in Main's Settings, so pass the map
                // down — ControllerPicker is its own file and can't see `win`.
                ControllerPicker {
                    Layout.alignment: Qt.AlignVCenter
                    names: win.controllerNames
                    mousePresent: mouse.present
                    mouseActive: win.activeDevice === "mouse"
                    onPickController: function (id) {
                        bridge.selectController(id); win.activeDevice = "controller"
                    }
                    onPickMouse: win.activeDevice = "mouse"
                }

                // Expand only once the full-width bar actually fits. MEASURED: expanded
                // row implicitWidth peaks at ~1211 (cozy density, connected controller)
                // + 20 left margin + 68 gear reserve = 1299, so 1200 overflowed by ~99px
                // and the status text ran under the gear. 1320 leaves headroom for the
                // widest live content.
                ProfileBar { compact: win.width < 1320; visible: win.activeDevice === "controller" }

                // The mouse's own onboard profiles (5 slots, named, stored on the
                // device). Picking one changes what the pages EDIT; making it the
                // running profile is a separate, explicit action.
                MouseProfileBar {
                    id: mouseProfiles
                    // Lower threshold than the controller's bar on purpose: five
                    // pills, and the NAMES are the reason to have them, so keep
                    // full labels down to widths where they still fit.
                    compact: win.width < 1150
                    Layout.alignment: Qt.AlignVCenter
                    visible: win.activeDevice === "mouse" && mouse.present
                             && mouse.profiles.length > 0
                }

                // Only meaningful when you're editing a profile the mouse isn't
                // running — otherwise it's a no-op button, so it stays hidden.
                PillButton {
                    id: makeActiveBtn
                    Layout.alignment: Qt.AlignVCenter
                    visible: win.activeDevice === "mouse" && mouse.present
                             && mouse.selectedProfile > 0
                             && mouse.selectedProfile !== mouse.activeProfile
                    enabled: !mouse.busy
                    // Higher text threshold than the profile bar on purpose: the
                    // NAMES are what deserve the width, so these two collapse to
                    // icons first rather than pushing the status pill off the bar.
                    label: win.width < 1450 ? "▶" : "▶ Make active"
                    onClicked: mouse.makeActive(mouse.selectedProfile)
                    HoverHandler { id: makeActiveHover }
                    QQC.ToolTip {
                        parent: makeActiveBtn
                        visible: makeActiveHover.hovered
                        delay: 400
                        text: "Switch the mouse to the profile you're editing.\n" +
                              "You can also cycle profiles with the button on the mouse."
                    }
                }

                // Restore the selected profile from the mouse's OWN factory copy
                // in ROM — a real factory restore, not defaults invented by us.
                // Hidden on a device that exposes no out-of-box profile.
                ConfirmButton {
                    id: mouseResetBtn
                    Layout.alignment: Qt.AlignVCenter
                    visible: win.activeDevice === "mouse" && mouse.present
                             && mouse.resetSupported && mouse.selectedProfile > 0
                    enabled: !mouse.busy
                    label: win.width < 1450 ? "↺" : "↺ Reset profile"
                    confirmLabel: "Reset " + win.selectedProfileLabel + "?"
                    onConfirmed: mouse.resetProfile()
                    HoverHandler { id: mouseResetHover }
                    QQC.ToolTip {
                        parent: mouseResetBtn
                        visible: mouseResetHover.hovered
                        delay: 400
                        text: "Restores " + win.selectedProfileLabel + " to the mouse's\n" +
                              "factory settings: buttons, G-Shift, DPI, rate and name.\n" +
                              "Your current settings are backed up first."
                    }
                }

                // Reset the ACTIVE profile to its factory defaults — lives beside
                // the profile pills since it acts on whichever profile is selected
                // (moved here from the Rebinds page). Hidden for controllers with
                // no reset path (G7/G7 Pro) or when no profile is selected.
                ConfirmButton {
                    id: resetBtn
                    Layout.alignment: Qt.AlignVCenter
                    visible: bridge.profile > 0 && bridge.profileResetSupported
                             && win.activeDevice === "controller"
                    label: win.width < 1320 ? "↺" : "↺ Reset profile"
                    confirmLabel: "Reset Profile " + bridge.profile + "?"
                    onConfirmed: bridge.resetProfileToDefault()
                    HoverHandler { id: resetHover }
                    QQC.ToolTip {
                        parent: resetBtn
                        visible: resetHover.hovered
                        delay: 400
                        text: "Resets only the current profile (P" + bridge.profile +
                              ") to defaults.\nReset all " + bridge.profileCount +
                              " in Settings → Backup & Restore."
                    }
                }

                Item { Layout.fillWidth: true }

                // Loads/unloads KDE's Game Controller (KWin) plugin so the
                // sticks drive the desktop cursor. Labelled by what it does, with
                // a help icon spelling out the plugin + on/off behaviour.
                Row {
                    visible: bridge.mouseModeAvailable && win.activeDevice === "controller"
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
                    visible: bridge.mouseModeAvailable && win.activeDevice === "controller"
                    Layout.alignment: Qt.AlignVCenter
                    width: 1; height: 24; color: Theme.cardBorder
                }

                StatusPill { compact: win.width < 1000; visible: win.activeDevice === "controller" }

                // Mouse status (when the G502 X is the active device): its OWN
                // battery / connection, read over HID++ — not the controller's.
                Row {
                    visible: win.activeDevice === "mouse"
                    Layout.alignment: Qt.AlignVCenter
                    spacing: 8
                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 8; height: 8; radius: 4
                        color: mouse.present ? Theme.ok : Theme.warn
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: mouse.present ? "Connected" : "Not connected"
                        color: Theme.textDim
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: mouse.present && mouse.battery >= 0
                        text: mouse.battery + "%"
                        color: mouse.battery >= 0 && mouse.battery <= 15 ? Theme.warn : Theme.accent
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        font.weight: Font.DemiBold
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: mouse.present
                        text: mouse.wireless ? "Wireless" : "Wired"
                        color: Theme.textDim
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                    }
                }
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

        // ---------------------------------------------- device-access banner
        // A controller was FOUND but can't be OPENED (permission / hidapi
        // backend). Without this, that state is an eternal "Searching…" with
        // every click a silent no-op (issue #1) — say what's wrong + the fix.
        Rectangle {
            visible: win.activeDevice === "controller" && bridge.accessProblem.length > 0
                     && !bridge.demoMode
            Layout.fillWidth: true
            Layout.leftMargin: 20; Layout.rightMargin: 20; Layout.topMargin: 10
            implicitHeight: accessCol.implicitHeight + 20
            radius: Theme.radius
            color: Theme.card; border.color: Theme.warn; border.width: 1
            Column {
                id: accessCol
                // the fix command for the diagnosed problem (udev vs hidapi
                // backend); NixOS gets declarative-config fixes for both
                readonly property string fixCmd: bridge.accessProblem === "backend"
                    ? (bridge.isNixos
                       ? "# use the community flake (builds hidapi with the hidraw backend):\nnix run codeberg:Epaphroditus/gamesir-linux-tools-nix"
                       : "HIDAPI_WITH_HIDRAW=1 pip install --user --force-reinstall --no-cache-dir --no-binary :all: hidapi")
                    : bridge.accessFixCommand
                anchors.left: parent.left; anchors.right: parent.right
                anchors.top: parent.top; anchors.margins: 10
                anchors.leftMargin: 14; anchors.rightMargin: 14
                spacing: 6
                Text {
                    width: parent.width; wrapMode: Text.WordWrap
                    color: Theme.warn; font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontM; font.weight: Font.DemiBold
                    text: bridge.accessProblem === "backend"
                          ? "⚠ Found your controller, but the Python hidapi library can't open it"
                          : "⚠ Found your controller, but Deadband isn't allowed to open it"
                }
                Text {
                    width: parent.width; wrapMode: Text.WordWrap
                    color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                    text: bridge.accessProblem === "backend"
                          ? (bridge.isNixos
                             ? "Your hidapi is built with the libusb backend, which can't open "
                               + "hidraw devices. On NixOS, use an overridden hidapi build — "
                               + "details in Diagnostics:"
                             : "Your hidapi is built with the libusb backend, which can't open hidraw "
                               + "devices (the pip default when built from source). Rebuild it — the "
                               + "--no-cache-dir matters, or pip reuses the old libusb build. "
                               + "Prerequisites & details in Diagnostics:")
                          : (bridge.isNixos
                             ? "On NixOS the rule comes from your configuration — add this (or use "
                               + "the community flake), rebuild, then replug:"
                             : "Run this once, then unplug and replug the controller:")
                }
                Text {
                    width: parent.width; wrapMode: Text.WrapAnywhere
                    color: Theme.text; font.family: "monospace"; font.pixelSize: Theme.fontS
                    text: accessCol.fixCmd
                }
                Row {
                    spacing: 8
                    PillButton {
                        label: "Copy command" + (bridge.accessProblem === "backend" ? "" : "s")
                        onClicked: bridge.copyText(accessCol.fixCmd)
                    }
                    PillButton {
                        label: "Diagnostics…"
                        onClicked: { diagWin.show(); diagWin.raise(); bridge.runDiagnostics() }
                    }
                }
            }
        }

        // --------------------------------------------------------- content
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

          Item {                                    // ---- controller content ----
            id: ctrlContent
            anchors.fill: parent
            visible: win.activeDevice === "controller"

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
          }                                         // ---- end controller content ----

          Item {                                    // ---- mouse content ----
              anchors.fill: parent
              visible: win.activeDevice === "mouse"
              MousePage { anchors.fill: parent; visible: win.currentTab === 0 }
              MouseDpiPage { anchors.fill: parent; visible: win.currentTab === 1 }
              MouseMacrosPage { anchors.fill: parent; visible: win.currentTab === 2 }
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
                    objectName: "settingsScroll"
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
                        SectionHeader { text: "Controllers" }
                        Text {
                            width: parent.width; wrapMode: Text.WordWrap
                            text: "Name each device so the picker shows \"Black\" instead of " +
                                  "\"Cyclone 2 #1\". Names are remembered per USB port — identical " +
                                  "models are indistinguishable to the computer, so moving a dongle " +
                                  "to another port leaves its name behind."
                            color: Theme.textDim
                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        }
                        Column {
                            width: parent.width
                            spacing: 8
                            Text {
                                visible: bridge.controllers.length === 0
                                text: "Nothing connected."
                                color: Theme.textFaint
                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                            }
                            Repeater {
                                model: bridge.controllers
                                delegate: Row {
                                    required property var modelData
                                    width: parent.width
                                    spacing: 10
                                    ConnIcon {
                                        anchors.verticalCenter: parent.verticalCenter
                                        wired: modelData.wired
                                        live: modelData.live
                                        tint: modelData.live ? Theme.text : Theme.warn
                                    }
                                    Column {
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: 168
                                        Text {
                                            text: modelData.label
                                            color: Theme.text
                                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                                        }
                                        Text {
                                            // the port IS the key, so show it rather than
                                            // implying the name is bound to the hardware
                                            text: "port " + modelData.port +
                                                  (modelData.live ? "" : " — " + modelData.status)
                                            color: modelData.live ? Theme.textFaint : Theme.warn
                                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontS - 1
                                        }
                                    }
                                    QQC.TextField {
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: 150
                                        text: win.nameFor(modelData.id)
                                        placeholderText: "name…"
                                        color: Theme.text
                                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                                        background: Rectangle {
                                            color: Theme.button; radius: Theme.radiusSm
                                            border.color: Theme.cardBorder; border.width: 1
                                        }
                                        onEditingFinished: win.setControllerName(modelData.id, text)
                                    }
                                }
                            }
                        }

                        Divider {}
                        SectionHeader { text: "Backup & Restore" }
                        BackupPanel { width: parent.width }

                        // Firmware backup/restore is Cyclone/BR23-only; hide the
                        // whole section for controllers that don't support it.
                        Divider { visible: bridge.fwSupported }
                        SectionHeader { text: "Firmware Backup & Restore"; visible: bridge.fwSupported }
                        FirmwarePanel { width: parent.width; visible: bridge.fwSupported }

                        Divider {}

                        // ------------------------------------------ Diagnostics
                        SectionHeader { text: "Help & Diagnostics" }
                        Text {
                            width: parent.width; wrapMode: Text.WordWrap
                            text: "Something not working? Diagnostics checks whether Deadband "
                                + "can actually open your devices and tells you how to fix it — "
                                + "with a report you can paste into a GitHub issue."
                            color: Theme.textDim
                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        }
                        PillButton {
                            label: "🩺 Open diagnostics…"
                            onClicked: { diagWin.show(); diagWin.raise() }
                        }

                    }
                }
            }
        }
    }

    // Diagnostics window (Settings → Help & Diagnostics, or the access banner).
    // A separate top-level window; hidden until shown, auto-runs on first open.
    DiagnosticsWindow { id: diagWin }

    // Transient toast: read-back result of the last "Save to Profile" (Apply).
    // Confirms an edit actually landed on the hardware (vs. a silently-dropped
    // vendor write) — the answer to "I can't tell if it's applying".
    Rectangle {
        id: applyToast
        property bool ok: bridge.applyStatus.indexOf("✓") >= 0
        property bool busy: bridge.applyStatus.endsWith("…")   // any in-progress message
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

    // Same, for the MOUSE Apply — read-back result of the last staged write. Sits
    // above the mouse pending bar so a failed apply is no longer a silent no-op.
    Rectangle {
        id: mouseToast
        property bool ok: mouse.applyStatus.indexOf("✓") >= 0
        property bool busy: mouse.applyStatus.endsWith("…")    // any in-progress message
        visible: win.activeDevice === "mouse" && mouse.applyStatus.length > 0
        z: 9999
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 92
        radius: Theme.radius
        implicitWidth: Math.min(win.width - 60, mouseToastText.implicitWidth + 34)
        implicitHeight: 40
        color: Theme.card
        border.width: 1
        border.color: mouseToast.busy ? Theme.cardBorder
                                      : (mouseToast.ok ? Theme.ok : Theme.warn)
        Text {
            id: mouseToastText
            anchors.centerIn: parent; width: parent.width - 24
            horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight
            text: mouse.applyStatus
            color: mouseToast.busy ? Theme.textDim
                                   : (mouseToast.ok ? Theme.ok : Theme.warn)
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
            font.weight: Font.DemiBold
        }
        Timer { id: mouseToastTimer; interval: 4500; onTriggered: mouse.clearApplyStatus() }
        Connections {
            target: mouse
            function onApplyStatusChanged() {
                if (mouse.applyStatus.length > 0 && !mouseToast.busy)
                    mouseToastTimer.restart()
                else
                    mouseToastTimer.stop()
            }
        }
    }
}

pragma Singleton
import QtQuick

// Central design tokens, tuned to the GameSir Connect look:
// deep near-black background with a faint red glow, dark translucent cards,
// a single saturated red accent, soft rounded corners.
//
// The color tokens are now USER-THEMEABLE: the primaries below are plain
// (writable) properties so Settings → Appearance can override them live, and
// they persist via the appearance Settings (themeJson). A handful of secondary
// tokens are DERIVED from the primaries (accentDim/glow, cardHover, textFaint,
// track) so the whole palette stays coherent no matter what the user picks —
// change the accent and its dim/glow follow; change a card and its hover follows.
// `_def` holds the factory values so a reset (or a partial theme) restores them.
QtObject {
    id: theme

    // --- factory defaults (the shipped GameSir-red look) ---------------------
    readonly property var _def: ({
        accent:     "#E03A2F",
        bg:         "#0E0F13",
        bgGlow:     "#2A1416",
        card:       "#181A20",
        cardBorder: "#23262E",
        navBar:     "#14151A",
        button:     "#20232B",
        track:      "#2C2F38",
        ringSelect: "#FFFFFF",
        text:       "#F2F3F5",
        textDim:    "#9AA0AC"
    })

    // --- user-themeable primaries (writable; default to _def) ----------------
    property color accent:      _def.accent
    property color bg:          _def.bg
    property color bgGlow:      _def.bgGlow        // top-left reddish wash
    property color card:        _def.card
    property color cardBorder:  _def.cardBorder
    property color navBar:      _def.navBar
    property color button:      _def.button        // idle button/pill background
    property color track:       _def.track         // slider grooves + toggle off-track
    // Halo marking a SELECTED item on a colour surface the theme doesn't control —
    // e.g. the 8K home-ring quadrants, whose own colours are the user's LED choice.
    // Must contrast the CARD, so light themes need a dark value: a white glow on a
    // white card is invisible (same trap `track` hit).
    property color ringSelect:  _def.ringSelect
    property color text:        _def.text
    property color textDim:     _def.textDim

    // --- derived secondaries (track the primaries; direction flips by theme so
    // hover states stay visible on LIGHT themes too — lightening white is invisible)
    readonly property color accentDim:   Qt.darker(accent, 1.6)
    readonly property color accentGlow:  accent
    readonly property color cardHover:   _lightBg ? Qt.darker(card, 1.06)   : Qt.lighter(card, 1.22)
    readonly property color buttonHover: _lightBg ? Qt.darker(button, 1.06) : Qt.lighter(button, 1.18)
    readonly property color textFaint:   Qt.darker(textDim, 1.55)

    // --- semantic state colors ----------------------------------------------
    // Darken on LIGHT themes: a light amber/green (great on near-black) washes out
    // to invisible on a light background. Keyed off the background's lightness so
    // the "warn"/"ok" cues (DEMO badge, wrong-mode ⚠, connected dot) stay legible.
    readonly property bool _lightBg: bg.hslLightness > 0.55
    readonly property color ok:          _lightBg ? "#1E9E57" : "#3CCB7F"
    readonly property color warn:        _lightBg ? "#B07600" : "#E0B23A"

    // What reads on top of `accent`. Accent is user-settable and the presets span
    // deep red to light amber, where white collapses to a 2.15 contrast ratio —
    // below the 3.0 minimum even for large marks. Measured white-vs-accent:
    // red 4.36, violet 4.23, cobalt 3.68, but emerald 2.38 and amber 2.15.
    //
    // Must use WCAG RELATIVE LUMINANCE, not hslLightness: by HSL, red (0.53) reads
    // as *lighter* than amber (0.50), yet white is fine on red and unreadable on
    // amber — because luminance weights green ~10x blue and HSL ignores that.
    function _chan(v) { return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }
    function _lum(c)  { return 0.2126 * _chan(c.r) + 0.7152 * _chan(c.g) + 0.0722 * _chan(c.b) }
    readonly property bool accentIsLight: _lum(accent) > 0.30
    readonly property color onAccent:     accentIsLight ? "#1A1D24" : "#FFFFFF"

    // Ordered list of themeable tokens for the Settings UI (key + label).
    readonly property var themeKeys: [
        { key: "accent",     label: "Accent" },
        { key: "bg",         label: "Background" },
        { key: "bgGlow",     label: "Corner glow" },
        { key: "navBar",     label: "Top bar" },
        { key: "card",       label: "Card" },
        { key: "cardBorder", label: "Card border" },
        { key: "button",     label: "Button" },
        { key: "track",      label: "Slider" },
        { key: "ringSelect", label: "Selection glow" },
        { key: "text",       label: "Text" },
        { key: "textDim",    label: "Dim text" }
    ]

    // Named preset palettes. Any key omitted falls back to _def, so a preset can
    // restyle just the accent + surfaces and leave the rest at the shipped value.
    readonly property var presets: [
        { name: "GameSir Red",  colors: _def },
        { name: "Cobalt",       colors: { accent: "#3B82F6", bg: "#0B0E14", bgGlow: "#122036",
                                          navBar: "#111521", card: "#161B26", cardBorder: "#232B3A",
                                          button: "#1E2636", track: "#2C3648", ringSelect: "#FFFFFF", text: "#EEF2F8", textDim: "#94A0B4" } },
        { name: "Emerald",      colors: { accent: "#2FBF71", bg: "#0A0F0C", bgGlow: "#0F2A1C",
                                          navBar: "#101613", card: "#151C18", cardBorder: "#222C27",
                                          button: "#1D2620", track: "#2B372F", ringSelect: "#FFFFFF", text: "#EDF5F0", textDim: "#93A69C" } },
        { name: "Violet",       colors: { accent: "#8B5CF6", bg: "#0E0B14", bgGlow: "#20143A",
                                          navBar: "#15111F", card: "#1A1626", cardBorder: "#2A2340",
                                          button: "#241E36", track: "#342C4E", ringSelect: "#FFFFFF", text: "#F0ECF8", textDim: "#A198B4" } },
        { name: "Amber",        colors: { accent: "#F59E0B", bg: "#12100A", bgGlow: "#2E2410",
                                          navBar: "#1A1610", card: "#201C14", cardBorder: "#2E2A20",
                                          button: "#2A2418", track: "#38321F", ringSelect: "#FFFFFF", text: "#F6F1E8", textDim: "#B0A894" } },
        { name: "Slate (light)",colors: { accent: "#E03A2F", bg: "#E9ECF1", bgGlow: "#F3D9D6",
                                          navBar: "#DCE0E8", card: "#FFFFFF", cardBorder: "#CDD3DE",
                                          button: "#E6E9EF", track: "#C2C7D2", ringSelect: "#333A47", text: "#1A1D24", textDim: "#5C636F" } }
    ]

    // Apply a {key: colorString} map onto the writable primaries. Unknown keys
    // are ignored; missing keys are left as-is (use resetColors() first for a
    // clean preset apply).
    function applyColors(map) {
        for (var i = 0; i < themeKeys.length; i++) {
            var k = themeKeys[i].key
            if (map[k] !== undefined)
                theme[k] = map[k]
        }
    }

    // Restore every themeable token to its factory default.
    function resetColors() { applyColors(_def) }

    // Density: scales spacing/rounding/type together so the whole UI tightens or
    // relaxes at once (like Outlook's Compact/Cozy). Set via the Appearance
    // settings; every component binds these tokens so it updates live.
    property string density: "comfortable"     // "compact" | "comfortable" | "cozy"
    readonly property bool _compact: density === "compact"
    readonly property bool _cozy:    density === "cozy"

    // Metrics
    readonly property int radius:        _compact ? 8  : _cozy ? 12 : 10
    readonly property int radiusSm:      _compact ? 5  : _cozy ? 7  : 6
    readonly property int pad:           _compact ? 11 : _cozy ? 20 : 16
    readonly property int gap:           _compact ? 8  : _cozy ? 15 : 12
    // Vertical padding/spacing baselines (per density). Cards multiply these by
    // `vComp` so tiles compress vertically to fit a short window WITHOUT shrinking
    // their contents (fonts/controls stay full size). Horizontal padding is `pad`.
    readonly property int padV:          _compact ? 11 : _cozy ? 20 : 16
    readonly property int gapV:          _compact ? 8  : _cozy ? 15 : 12
    // 1.0 = full padding; a FitScroll drives this toward ~0.45 when its content
    // would overflow, so a page packs more rows before it has to scroll. Global
    // because only one page is visible at a time; reset to 1 on tab change.
    property real vComp: 1.0

    // Type
    readonly property string fontFamily: "Inter, Noto Sans, sans-serif"
    readonly property int fontXL:        _compact ? 18 : _cozy ? 22 : 20
    readonly property int fontL:         _compact ? 14 : _cozy ? 16 : 15
    readonly property int fontM:         _compact ? 12 : _cozy ? 14 : 13
    readonly property int fontS:         _compact ? 10 : _cozy ? 12 : 11
}

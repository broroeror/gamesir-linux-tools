import QtQuick
import QtMultimedia

// Muted, looping video background (webm/mp4/…). Kept in its own file so the
// QtMultimedia import is only pulled in when the user actually picks a video —
// a system without the multimedia backend still runs the app + image backgrounds.
// Driven by `src` / `fillModeStr`, set by the Loader in Main.qml (no reliance on
// the parent's ids/context, so it loads cleanly in isolation).
Item {
    id: root
    property url src: ""
    property string fillModeStr: "crop"

    VideoOutput {
        id: vo
        anchors.fill: parent
        fillMode: root.fillModeStr === "fit" ? VideoOutput.PreserveAspectFit
                : root.fillModeStr === "stretch" ? VideoOutput.Stretch
                : VideoOutput.PreserveAspectCrop     // video has no "tile" mode
    }

    MediaPlayer {
        id: player
        source: root.src
        videoOutput: vo
        audioOutput: AudioOutput { muted: true }     // background: always silent
        loops: MediaPlayer.Infinite
        onSourceChanged: if (source != "") play()
        // some backends stop at end-of-stream despite Infinite; nudge it back
        onPlaybackStateChanged: if (playbackState === MediaPlayer.StoppedState && source != "") play()
    }
}

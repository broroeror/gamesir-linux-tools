#!/usr/bin/env python3
"""Startup smoke test — catch the class of regression that hides at launch.

The app starts a couple of daemon threads (the reader + press-to-select) and then
loads the QML. A bad import inside a thread (like the research/ reorg breaking
press_select_loop) kills that thread with only a traceback on stderr — the app
still opens, so nothing looks wrong until a feature silently doesn't work. QML that
fails to load is similarly quiet. This test reproduces that startup and fails if
either happens.

    python3 smoke_test.py        # exit 0 = OK, 1 = a thread crashed / QML failed

No controller is required: with no hardware the threads just idle. Run it with the
GUI app CLOSED so the reader doesn't briefly double-drive a connected controller.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')   # headless Qt

import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# Record any exception that escapes a background thread's run() (Python 3.8+).
_crashes = []


def _excepthook(args):
    _crashes.append(args)
    threading.__excepthook__(args)          # still print the traceback


threading.excepthook = _excepthook


def _slot_signature_mismatches():
    """@Slot(...) type args that don't match the Python signature.

    Qt matches a QML call against the DECLARED types, so a wrong decorator makes
    the call fail at runtime ("Error: Insufficient arguments") while Python and
    every static checker see nothing wrong. Found in the wild: setPoll declared
    @Slot(str, int) but took one argument, so changing the poll rate silently did
    nothing (issue #6). Static, no device or GUI needed."""
    import ast
    out = []
    for path in ('bridge.py', 'mouse_bridge.py'):
        full = os.path.join(HERE, path)
        if not os.path.exists(full):
            continue
        for node in ast.walk(ast.parse(open(full).read())):
            if not isinstance(node, ast.FunctionDef):
                continue
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and getattr(dec.func, 'id', None) == 'Slot':
                    declared = len(dec.args)            # positional args are the types
                    takes = len(node.args.args) - 1 + len(node.args.kwonlyargs)
                    if declared != takes:
                        out.append(f'{path}:{node.lineno} {node.name}() declares '
                                   f'{declared} arg(s), takes {takes}')
    return out


def _foreign_pid_claims():
    """Config identities that belong to another GameSir product.

    An id from OTHER_PRODUCT_PIDS may only be in CONFIG_PIDS if it is also in
    SHARED_PIDS, i.e. resolved per device by is_g7_device(). 3537:1004 is the
    case in point: the G7 Pro White Trimode's dock identity AND the T4 Kaleid in
    mainline xpad. Claiming it blindly would drive a T4 Kaleid as a G7 Pro; this
    file used to forbid it outright, which wrongly locked White Trimode owners out
    (issue #14 was the kernel's label for that id, not a Deadband write). So:
    allow a shared id, but prove the discriminator actually discriminates."""
    try:
        from vendors.gamesir.models.g7pro import protocol as g7
    except Exception:
        return []
    bad = []
    for pid in set(g7.CONFIG_PIDS) & set(g7.OTHER_PRODUCT_PIDS):
        name = g7.OTHER_PRODUCT_PIDS[pid]
        if pid not in g7.SHARED_PIDS:
            bad.append(f'3537:{pid:04x} is the {name} and has no per-device check')
            continue
        if g7.is_g7_device(pid, f'GameSir {name}'):
            bad.append(f'3537:{pid:04x}: is_g7_device() claims a real {name}')
        if g7.is_g7_device(pid, None):
            bad.append(f'3537:{pid:04x}: is_g7_device() claims a device with no name')
        if not g7.is_g7_device(pid, 'GameSir-G7 Pro'):
            bad.append(f'3537:{pid:04x}: is_g7_device() rejects a real G7 Pro')
    return bad

def _profile_pid_overlaps():
    """USB ids claimed by more than one ControllerProfile.

    detect_one() walks ALL in order and returns the first match, so a duplicated
    id silently resolves to whichever profile is listed earlier -- and the loser
    gets the winner's register map. The project already carries two ids that are
    genuinely shared with another product (0575, 1004); both are resolved by a
    product-string check inside detect_one rather than by listing them twice.
    Adding a seventh and eighth profile is what makes this worth a check: the
    Kaleid's three ids sit a few digits from the G7 SE's and the Cyclone's."""
    try:
        import controller_profile as profiles
    except Exception:
        return []
    seen = {}
    bad = []
    for prof in profiles.ALL:
        for pid in prof.usb_products:
            if pid in seen and seen[pid] is not prof:
                bad.append(f'3537:{pid:04x} is claimed by both '
                           f'{seen[pid].name} and {prof.name}')
            seen[pid] = prof
    return bad


def _udev_pid_gaps():
    """Config identities with no udev rule granting raw USB access.

    The G7 Pro's config interfaces and the Kaleid's GIP channel are reached
    through libusb, so each one needs its own rule on the USB device. An id
    present in CONFIG_PIDS but missing from the rules file fails as "raw USB
    access: PERMISSION DENIED" in the diagnostics while everything else looks
    correct -- a confusing failure, and an easy one to create, since adding a
    model or edition means editing two files. This is the second table in this
    project that drifted from its source of truth, so it gets checked rather
    than remembered."""
    try:
        from vendors.gamesir.models.g7pro import protocol as g7
        from vendors.gamesir.models.kaleid import protocol as kal
    except Exception:
        return []
    try:
        rules = open(os.path.join(HERE, '70-gamesir.rules')).read().lower()
    except OSError:
        return ['70-gamesir.rules is missing']
    needed = [(pid, g7.edition_name(pid) or 'transition')
              for pid in g7.CONFIG_PIDS + g7.TRANSITION_PIDS]
    needed += [(pid, 'Kaleid') for pid in kal.CONFIG_PIDS]
    return [f'3537:{pid:04x} ({name}) has no udev rule'
            for pid, name in needed if f'"{pid:04x}"' not in rules]


def _connection_kind_gaps():
    """Config identities connection_kind() cannot classify as wired or dongle.

    The wired/dongle split is what drives the UI's connection hint and the
    firmware panel's warning. It was hand-listed as 109b/109c and did not grow
    when 10ba was added, so Amazon-edition owners saw a blank hint (issue #10).
    Every CONFIG_PID must land in exactly one of WIRED_PIDS / DONGLE_PIDS --
    both or neither is a bug."""
    try:
        from vendors.gamesir.models.g7pro import protocol as g7
    except Exception:
        return []
    bad = []
    for pid in g7.CONFIG_PIDS:
        w, d = pid in g7.WIRED_PIDS, pid in g7.DONGLE_PIDS
        if w and d:
            bad.append(f'3537:{pid:04x} ({g7.edition_name(pid)}) is BOTH wired and dongle')
        elif not w and not d:
            bad.append(f'3537:{pid:04x} ({g7.edition_name(pid)}) is neither wired nor dongle')
    return bad


def _doctor_identity_gaps():
    """G7 Pro identities the app knows but the diagnostics would skip.

    doctor.py only reports a G7 Pro whose PID is in its G7_IDENTITIES table.
    That table once named 109b/109c by hand, so when 10ba was promoted to a
    config identity it disappeared from every report while the app drove it
    fine -- the fourth table in this project to drift from CONFIG_PIDS."""
    try:
        import doctor
        from vendors.gamesir.models.g7pro import protocol as g7
        from vendors.gamesir.models.kaleid import protocol as kal
    except Exception:
        return []
    known = set(g7.CONFIG_PIDS) | set(g7.TRANSITION_PIDS) | set(g7.UNCONFIRMED_PIDS) \
        | {g7.PID_NATIVE} | set(kal.ALL_PIDS)
    return [f'3537:{pid:04x} is invisible to the diagnostics'
            for pid in sorted(known) if pid not in doctor.USB_IDENTITIES]


def _qml_handler_named_properties():
    """QML property declarations whose name looks like a signal handler.

    `property color onAccent` on an object that also has an `accent` property is
    parsed as the handler for that property, not as a property: a binding
    expression becomes the handler body, the property keeps its default, and
    nothing warns. Theme.onAccent sat at #000000 for three months that way. Any
    `on` + capital-letter property name is the same trap waiting for a sibling."""
    import re
    pat = re.compile(r'\bproperty\s+[\w.<>]+\s+(on[A-Z]\w*)')
    bad = []
    for root, _dirs, files in os.walk(os.path.join(HERE, 'qml')):
        for name in files:
            if name.endswith('.qml'):
                path = os.path.join(root, name)
                for i, line in enumerate(open(path, encoding='utf-8'), 1):
                    m = pat.search(line)
                    if m and not line.lstrip().startswith('//'):
                        bad.append(f'{os.path.relpath(path, HERE)}:{i} declares {m.group(1)}')
    return bad


def _qml_missing_bridge_members():
    """bridge.<name> / mouse.<name> used in QML that the Python object lacks.

    QML reads a missing property as `undefined` and silently carries on: the
    profile bar rendered zero pills (profileCount, Sept) and the Reset-profile
    button never appeared (profileResetSupported, deleted Sept 8, found Oct 6).
    Both were deleted together by one refactor. This reads every member name the
    QML uses and checks it exists on the class."""
    import re
    from bridge import GamesirBridge
    from mouse_bridge import MouseBridge
    classes = {'bridge': GamesirBridge, 'mouse': MouseBridge}
    pat = re.compile(r'\b(bridge|mouse)\.([A-Za-z_]\w*)')
    missing = {}
    for root, _dirs, files in os.walk(os.path.join(HERE, 'qml')):
        for name in files:
            if not name.endswith('.qml'):
                continue
            path = os.path.join(root, name)
            for i, line in enumerate(open(path, encoding='utf-8'), 1):
                code = line.split('//', 1)[0]
                for obj, member in pat.findall(code):
                    if not hasattr(classes[obj], member):
                        missing.setdefault(f'{obj}.{member}', f'{os.path.relpath(path, HERE)}:{i}')
    return [f'{k} (first used at {v})' for k, v in sorted(missing.items())]


def main():
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from reader import read_controller, press_select_loop
    from bridge import GamesirBridge

    # 1) Start the same daemon threads deadband.main() starts. A bad import
    #    (top-level or lazy) crashes them within milliseconds of the thread start.
    threads = {
        'read_controller': threading.Thread(target=read_controller, daemon=True),
        'press_select_loop': threading.Thread(target=press_select_loop, daemon=True),
    }
    for t in threads.values():
        t.start()

    # 2) Load the QML headless — catches syntax / missing-import / bad-component
    #    errors (an empty rootObjects means Main.qml did not load).
    app = QGuiApplication(sys.argv)
    qml_dir = os.path.join(HERE, 'qml')
    engine = QQmlApplicationEngine()
    engine.addImportPath(qml_dir)
    bridge = GamesirBridge()
    engine.rootContext().setContextProperty('bridge', bridge)
    engine.rootContext().setContextProperty('appVersion', 'smoke')
    engine.rootContext().setContextProperty(
        'assetsDir', QUrl.fromLocalFile(os.path.join(HERE, 'assets') + os.sep).toString())
    engine.load(QUrl.fromLocalFile(os.path.join(qml_dir, 'Main.qml')))
    qml_ok = bool(engine.rootObjects())

    # 3) Let the threads run their startup and Qt settle for a moment.
    deadline = time.time() + 1.5
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)

    # --- report ---------------------------------------------------------------
    slot_bad = _slot_signature_mismatches()
    udev_bad = _udev_pid_gaps()
    foreign = _foreign_pid_claims()
    kind_bad = _connection_kind_gaps()
    doc_bad = _doctor_identity_gaps()
    overlap = _profile_pid_overlaps()
    qml_on = _qml_handler_named_properties()
    qml_missing = _qml_missing_bridge_members()
    ok = (qml_ok and not slot_bad and not udev_bad and not foreign and not kind_bad
          and not doc_bad and not overlap and not qml_on and not qml_missing)
    print("=== startup smoke test ===")
    print(f"  QML (Main.qml) loaded : {'OK' if qml_ok else 'FAIL — did not load'}")
    print(f"  @Slot signatures      : "
          + ('OK' if not slot_bad else f'FAIL — {len(slot_bad)} mismatch(es)'))
    for m in slot_bad:
        print(f"      {m}")
    print(f"  udev vs CONFIG_PIDS   : "
          + ('OK' if not udev_bad else f'FAIL — {len(udev_bad)} gap(s)'))
    for m in udev_bad:
        print(f"      {m}")
    print(f"  wired/dongle coverage : "
          + ('OK' if not kind_bad else f'FAIL — {len(kind_bad)} gap(s)'))
    for m in kind_bad:
        print(f"      {m}")
    print(f"  diagnostics coverage  : "
          + ('OK' if not doc_bad else f'FAIL — {len(doc_bad)} gap(s)'))
    for m in doc_bad:
        print(f"      {m}")
    print(f"  profile PID overlaps  : "
          + ('OK' if not overlap else f'FAIL — {len(overlap)}'))
    for m in overlap:
        print(f"      {m}")
    print(f"  QML on[A-Z] properties: "
          + ('OK' if not qml_on else f'FAIL — {len(qml_on)} found'))
    for m in qml_on:
        print(f"      {m}")
    print(f"  QML bridge members    : "
          + ('OK' if not qml_missing else f'FAIL — {len(qml_missing)} missing'))
    for m in qml_missing:
        print(f"      {m}")
    print(f"  foreign PID claims    : "
          + ('OK' if not foreign else f'FAIL — {len(foreign)}'))
    for m in foreign:
        print(f"      {m}")
    for name, t in threads.items():
        alive = t.is_alive()
        ok = ok and alive
        print(f"  thread {name:18}: {'alive' if alive else 'DEAD — crashed on startup'}")
    if _crashes:
        ok = False
        print(f"\n  {len(_crashes)} background thread(s) raised on startup:")
        for c in _crashes:
            print(f"    {c.exc_type.__name__}: {c.exc_value}")

    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())

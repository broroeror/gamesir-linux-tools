#!/usr/bin/env python3
"""t3pro -- configure the original GameSir Tarantula Pro (dongle 3537:103e) on Linux.

Every write is read back and compared. `backup` before anything else.

  t3pro info
  t3pro backup [FILE]                 full raw dump as JSON
  t3pro light                         show mode/brightness/speed and zone colours
  t3pro light --mode breathing --brightness 80 --speed 50
  t3pro color ZONE H,S,V [H,S,V ...]   e.g. color 5 0,100,100 85,100,100 170,100,100 34,100,100
  t3pro macro L4 A:0-50 B:300-350     button:start_ms-end_ms ... [--hold] [--loop MS]
  t3pro macro L4 --clear
  t3pro vibration [--left 0-100] [--right 0-100] [--gain 0.0-2.0]
  t3pro rumble [L R]                   short vibration test (0-255)
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from vendors.gamesir.models.t3pro import protocol as p  # noqa: E402


def hsv(s):
    h, sat, v = (int(x) for x in s.split(','))
    if not (0 <= h <= 255 and 0 <= sat <= 100 and 0 <= v <= 100):
        raise argparse.ArgumentTypeError('H 0-255, S 0-100, V 0-100')
    return (h, sat, v)


def step(s):
    btn, span = s.split(':')
    a, b = (int(x) for x in span.split('-'))
    btn = btn.upper()
    if btn not in p.KEYS or b <= a:
        raise argparse.ArgumentTypeError(f'bad step {s!r}')
    return (btn, a, b)


def cmd_info(t, a):
    print(json.dumps(t.device_info(), indent=2))


def cmd_backup(t, a):
    data = t.dump()
    data['_taken'] = time.strftime('%Y-%m-%d %H:%M:%S')
    path = a.file or os.path.expanduser(
        f'~/.local/share/t3pro/backup-{time.strftime("%Y%m%d-%H%M%S")}.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    print('backup written:', path)


def show_light(t):
    lp = t.get_light_param()
    mode = {v: k for k, v in p.LIGHT_MODES.items()}.get(lp['mode'], lp['mode'])
    print(f"mode={mode} brightness={lp['brightness']} speed={lp['speed']}")
    for z in p.LIGHT_ZONES:
        print(f'zone {z}:', ' '.join(f'{h},{s},{v}' for h, s, v in t.get_light_color(z)))


def cmd_light(t, a):
    if a.mode is None and a.brightness is None and a.speed is None:
        return show_light(t)
    cur = t.get_light_param()
    want = {'brightness': cur['brightness'] if a.brightness is None else a.brightness,
            'speed': cur['speed'] if a.speed is None else a.speed,
            'mode': cur['mode'] if a.mode is None else p.LIGHT_MODES[a.mode]}
    t.set_light_param(**want)
    t.save()
    time.sleep(0.3)
    got = t.get_light_param()
    print('ok' if got == want else f'MISMATCH: wanted {want}, read {got}')


def cmd_color(t, a):
    if a.zone not in p.LIGHT_ZONES:
        sys.exit(f'zone must be one of {p.LIGHT_ZONES}')
    cur = t.get_light_color(a.zone)
    leds = list(a.leds) + cur[len(a.leds):]
    t.set_light_color(a.zone, leds)
    t.save()
    time.sleep(0.3)
    got = t.get_light_color(a.zone)
    # the pad converts through its own HSV maths: allow +-2 on hue
    ok = all(abs(g[0] - w[0]) <= 2 and g[1:] == w[1:] for g, w in zip(got, leds))
    print('ok' if ok else f'MISMATCH: wanted {leds}, read {got}')


def cmd_macro(t, a):
    key = a.key.upper()
    if a.clear:
        t.clear_macro(key)
        t.save()
        print('cleared')
        return
    if not a.steps:
        for i in range(p.MACRO_MAX_STEPS):
            s = t.get_macro_step(key, i)
            if len(s) < 8 or s[6] == p.MAP_VACANT:
                break
            print(i, p.KEY_NAMES.get(s[8], s[8]), f'{(s[12] << 8 | s[13])}-{(s[14] << 8 | s[15])} ms')
        else:
            pass
        return
    t.set_macro(key, a.steps, hold_to_trigger=a.hold, loop=a.loop is not None,
                loop_time_ms=a.loop or 0)
    t.save()
    time.sleep(0.3)
    bad = []
    for i, (btn, s0, e0) in enumerate(a.steps):
        s = t.get_macro_step(key, i)
        got = (p.KEY_NAMES.get(s[8]), s[12] << 8 | s[13], s[14] << 8 | s[15])
        if got != (btn, s0, e0):
            bad.append((i, got))
    print('ok' if not bad else f'MISMATCH in steps: {bad}')


def cmd_vibration(t, a):
    import json
    cfg_path = os.path.expanduser('~/.config/t3pro/bridge.json')
    try:
        cfg = json.load(open(cfg_path))
    except (OSError, ValueError):
        cfg = {}
    if a.left is not None or a.right is not None:
        cur = t.get_vibrate_level()
        want = (cur[0] if a.left is None else a.left, cur[1] if a.right is None else a.right)
        t.set_vibrate_level(*want)
        t.save()
        time.sleep(0.3)
        got = t.get_vibrate_level()
        print('pad level ok' if got == want else f'MISMATCH: wanted {want}, read {got}')
    if a.gain is None:
        if a.left is None and a.right is None:
            print(f"software gain (bridge): {cfg.get('rumble_gain', 1.0)}")
            l, r = t.get_vibrate_level()
            print(f'pad vibrate level: left {l}%  right {r}%')
        return
    cfg['rumble_gain'] = a.gain
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    json.dump(cfg, open(cfg_path, 'w'), indent=2)
    print(f'software gain set to {a.gain}; restart the bridge: systemctl --user restart t3pro-bridge')


def cmd_rumble(t, a):
    t.vibrate_test(a.left, a.right)
    time.sleep(0.6)
    t.vibrate_test(0, 0)


def main():
    ap = argparse.ArgumentParser(prog='t3pro', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-v', '--verbose', action='store_true', help='print raw packets')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('info')
    b = sub.add_parser('backup'); b.add_argument('file', nargs='?')
    li = sub.add_parser('light')
    li.add_argument('--mode', choices=list(p.LIGHT_MODES))
    li.add_argument('--brightness', type=int, choices=range(0, 101), metavar='0-100')
    li.add_argument('--speed', type=int, choices=range(0, 101), metavar='0-100')
    c = sub.add_parser('color'); c.add_argument('zone', type=int); c.add_argument('leds', type=hsv, nargs='+')
    m = sub.add_parser('macro'); m.add_argument('key', choices=[k for k in p.MACRO_KEYS] + [k.lower() for k in p.MACRO_KEYS])
    m.add_argument('steps', type=step, nargs='*'); m.add_argument('--clear', action='store_true')
    m.add_argument('--hold', action='store_true', help='run while held (default: one shot per press)')
    m.add_argument('--loop', type=int, metavar='MS', help='repeat, with this cycle time')
    vb = sub.add_parser('vibration', help='show/set vibration intensity')
    vb.add_argument('--gain', type=float, help='bridge software gain 0.0-2.0 (1.0 = as the game asks)')
    vb.add_argument('--left', type=int, choices=range(0, 101), metavar='0-100', help='pad left grip level %%')
    vb.add_argument('--right', type=int, choices=range(0, 101), metavar='0-100', help='pad right grip level %%')
    r = sub.add_parser('rumble'); r.add_argument('left', type=int, nargs='?', default=160)
    r.add_argument('right', type=int, nargs='?', default=160)
    a = ap.parse_args()
    with p.Tarantula(verbose=a.verbose) as t:
        globals()['cmd_' + a.cmd](t, a)


if __name__ == '__main__':
    main()

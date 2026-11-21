#!/usr/bin/env python3
"""Guided IMU axis/sign/scale check for the Tarantula Pro over its dongle.

Each step: put the pad in the start pose, press A, do the motion within ~3 s
and hold still until the next prompt. Prints, per step, the integrated angle of
each gyro axis (assuming 16.4 LSB per deg/s) and the accelerometer change.
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from vendors.gamesir.models.t3pro import protocol as p  # noqa: E402

STEPS = [
    ('bias', 'Deixe o controle PARADO em cima da mesa, botoes para cima.'),
    ('pitch', 'Controle deitado na mesa. Depois do A: levante a FRENTE (lado dos gatilhos) '
              'ate ficar em pe, ~90 graus, e segure parado.'),
    ('roll', 'Volte a deitar na mesa. Depois do A: incline para a DIREITA (pegada direita '
             'desce) ~90 graus e segure.'),
    ('yaw', 'Volte a deitar na mesa. Depois do A: gire o controle sobre a mesa ~90 graus '
            'para a ESQUERDA (anti-horario visto de cima) e segure.'),
]
REC = 4.0


def frames(t):
    while True:
        try:
            r = os.read(t.fd, 64)
        except BlockingIOError:
            time.sleep(0.001)
            continue
        if r[:4] == bytes([6, 0x1A, 0x0A, 3]):
            yield time.time(), r[4:]


def imu(e):
    a = struct.unpack_from('>hhh', e, 11)
    g = struct.unpack_from('>hhh', e, 17)
    return a, g


def wait_a(src):
    prev = None
    for _, e in src:
        a = e[6] >> 1 & 1
        if prev == 0 and a == 1:
            return
        prev = a


def main():
    t = p.Tarantula()
    t.set_gamepad_state_report(1)
    src = frames(t)
    bias = (0, 0, 0)
    try:
        for name, text in STEPS:
            print(f'\n[{name}] {text}\n   -> aperte A para comecar', flush=True)
            wait_a(src)
            print('   gravando... faca o movimento e aperte A de novo quando terminar' if name != 'bias'
                  else '   gravando 3 s, nao mexa...', flush=True)
            prev_a = 1
            t0 = time.time(); last = None; ang = [0.0, 0.0, 0.0]; acc0 = acc1 = None
            gs = []
            for ts, e in src:
                acc, gyr = imu(e)
                if acc0 is None:
                    acc0 = acc
                acc1 = acc
                gs.append(gyr)
                if last is not None:
                    dt = ts - last
                    for i in range(3):
                        ang[i] += (gyr[i] - bias[i]) / 16.4 * dt
                last = ts
                a_now = e[6] >> 1 & 1
                if name == 'bias':
                    if ts - t0 > 3:
                        break
                elif prev_a == 0 and a_now == 1 and ts - t0 > 0.3:
                    break
                prev_a = a_now
            if name == 'bias':
                bias = tuple(sum(g[i] for g in gs) / len(gs) for i in range(3))
                print(f'   bias gyro = {tuple(round(b, 1) for b in bias)}  accel = {acc1}')
            else:
                print(f'   angulo integrado (graus) gyro[0..2] = {tuple(round(x) for x in ang)}')
                print(f'   accel inicio {acc0} -> fim {acc1}')
        print('\npronto.')
    finally:
        t.set_gamepad_state_report(0)
        t.close()


if __name__ == '__main__':
    main()

# Media-key fix

The Cyclone 2 and G7 Pro describe their media keys in a way Linux can't read. This
HID-BPF program corrects that description when the controller connects. The
[Manual](../../MANUAL.md#volume-and-media-keys-do-nothing-cyclone-2-g7-pro) has the
install steps.

`0010-GameSir__Cyclone-2.bpf.c` is GPL-2.0, as HID-BPF programs must be; the rest of
Deadband is MIT. The `.bpf.o` is built from it. To rebuild, with `src/bpf` from
[udev-hid-bpf](https://gitlab.freedesktop.org/libevdev/udev-hid-bpf):

```sh
clang -target bpf -O2 -g -D__TARGET_ARCH_x86 -I<udev-hid-bpf>/src/bpf \
      -c 0010-GameSir__Cyclone-2.bpf.c -o full.o
llvm-strip -g -o 0010-GameSir__Cyclone-2.bpf.o full.o
```

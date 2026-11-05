// SPDX-License-Identifier: GPL-2.0
/*
 * GameSir Cyclone 2 (3537:100b, 3537:1053) and G7 Pro (3537:100a) report
 * descriptor fixup
 *
 * The consumer collection on interface 1 declares its range with a 1-byte
 * Usage Minimum and a 4-byte Usage Maximum:
 *
 * 0x06, 0x0c, 0x00,              // Usage Page (Consumer)       67
 * 0x85, 0x02,                    // Report ID (2)               74
 * 0x19, 0x00,                    // Usage Minimum (0)           76
 * 0x2b, 0xff, 0xff, 0x00, 0x00,  // Usage Maximum (0x0000ffff)  78
 *
 * A 4-byte usage carries its own page, so the kernel reads this as usages on
 * page 0, no Consumer Control input appears and every media key the pad sends
 * is dropped. Make it a 2-byte Usage Maximum so the range stays on the Consumer
 * page. 0x03ff covers the page's assigned usages and stays under HID_MAX_USAGES.
 * Push/Pop fill the two spare bytes so the descriptor keeps its length.
 */

#include "vmlinux.h"
#include "hid_bpf.h"
#include "hid_bpf_helpers.h"
#include <bpf/bpf_tracing.h>

#define VID_GAMESIR	0x3537
#define PID_CYCLONE_XINPUT	0x100B
#define PID_CYCLONE_XINPUT_ALT	0x1053
#define PID_G7_PRO_XINPUT	0x100A
#define RDESC_SIZE	214

HID_BPF_CONFIG(
	HID_DEVICE(BUS_USB, HID_GROUP_GENERIC, VID_GAMESIR, PID_CYCLONE_XINPUT),
	HID_DEVICE(BUS_USB, HID_GROUP_GENERIC, VID_GAMESIR, PID_CYCLONE_XINPUT_ALT),
	HID_DEVICE(BUS_USB, HID_GROUP_GENERIC, VID_GAMESIR, PID_G7_PRO_XINPUT)
);

SEC(HID_BPF_RDESC_FIXUP)
int BPF_PROG(hid_fix_rdesc_cyclone2, struct hid_bpf_ctx *hctx)
{
	__u8 *data = hid_bpf_get_data(hctx, 0, HID_MAX_DESCRIPTOR_SIZE);

	if (!data)
		return 0; /* EPERM check */

	if (data[76] == 0x19 && data[77] == 0x00 && data[78] == 0x2b &&
	    data[79] == 0xff && data[80] == 0xff && data[81] == 0x00 && data[82] == 0x00) {
		data[78] = 0x2a;	/* Usage Maximum, 2 bytes */
		data[79] = 0xff;
		data[80] = 0x03;
		data[81] = 0xa4;	/* Push */
		data[82] = 0xb4;	/* Pop */
	}

	return 0;
}

HID_BPF_OPS(cyclone2) = {
	.hid_rdesc_fixup = (void *)hid_fix_rdesc_cyclone2,
};

SEC("syscall")
int probe(struct hid_bpf_probe_args *ctx)
{
	ctx->retval = ctx->rdesc_size != RDESC_SIZE;
	if (ctx->retval)
		ctx->retval = -EINVAL;

	return 0;
}

char _license[] SEC("license") = "GPL";

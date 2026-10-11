#!/usr/bin/env python3
"""Sanity-check a UF2 image for the uc9900 keyboard.

usage: check-uf2.py <file.uf2>...

Checks every block's magic numbers, that the image targets the nRF52840
(family 0xADA52840) and starts at 0x1000 where the keyboard's bootloader
expects the application, and that the blocks are contiguous. Exits non-zero
on the first problem. Used by CI and handy before flashing a download.
"""
import struct
import sys

MAGIC0, MAGIC1, MAGIC_END = 0x0A324655, 0x9E5D5157, 0x0AB16F30
FAMILY_NRF52840 = 0xADA52840
APP_START = 0x1000
BLOCK = 512


def check(path):
    data = open(path, "rb").read()
    if len(data) == 0 or len(data) % BLOCK:
        return f"size {len(data)} is not a multiple of {BLOCK}"
    blocks = len(data) // BLOCK
    expect_addr = None
    for i in range(blocks):
        b = data[i * BLOCK:(i + 1) * BLOCK]
        m0, m1, flags, addr, size, num, total, family = struct.unpack_from("<8I", b, 0)
        (end,) = struct.unpack_from("<I", b, BLOCK - 4)
        if (m0, m1, end) != (MAGIC0, MAGIC1, MAGIC_END):
            return f"block {i}: bad magic"
        if not flags & 0x2000 or family != FAMILY_NRF52840:
            return f"block {i}: family {family:#x}, expected {FAMILY_NRF52840:#x}"
        if num != i or total != blocks:
            return f"block {i}: numbering {num}/{total} does not match {i}/{blocks}"
        if size != 256:
            return f"block {i}: payload {size} bytes, expected 256"
        if i == 0 and addr != APP_START:
            return f"starts at {addr:#x}, expected {APP_START:#x}"
        if expect_addr is not None and addr != expect_addr:
            return f"block {i}: address {addr:#x}, expected {expect_addr:#x} (gap)"
        expect_addr = addr + size
    print(f"{path}: {blocks} blocks, {blocks * 256} bytes of code at {APP_START:#x}-{expect_addr:#x}, nRF52840")
    return None


def main(paths):
    if not paths:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    rc = 0
    for p in paths:
        err = check(p)
        if err:
            print(f"{p}: {err}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

# ocp8178-backlight

A DKMS build of the uConsole's backlight driver (`ocp8178_bl`) that exposes all **32 brightness levels** of the OCP8178 LED driver instead of the stock driver's 10.

## Why

The OCP8178 takes a 5-bit level (0–31) over its one-wire interface. The ClockworkPi kernel driver registers the backlight with `max_brightness = 9` and maps those ten steps onto the chip through a fixed table: `{0, 1, 4, 8, 12, 16, 20, 24, 28, 31}`. Everything in userspace — `brightnessctl`, the brightness keys, waybar's backlight module — sees ten levels, so each press jumps ~11%, and asking for anything in between rounds back to one of the ten.

This tweak is the same driver source with `max_brightness = 31` and the value sent to the chip as-is. The device tree's `default-brightness` (written on the 0–9 scale, `5` in the uConsole overlays) is still translated through the old table, so the panel comes up at the same level it always did (`5` → `16` of 31).

One behavioural difference from the stock module, on purpose. The stock driver resets the chip (a ~3 ms LED-off shutdown + detect sequence) before every write, which strobes under key repeat but also recovers a chip that has dropped out of its 1-wire mode. The upstream branch has since switched to streaming bare frames and only resetting when coming from off, which is flicker-free but cannot recover if the chip ever leaves 1-wire mode. This build does both: writes that arrive within a second of the previous one are streamed, and the first write after a longer pause re-enters 1-wire mode first. Holding a brightness key is smooth; the first press after a pause may show a barely visible blink.

Source: `drivers/video/backlight/ocp8178_bl.c` from [ak-rex/ClockworkPi-linux](https://github.com/ak-rex/ClockworkPi-linux) (`rpi-7.1.y`), GPL-2.0.

## How it is installed

The package ships the module source to `/usr/src/ocp8178-backlight-<version>/` and registers it with DKMS. DKMS builds it against the running kernel's headers and installs it under `/lib/modules/<kernel>/updates/dkms/`, which depmod prefers over the stock copy in `kernel/drivers/video/backlight/`. The kernel package is not modified; DKMS rebuilds the module automatically when a new kernel (with headers) is installed.

Requirements: `dkms` (declared dependency) and the headers for the running kernel (`linux-headers-$(uname -r)`, shipped alongside the kernel in the ClockworkPi apt repo).

## Activating it

**Reboot.** Do not unload and reload the module on a running system: the panel driver (`panel-cwu50`) looks its backlight device up once at probe and keeps that reference. After a `modprobe -r` / `modprobe` cycle the panel's DPMS off/on drives the old, unregistered device and never reaches the new one, so the next screen blank leaves the panel dark until a reboot.

```sh
cat /sys/class/backlight/backlight@0/max_brightness   # 31 after the reboot
```

`systemd-backlight` saves the raw level at shutdown and restores it at boot. The first boot after switching restores a value saved on the 0–9 scale, so the panel may come up dim once; press brightness-up and it saves the new scale from then on.

## Checking

```sh
dkms status ocp8178-backlight            # ocp8178-backlight/<ver>, <kernel>, aarch64: installed
modinfo -n ocp8178_bl                    # .../updates/dkms/ocp8178_bl.ko*
for i in $(seq 1 31); do brightnessctl set $i; sleep 0.1; done
```

## Reverting

`sudo dpkg -r uconsole-tweaks` removes the DKMS module; the stock driver is used again after a reboot. To keep the package but drop just this module: `sudo dkms remove ocp8178-backlight/<version> --all`, then reboot.

## Pairing

The brightness keys in [hyprland-wm-config](https://github.com/syndr/hyprland-wm-config) step in raw hardware levels (`scripts/Brightness.sh`), so with this module each press is one of the 32 levels.

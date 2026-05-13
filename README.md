# uConsole-tweaks

Small standalone tweaks for the [ClockworkPi uConsole](https://www.clockworkpi.com/uconsole), packaged as a single `.deb`. Each tweak lives under `tweaks/<name>/` in the source tree; the build script bundles them all into one `uconsole-tweaks` package.

For larger systems built around uConsole-specific behavior (sleep / power management, etc.) see the sibling repo [uConsole-sleep](https://github.com/syndr/uConsole-sleep).

## Tweaks

| Name | What it does |
| --- | --- |
| [`zmk-cursor-scroll`](tweaks/zmk-cursor-scroll) | While the gamepad `Select` key is held, the trackball drives the scroll wheel instead of the cursor. |

## Install

```sh
make install      # builds uconsole-tweaks.deb and runs `apt install -y ./uconsole-tweaks.deb`
```

`apt install` of a local deb auto-resolves the declared `Depends:` (currently `python3`, `python3-evdev`, `keyd`), so you don't need a separate `make deps` step.

To just build the deb without installing:

```sh
make build
ls uconsole-tweaks.deb
```

## Uninstall

```sh
make uninstall    # dpkg -r uconsole-tweaks
```

## Other targets

```sh
make status       # systemctl status for shipped services
make logs         # journalctl -f -u <each shipped service>
make reinstall    # clean + install
make clean        # remove build artifacts
make help         # list all targets
```

## Adding a new tweak

1. Create `tweaks/<your-tweak>/` with the files it needs (script, unit, udev rule, ...).
2. Extend `make_uconsole-tweaks_package.sh` to copy the new files into the staging tree and (if it ships a systemd unit) enable it in `DEBIAN/postinst` and disable it in `DEBIAN/prerm`.
3. Add it to the `SERVICES :=` line in the `Makefile` if you want it picked up by `make status` / `make logs`.
4. Document it in this README.

## License

MIT — see [LICENSE](LICENSE).

# uConsole-tweaks

Small standalone tweaks for the [ClockworkPi uConsole](https://www.clockworkpi.com/uconsole) that don't justify a package of their own. Each tweak lives in its own subdirectory under `tweaks/` with a self-contained `install.sh` / `uninstall.sh` pair, so they can be picked up individually.

For larger systems built around uConsole-specific behavior (sleep / power management, etc.) see the sibling repo [uConsole-sleep](https://github.com/syndr/uConsole-sleep).

## Tweaks

| Name | What it does |
| --- | --- |
| [`zmk-cursor-scroll`](tweaks/zmk-cursor-scroll) | While the gamepad `Select` key is held, the trackball drives the scroll wheel instead of the cursor. |

## Install

Install every tweak:

```sh
./install.sh
```

Install only specific tweaks:

```sh
./install.sh zmk-cursor-scroll
```

Each tweak's installer is idempotent — re-running it after edits will refresh the installed files and restart the service.

## Uninstall

```sh
./uninstall.sh                  # remove every tweak
./uninstall.sh zmk-cursor-scroll
```

## Adding a new tweak

1. Create `tweaks/<your-tweak>/` with whatever files it needs (script, unit, udev rule, etc.).
2. Add an executable `install.sh` and `uninstall.sh` to that directory. Keep them self-contained — the top-level wrappers just invoke them.
3. Document it in this README.

## License

MIT — see [LICENSE](LICENSE).

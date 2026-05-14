# keyd-uconsole

[keyd](https://github.com/rvaiya/keyd) configuration for the uConsole's internal ZMK keyboard. Ships as `/etc/keyd/uconsole.conf` so it composes with any other keyd configs the user may already have.

## What it does

- **Tab (hold) → Super.** `overloadt2(meta, tab, 200)` — Tab fires its hold action (Super/Meta) only when held past 200 ms *or* when another key is pressed-and-released while Tab is held. Preserves normal Tab, Shift+Tab, and fast tab-tab autocomplete.
- **Select (hold) → KEY_F24.** `timeout(front, 200, f24)` — a tap of gamepad Select still emits `KEY_FRONT` (so games and any app that maps Select still see it); holding Select past 200 ms emits `KEY_F24` instead. `KEY_F24` is unmapped in essentially all userspace, so apps don't react to it — but the [`zmk-cursor-scroll`](../zmk-cursor-scroll) daemon latches on it to enter scroll mode. Without this rebind, the Select keypress itself leaks to the focused app as a real keystroke, which terminals and other scrollback-aware UIs interpret as "exit scrollback / jump to bottom" — snapping the view to the live tail right when you're trying to scroll up.
- **Scopes keyd to the keyboard sub-device only.** The `[ids]` block targets the ZMK keyboard's full identifier (`vid:pid:hash`) so keyd does not grab the trackball, which lives on the same USB composite device.

This scoping is also what makes [`zmk-cursor-scroll`](../zmk-cursor-scroll) work — keyd's grab on the keyboard sub-device is what creates the virtual keyboard (`vid:pid 0fac:0ade`) that the scroll daemon listens on.

## The device hash

`93631e17` is the keyd-computed hash of the ZMK keyboard's USB descriptor on stock uConsole firmware. If you run custom ZMK firmware, the hash may differ. To find yours:

```sh
sudo keyd monitor
```

Press any key on the internal keyboard — keyd will log the full `vendor:product:hash` of the device that emitted it. Drop that value into the `[ids]` block.

If you'd rather not pin the hash, replace the `[ids]` line with bare `1d50:615e` — but keyd will then grab both the keyboard and the trackball interfaces, breaking pointer motion. Pinning the hash is the supported configuration.

## Migrating from a hand-rolled `default.conf`

If you previously put this same content in `/etc/keyd/default.conf`, delete that file (or remove the conflicting `[ids]` block) after installing the package, then `sudo keyd reload`. Two configs with the same `[ids]` block produces undefined behavior.

## Debugging

```sh
sudo keyd monitor       # live key events with device IDs
sudo systemctl status keyd
sudo keyd reload        # re-read /etc/keyd/*.conf without restart
```

# battery-gauge

A voltage-based battery percentage for the uConsole, to work around the AXP223
PMIC's **stuck fuel-gauge register**.

## The problem

The uConsole's power management chip is an **AXP223**. Its voltage and current
ADCs read correctly, but its fuel-gauge *percentage* register gets stuck — on
this board it pins at **100%** even while the pack is actively discharging:

```
$ cat /sys/class/power_supply/axp20x-battery/{status,capacity,voltage_now,current_now}
Discharging
100            # <- wrong
3621000        # 3.621 V under load — nowhere near full
-1376000       # -1.376 A, i.e. really discharging
```

The kernel exports that register as `capacity`, and everything downstream trusts
it: `upower`, waybar's built-in `battery` module, hyprlock, swaync. Net effect —
no usable battery indicator and **no low-battery warning** before the board hard-
cuts around 3.0 V.

Recalibrating the AXP223 gauge itself is unreliable on these boards, so instead
we ignore the broken register and estimate state-of-charge from the voltage,
which is accurate.

## How it works

`/usr/local/bin/uconsole-battery` reads `voltage_now` / `current_now` / `status`,
reconstructs the pack's open-circuit voltage by compensating for the IR drop
under load, and maps that to a percentage via a Li-ion OCV curve:

```
OCV = V_terminal + |I| * R_internal   (discharging: add the sag back)
OCV = V_terminal - |I| * R_internal   (charging: remove the rise)
SoC = interpolate(OCV) on the Li-ion OCV curve
```

Output modes:

| Invocation | Output |
| --- | --- |
| `uconsole-battery` | waybar custom-module JSON (`text`, `alt`, `percentage`, `tooltip`, `class`) |
| `uconsole-battery --percent` | just the integer, e.g. `27` |
| `uconsole-battery --text` | `27% (discharging)` |

It's stateless (waybar re-runs it on an interval) apart from a small EMA smoothing
value cached in `$XDG_RUNTIME_DIR`.

## Wiring it into waybar

The deb ships only the script — waybar config is yours/ML4W-managed, so wire it
up manually. See [`waybar-custom-uconsole-battery.jsonc`](waybar-custom-uconsole-battery.jsonc):

1. In your active config (`~/.config/waybar/config` →
   `~/.config/waybar/configs/<name>`), replace `"battery"` in the `modules-*`
   array with `"custom/uconsole-battery"`.
2. Merge the `"custom/uconsole-battery": { … }` block into that config.
3. The emitted `class` matches the built-in module's names
   (`charging`/`full`/`warning`/`critical`/`discharging`), so existing
   `#battery.warning` etc. CSS can be reused as `#custom-uconsole-battery.warning`.
4. Reload waybar.

Other consumers (e.g. `~/.config/hypr/scripts/Battery.sh`) can call
`uconsole-battery --text` instead of reading the broken `capacity` file.

## Tuning

Constants at the top of the script:

| Constant | Meaning |
| --- | --- |
| `BATTERY_NAME` | Preferred power-supply name (`axp20x-battery`); falls back to the first `Battery`-type supply. |
| `R_INTERNAL_OHMS` | **The main accuracy lever.** Pack internal resistance used to turn loaded voltage into OCV. Default `0.12`. Too low → pessimistic under load; too high → optimistic. |
| `MAX_IR_CORRECTION_V` | Clamp on the IR correction so a current spike can't throw the estimate off the curve. |
| `EMA_ALPHA` | Cross-invocation smoothing (`0`=off … `1`=none). Damps jitter from current spikes. |
| `OCV_CURVE` | Per-cell open-circuit-voltage → SoC table, linearly interpolated. |

**Calibrating `R_INTERNAL_OHMS`:** let the pack sit near-idle (screen off) and
note `voltage_now` and `current_now`; that near-zero-load voltage is close to the
true OCV. Then under a known load, adjust `R_INTERNAL_OHMS` until the loaded
estimate lands on the same OCV.

## Accuracy caveats

Voltage-based gauging is approximate, and worst during **heavy charging**: at
~2 A charge current the IR correction is large, so the charging estimate is the
most sensitive to `R_INTERNAL_OHMS`. It is nonetheless dramatically better than a
gauge frozen at 100%, and — crucially — it moves, so low-battery states are
actually visible. The tooltip shows raw voltage/current so you can sanity-check,
and flags the stuck AXP223 reading when it disagrees.

## Requirements

- **Hardware**: uConsole with the AXP223 PMIC (`/sys/class/power_supply/axp20x-battery`).
- **Runtime**: `python3` (standard library only).

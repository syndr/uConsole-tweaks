# battery-gauge

A battery percentage for the uConsole that trusts the AXP223 fuel gauge while
it is working and falls back to a voltage-based estimate when it **gets stuck**.

## The problem

The uConsole's power management chip is an **AXP223**. It has a real coulomb-
counting fuel gauge, which the kernel exports as
`/sys/class/power_supply/axp20x-battery/capacity`, and when it works it is the
most accurate number available. But on these boards the gauge periodically
sticks — classically pinned at **100%** while the pack is actively discharging,
sometimes frozen at some other value:

```
$ cat /sys/class/power_supply/axp20x-battery/{status,capacity,voltage_now,current_now}
Discharging
100            # <- wrong
3621000        # 3.621 V under load — nowhere near full
-1376000       # -1.376 A, i.e. really discharging
```

Everything downstream trusts that register: `upower`, waybar's built-in
`battery` module, hyprlock, swaync. Net effect while it is stuck — no usable
battery indicator and **no low-battery warning** before the board hard-cuts
around 3.2 V. (The OCV curve's 0% point, 3.27 V open-circuit, sits just above
that cutoff, so the estimate reaches 0 right before the lights go out.) Recalibrating the AXP223 gauge itself is unreliable on these
boards, and the voltage and current ADCs *are* accurate, so we use those as an
independent check.

## How it works

`/usr/local/bin/uconsole-battery` reads `status` / `capacity` / `voltage_now` /
`current_now`, and always computes a voltage-based state-of-charge estimate by
reconstructing the pack's open-circuit voltage from the loaded terminal voltage
and mapping it onto a Li-ion OCV curve:

```
OCV = V_terminal + |I| * R_internal   (discharging: add the sag back)
OCV = V_terminal - |I| * R_internal   (charging: remove the rise)
SoC = interpolate(OCV) on the Li-ion OCV curve
```

That estimate is then used to **judge the kernel gauge**:

| Gauge judged | Displayed value |
| --- | --- |
| healthy | kernel `capacity` (the AXP223 fuel gauge) |
| stuck | the voltage estimate, until the gauge moves again |

The gauge is flagged **stuck** when any of these trips:

1. It reads `100` while `Discharging` and the voltage estimate is below
   `STUCK_FULL_MAX_EST_PCT` (85) — the classic signature.
2. It disagrees with the voltage estimate by more than `STUCK_DISAGREE_PCT`
   (25) points.
3. It has not changed while at least `STUCK_NO_MOVE_PCT` (4%) of the pack has
   flowed in or out since it last changed, measured by integrating
   `current_now` across runs. At ~1.3 A on the stock pack that is ~12 minutes.

Once flagged it stays flagged (hysteresis) until the gauge moves to a *new*
value, in the direction the charge status implies, that lands within
`RECOVER_AGREE_PCT` (12) points of the voltage estimate. If the `capacity`
attribute is unreadable the estimate is used outright.

The per-run state this needs (last reading, integrated charge flow since it
last changed, the stuck flag, the EMA of the estimate) lives in
`$XDG_RUNTIME_DIR/uconsole-battery.state`, along with the status timers and
averages described below; waybar re-runs the script on an interval with no
shared process. The time step between runs is capped at
`MAX_SAMPLE_GAP_S` (300 s), so a suspend or a stopped waybar doesn't book hours
of phantom charge flow.

### Time on battery, runtime, learned capacity

The tooltip also carries:

- **On battery / Charging for** — how long the current charge status has held.
  The runtime state is wiped at reboot, so on the first run after boot the
  status is assumed to have held since the kernel came up (marked "since
  boot"). Suspend time counts, as it should for a wall-clock figure.
- **Remaining / Full in** — remaining charge (displayed percent × pack
  capacity) divided by a moving average of the measured current with a
  `RUNTIME_TAU_S` (600 s) time constant, so a brief load spike doesn't swing
  it by an hour. Shown as "estimating…" until `RUNTIME_MIN_SPAN_S` (60 s) of
  samples exist since the status last changed. Time to full is hidden above
  `TIME_TO_FULL_MAX_PCT` (90) because the constant-voltage tail makes the
  current-based figure meaningless there, and is optimistic below it.
- **Pack** — the capacity in use and where it came from: `configured`
  (`PACK_CAPACITY_MAH`), `device tree` (`charge_full_design`, 6700 mAh on the
  stock pack) or `learned`.

**Capacity learning** (`LEARN_CAPACITY`, on by default): during a discharge
session — from unplugging until plugging in — the script integrates the
measured current and compares it with how far the gauge has dropped. Once the
drop reaches `LEARN_MIN_DROP_PCT` (30 points) the effective capacity,
`mAh flowed / points dropped × 100`, is written to
`$XDG_STATE_HOME/uconsole-battery/capacity.json` (`~/.local/state/…`) and
refined for the rest of the session. It survives reboots and overrides the
configured/device-tree value, which corrects for cell ageing and for packs
nobody configured. A session is discarded if the gauge is flagged stuck at any
point, if a sample gap exceeds `MAX_SAMPLE_GAP_S` (a suspend), or if the result
is outside 50–150% of the reference capacity. Delete the file to forget the
learned value.

### Bar text

`TEXT_FORMAT` (default `{pct}%`) is a Python `str.format` string with fields
`{pct}` `{volt}` `{amps}` `{watts}` `{remaining}` `{status}`, e.g.
`TEXT_FORMAT={pct}% {volt:.2f}V` shows `61% 3.68V` in the bar. A format that
fails to render falls back to the bare percentage.

Output modes:

| Invocation | Output |
| --- | --- |
| `uconsole-battery` | waybar custom-module JSON (`text`, `alt`, `percentage`, `tooltip`, `class`) |
| `uconsole-battery --percent` | just the integer, e.g. `27` |
| `uconsole-battery --text` | `27% (discharging, ~1h 05m left)` |
| `uconsole-battery --force-voltage` | always display the voltage estimate (the original behaviour) |
| `uconsole-battery --debug` | additionally log config overrides, state and the stuck decision to stderr |

The tooltip always shows the raw voltage/current, which source is in use, and
the other number — `Source: AXP223 gauge (voltage estimate 68%)` when healthy,
`Source: voltage estimate — AXP223 gauge stuck at 100%` when not.

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
   While the gauge is flagged stuck an extra `gauge-stuck` class is added, so
   `#custom-uconsole-battery.gauge-stuck { … }` can mark the fallback if you
   like.
4. Reload waybar.

Other consumers (e.g. `~/.config/hypr/scripts/Battery.sh`) can call
`uconsole-battery --text` instead of reading `capacity` directly.

## Configuration

Package defaults are constants at the top of the script. **Device-specific
values do not belong there** — put them in a config file instead, so they
survive reinstall and aren't baked into the package:

- `/etc/uconsole-battery.conf` (system-wide), then
- `~/.config/uconsole-battery.conf` (`$XDG_CONFIG_HOME`), which wins.

Format is `KEY=VALUE`, one per line, `#` comments. Every key is documented in
[`uconsole-battery.conf.example`](uconsole-battery.conf.example) (installed to
`/usr/share/doc/uconsole-tweaks/`). `uconsole-battery --debug` prints which
overrides were applied.

| Key | Meaning |
| --- | --- |
| `PACK_CAPACITY_MAH` | Total pack capacity. Default: unset → `charge_full_design` from sysfs (6700 mAh from the stock device tree). **Set this if you have fitted other cells**, e.g. `9000` for two 4500 mAh 21700s. Used for rule 3 and the runtime estimate until a learned value replaces it. |
| `R_INTERNAL_OHMS` | **The main accuracy lever for the estimate.** Pack internal resistance used to turn loaded voltage into OCV. Default `0.08`. Too low → pessimistic under load; too high → optimistic. |
| `MAX_IR_CORRECTION_V` | Clamp on the IR correction so a current spike can't throw the estimate off the curve. Default `0.35`. |
| `EMA_ALPHA` | Cross-invocation smoothing of the estimate (`1`=none). Default `0.5`. |
| `STUCK_FULL_MAX_EST_PCT` | Rule 1 threshold. Default `85`. |
| `STUCK_DISAGREE_PCT` | Rule 2 threshold. Default `25`. |
| `STUCK_NO_MOVE_PCT` | Rule 3 threshold, percent of `PACK_CAPACITY_MAH`. Default `4.0`. |
| `RECOVER_AGREE_PCT` | How close to the estimate a moved gauge must land to be trusted again. Default `12`. |
| `MAX_SAMPLE_GAP_S` | Cap on the time step used when integrating current. Default `300`. |
| `RUNTIME_TAU_S` | Time constant of the current average behind the runtime estimate. Default `600`. |
| `RUNTIME_MIN_SPAN_S` | Samples needed before a runtime figure is shown. Default `60`. |
| `TIME_TO_FULL_MAX_PCT` | Hide "Full in" above this. Default `90`. |
| `LEARN_CAPACITY` | Learn the effective pack capacity from discharge sessions. Default `true`. |
| `LEARN_MIN_DROP_PCT` | Gauge drop required before a learned value is written. Default `30`. |
| `TEXT_FORMAT` | Bar text format, see above. Default `{pct}%`. |
| `FORCE_VOLTAGE` | `true` to always display the estimate. Default `false`. |
| `BATTERY_NAME` | Preferred power-supply name. Default `axp20x-battery`; falls back to the first `Battery`-type supply. |
| `WARNING_PCT` / `CRITICAL_PCT` | waybar state thresholds. Defaults `30` / `15`. |

The `OCV_CURVE` table (per-cell open-circuit voltage → SoC) is only editable in
the script.

**Calibrating `R_INTERNAL_OHMS`:** run the bundled helper, which measures the
pack's internal resistance directly:

```sh
uconsole-battery-calibrate
```

It requires the device to be **on battery** (aborts if the charger is plugged
in). Turn the screen off and leave it alone; it samples the battery at idle,
spins every CPU core to draw a large extra current, samples again, and reports
`R = (V_idle - V_load) / (|I_load| - |I_idle|)` — the ohmic response to the
current step, with the unknown OCV cancelled out. Put the suggested value in
your config file as `R_INTERNAL_OHMS=<value>`. Run it a couple of times at
different charge levels and average if you want to be thorough.

Manual alternative: let the pack sit near-idle (screen off), note `voltage_now`
(≈ true OCV) and `current_now`, then under a known load adjust `R_INTERNAL_OHMS`
until the loaded estimate lands on that OCV.

## Accuracy caveats

The displayed number is the AXP223 gauge whenever it is judged healthy, so
normally accuracy is the chip's. The voltage estimate is approximate (roughly
±10 points), and worst during **heavy charging**: at ~2 A charge current the IR
correction is large, so the charging estimate is the most sensitive to
`R_INTERNAL_OHMS`. It is nonetheless dramatically better than a gauge frozen at
100%, and — crucially — it moves, so low-battery states are actually visible
while the gauge is stuck. Because the estimate is also the yardstick for rules
1–2, a badly wrong `R_INTERNAL_OHMS` can make a healthy gauge look stuck (or
vice versa); the tooltip shows both numbers so you can sanity-check.

## Requirements

- **Hardware**: uConsole with the AXP223 PMIC (`/sys/class/power_supply/axp20x-battery`).
- **Runtime**: `python3` (standard library only).

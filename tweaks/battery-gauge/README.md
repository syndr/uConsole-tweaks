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
| stuck | a charge count from the last trusted gauge value (see below), until the gauge moves again |

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
`RECOVER_AGREE_PCT` (12) points of the current best figure (the charge count
when there is one, else the voltage estimate). If the `capacity` attribute is
unreadable the gauge is treated as stuck.

### The fallback: charge counting anchored on the gauge

When the gauge is flagged, the display does not jump to the voltage estimate.
Every healthy run re-anchors a **coulomb count** at the gauge's value; once the
gauge sticks, the count continues from that anchor using the integrated
current and the pack capacity (`last good % − mAh flowed / capacity × 100`).
That makes the switch-over seamless and keeps the fallback within a point or
two over hours, where the voltage estimate alone can be ten points off. The
voltage estimate bounds it: if the two drift more than `CC_REANCHOR_PCT` (15)
apart the count is re-anchored on the estimate. The count is also lost across
a sample gap longer than `MAX_SAMPLE_GAP_S` (a suspend, where the current
drawn is not seen) and when the gauge has been stuck since boot; in both cases
it is anchored on the voltage estimate instead and counts on from there. The
tooltip says which: "charge count from last good gauge 61%" or "charge count
from voltage est 58%".

### Learning from the healthy gauge

Everything the gauge teaches us while it works is persisted under
`$XDG_STATE_HOME/uconsole-battery/` (`~/.local/state/…`), survives reboots and
is used from then on. `uconsole-battery --calibration` prints it all; delete
the files to start over.

- **Pack capacity** (`capacity.json`) — described under *Time on battery,
  runtime, learned capacity* below. Scales the charge count, the runtime
  estimate and stuck rule 3.
- **Curve offsets** (`calibration.json`, `LEARN_CURVE`) — on every healthy
  discharging run, the difference between the gauge and the raw voltage
  estimate is fed into a running mean for the estimate's 5-point bin. Once a
  bin has `CAL_MIN_SAMPLES` (20) samples its offset is applied, interpolated
  between bins and tapered to zero within 10 points outside the learned range,
  clamped to ±`CAL_MAX_OFFSET_PCT` (15). This removes the systematic mismatch
  between the stock Li-ion curve and your cells (on the author's 21700 pack the
  raw estimate ran 9–14 points low), so the estimate is a better yardstick for
  stuck detection and a better anchor when there is no gauge to anchor on.
  Samples with the gauge at 100 or ≤5 are skipped because it saturates there.
- **Internal resistance** (`calibration.json`, `LEARN_RESISTANCE`) — two
  consecutive discharging samples less than `R_LEARN_MAX_DT_S` (90 s) apart
  whose current differs by at least `R_LEARN_MIN_DI` (0.3 A) give
  `R = −ΔV / Δ|I|`, the same measurement `uconsole-battery-calibrate` makes
  with a forced load, taken passively from normal use. Values outside
  0.02–0.40 Ω are rejected; after `R_LEARN_MIN_SAMPLES` (10) steps the running
  mean replaces `R_INTERNAL_OHMS`. Useful when the pack has been changed and
  nobody re-ran the calibrate tool.

Tooltip text is escaped for Pango markup; a literal `<` or `&` in it (for
instance from `TEXT_FORMAT`) would otherwise blank the whole tooltip.

The tooltip's last line summarises the state: `Calibration: curve offset +9.2
here (6 bins, 412 samples); R 71 mΩ (learned, 38 steps)`.

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
- **Remaining / Full in** — remaining charge divided by a moving average of
  the measured current with a `RUNTIME_TAU_S` (300 s) time constant, so a
  brief load spike doesn't swing it by an hour. Remaining charge is measured
  in the gauge's own units whenever the gauge is healthy: each time it moves a
  point, the mAh that flowed while it sat there is one sample of *mAh per
  point*, averaged over recent moves (`RATE_ALPHA`). That makes the figure
  immune to a wrong `PACK_CAPACITY_MAH` and to whatever capacity the AXP223
  scales its percent against (on the author's unit the gauge moves about
  three times faster than the nominal pack would suggest). Before the first
  move, and while the gauge is stuck, the pack capacity is used instead; the
  tooltip names the basis. Shown as "estimating…" until `RUNTIME_MIN_SPAN_S`
  (60 s) of samples exist since the status last changed. Time to full is
  hidden above `TIME_TO_FULL_MAX_PCT` (90) because the constant-voltage tail
  makes the current-based figure meaningless there, and is optimistic below
  it.
- **Charger** (while charging) — an *estimate* of charger output. The AXP223
  has no ACIN voltage/current ADC (its IIO channels are the thermistor pin,
  battery voltage, charge/discharge current and die temperature), so the
  charger can't be measured. What can be: the power going into the pack
  (`voltage_now × current_now`), plus the system's own draw, which is what the
  pack was supplying during the last discharge (the 5-minute average, kept
  across the plug-in). The line says `Charger: ~8.3 W est. (2.8 W into pack +
  ~5.5 W system, from last discharge)`, or notes that the system draw hasn't
  been measured yet if the device booted on the charger. The system draw is
  as of the last discharge, so screen-off charging reads high and heavy use
  reads low.
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
| `uconsole-battery --calibration` | learned capacity, curve offsets and resistance as JSON |
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
   like. A `cpu-manual` class is added while a CPU profile is selected by
   hand (see [CPU governor](#cpu-governor)).
4. Reload waybar.

Other consumers (e.g. `~/.config/hypr/scripts/Battery.sh`) can call
`uconsole-battery --text` instead of reading `capacity` directly.

## CPU governor

Optional, and only with [uConsole-sleep](https://github.com/syndr/uConsole-sleep)
**1.8 or newer** installed. Its `sleep-cpu-governor` service switches the CPU
governor on battery level and AC state, and the battery widget is the natural
place to see and steer that. **Without uConsole-sleep the widget is exactly
the plain battery widget**: no extra tooltip line, no menu.

### Tooltip line

The last tooltip line says which governor is set and the service's own reason
for it. The wording comes from the service's state
(`/run/uconsole-sleep/cpu-governor.state`), never from the governor's name, so
`powersave` is not assumed to mean a low battery:

| Situation | Line |
| --- | --- |
| Battery under the service's low threshold | `CPU: powersave — automatic (battery below 20%)` |
| Recovering, inside the hysteresis band | `CPU: powersave — automatic (holding until 25%)` |
| Plugged in | `CPU: schedutil — automatic (on AC)` |
| Otherwise | `CPU: schedutil — automatic` |
| A profile was selected by hand | `CPU: performance — set manually (until reboot)` |
| uConsole-sleep installed, service stopped or older than 1.8 | `CPU: powersave — governor service not running or older than 1.8` |
| uConsole-sleep not installed | no line |

The percentages are the service's configured thresholds, read from its state.
While a profile is selected by hand the module also gets a `cpu-manual` CSS
class, so `#custom-uconsole-battery.cpu-manual { … }` can mark that the
automatic logic is off.

### Selecting a profile

```sh
uconsole-battery --cpu-profile                    # e.g. "schedutil — automatic (on AC)"
uconsole-battery --set-cpu-profile performance    # or any available governor
uconsole-battery --set-cpu-profile auto           # back to the automatic logic
```

A selection is a **current-boot setting**: it survives a service restart,
suspend and plugging / unplugging, and is gone after a reboot, when the
service starts in automatic again. Nothing is written to disk.

`--set-cpu-profile` waits up to 3 s for the service to apply the change and
prints the resulting line. It exits 2 for an unknown profile and 1 when the
service is not there; every failure is also raised as a desktop notification
(`notify-send`, if installed), because a waybar menu item has no terminal to
print to. Without uConsole-sleep the message is "CPU profile control needs the
uconsole-sleep package (>= 1.8)".

### Enable the CPU profile menu

Waybar can pop up a menu when a module is clicked (`man waybar-menu`; tested
with 0.12). The package
installs the menu itself, `/usr/share/uconsole-tweaks/waybar-cpu-profile-menu.ui`
(Automatic / Performance / Balanced = `schedutil` / Power save); the module
only has to point at it:

1. Install uConsole-sleep 1.8 or newer.
2. Add the `menu`, `menu-file` and `menu-actions` keys to the module: either
   uncomment them at the end of
   [`waybar-custom-uconsole-battery.jsonc`](waybar-custom-uconsole-battery.jsonc),
   or paste the output of `uconsole-battery --waybar-menu-snippet` into **each**
   `custom/uconsole-battery…` block of a config you already have. That command
   also says whether uConsole-sleep is detected right now. Reload waybar.

Left click then opens the menu. The tooltip catches up at the module's next
`interval`. With the keys in place but no uConsole-sleep, the items do nothing
except raise the "needs uconsole-sleep" notification.

For a waybar build without menu support, or for a keybind, there is
`uconsole-battery-profile-menu`: the same choice through `rofi` or `fuzzel`
(whichever is installed), listing every governor the service reports. Wire it
as `"on-click": "/usr/local/bin/uconsole-battery-profile-menu"`.

### For config generators

A script that generates waybar config can enable the menu exactly when it
would work, without knowing the keys:

```sh
if snippet="$(uconsole-battery --waybar-menu-snippet --if-available 2>/dev/null)"; then
    # insert "$snippet" inside the custom/uconsole-battery module block
fi
```

With `--if-available` the command prints the keys, comma-terminated so they
can go anywhere inside the block, and exits 0 **only if** uConsole-sleep and
the menu file are both installed; otherwise it prints nothing and exits 1.
Older versions of `uconsole-battery` reject the option and exit non-zero, so
the same test is safe against them.

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
| `R_INTERNAL_OHMS` | Pack internal resistance used to turn loaded voltage into OCV, until a learned value replaces it. Default `0.08`. Too low → pessimistic under load; too high → optimistic. |
| `MAX_IR_CORRECTION_V` | Clamp on the IR correction so a current spike can't throw the estimate off the curve. Default `0.35`. |
| `EMA_ALPHA` | Cross-invocation smoothing of the estimate (`1`=none). Default `0.5`. |
| `STUCK_FULL_MAX_EST_PCT` | Rule 1 threshold. Default `85`. |
| `STUCK_DISAGREE_PCT` | Rule 2 threshold. Default `25`. |
| `STUCK_NO_MOVE_PCT` | Rule 3 threshold, percent of `PACK_CAPACITY_MAH`. Default `4.0`. |
| `RECOVER_AGREE_PCT` | How close to the estimate a moved gauge must land to be trusted again. Default `12`. |
| `MAX_SAMPLE_GAP_S` | Cap on the time step used when integrating current. Default `300`. |
| `RUNTIME_TAU_S` | Time constant of the current average behind the runtime estimate. Default `300`. |
| `RATE_ALPHA` | EMA weight of the newest gauge move in the mAh-per-point scale. Default `0.4`. |
| `RUNTIME_MIN_SPAN_S` | Samples needed before a runtime figure is shown. Default `60`. |
| `TIME_TO_FULL_MAX_PCT` | Hide "Full in" above this. Default `90`. |
| `LEARN_CAPACITY` | Learn the effective pack capacity from discharge sessions. Default `true`. |
| `LEARN_MIN_DROP_PCT` | Gauge drop required before a learned value is written. Default `30`. |
| `CC_REANCHOR_PCT` | Re-anchor the charge count on the voltage estimate when they differ by more than this. Default `15`. |
| `LEARN_CURVE` / `CAL_MIN_SAMPLES` / `CAL_MAX_OFFSET_PCT` | Curve-offset learning: on/off, samples per bin before use, clamp. Defaults `true` / `20` / `15`. |
| `LEARN_RESISTANCE` / `R_LEARN_MIN_DI` / `R_LEARN_MAX_DT_S` / `R_LEARN_MIN_SAMPLES` | Resistance learning: on/off, minimum current step (A), maximum sample spacing (s), steps before use. Defaults `true` / `0.3` / `90` / `10`. |
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
normally accuracy is the chip's. While it is stuck the charge count is good to
a point or two per hour given a reasonable capacity figure. The raw voltage
estimate is approximate (roughly ±10 points before curve learning kicks in),
and worst during **heavy charging**: at ~2 A charge current the IR correction
is large, so the charging estimate is the most sensitive to the resistance
value. Because the estimate is the yardstick for rules 1–2 and the anchor of
last resort, a badly wrong resistance can make a healthy gauge look stuck (or
vice versa) until the learners correct it; the tooltip shows every number so
you can sanity-check, and `--calibration` shows what has been learned.

## Requirements

- **Hardware**: uConsole with the AXP223 PMIC (`/sys/class/power_supply/axp20x-battery`).
- **Runtime**: `python3` (standard library only).
- **Optional**: uConsole-sleep ≥ 1.8 for the CPU governor line and profile
  menu; `notify-send` for their error notifications; `rofi` or `fuzzel` for
  `uconsole-battery-profile-menu`.

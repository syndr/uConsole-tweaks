/* SPDX-License-Identifier: MIT
 *
 * Board-local APIs shared between the bb9900 sources.
 */
#pragma once

#include <stdbool.h>

/* Trackpad light on P0.10. `set` records the wanted state; the light is
 * actually on only when wanted and no gate (scroll mode, host asleep,
 * keyboard idle) holds it off. `refresh` re-applies the gates. */
int bb9900_trackpad_light_set(bool on);
void bb9900_trackpad_light_refresh(void);

/* Host sleep: true while the host reports itself asleep (HID LED bit) or
 * has suspended the USB link. */
bool bb9900_host_asleep(void);

/* A320 trackpad sensor polling. Disabled while the host sleeps. */
void bb9900_a320_set_enabled(bool enabled);

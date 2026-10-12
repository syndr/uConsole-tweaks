/* SPDX-License-Identifier: MIT */
#pragma once

#include <stdbool.h>

/* Scroll direction of the trackpad in scroll mode. false = natural (the
 * content follows the finger), true = inverted. Persisted in settings. */
bool bb9900_scroll_inverted(void);
int bb9900_scroll_inverted_toggle(void);

#include "bb9900.h"

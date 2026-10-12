/*
 * &scroll_dir_tog: flip the trackpad's scroll direction (natural/inverted)
 * and remember it.
 *
 * SPDX-License-Identifier: MIT
 */

#define DT_DRV_COMPAT uconsole_behavior_scroll_dir_toggle

#include <zephyr/device.h>
#include <zephyr/kernel.h>

#include <drivers/behavior.h>
#include <zmk/behavior.h>

#include "scroll_dir.h"

static int on_pressed(struct zmk_behavior_binding *binding,
                      struct zmk_behavior_binding_event event) {
    bb9900_scroll_inverted_toggle();
    return ZMK_BEHAVIOR_OPAQUE;
}

static int on_released(struct zmk_behavior_binding *binding,
                       struct zmk_behavior_binding_event event) {
    return ZMK_BEHAVIOR_OPAQUE;
}

static const struct behavior_driver_api scroll_dir_toggle_api = {
    .binding_pressed = on_pressed,
    .binding_released = on_released,
#if IS_ENABLED(CONFIG_ZMK_BEHAVIOR_METADATA)
    .get_parameter_metadata = zmk_behavior_get_empty_param_metadata,
#endif
};

#define SCROLL_DIR_TOGGLE_INST(n)                                                                  \
    BEHAVIOR_DT_INST_DEFINE(n, NULL, NULL, NULL, NULL, POST_KERNEL,                                \
                            CONFIG_KERNEL_INIT_PRIORITY_DEFAULT, &scroll_dir_toggle_api);

DT_INST_FOREACH_STATUS_OKAY(SCROLL_DIR_TOGGLE_INST)

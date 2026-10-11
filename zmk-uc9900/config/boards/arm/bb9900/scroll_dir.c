/*
 * Scroll-direction input processor: negates wheel events when inverted.
 * The flag is kept in Zephyr settings ("uc9900/scroll_inv") so the choice
 * survives a power cycle. Toggled by the scroll_dir_tog behavior.
 *
 * SPDX-License-Identifier: MIT
 */

#define DT_DRV_COMPAT uconsole_input_processor_scroll_dir

#include <zephyr/device.h>
#include <zephyr/dt-bindings/input/input-event-codes.h>
#include <zephyr/init.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/settings/settings.h>

#include <drivers/input_processor.h>

#include "scroll_dir.h"

LOG_MODULE_REGISTER(scroll_dir, CONFIG_ZMK_LOG_LEVEL);

static bool inverted;

bool bb9900_scroll_inverted(void) { return inverted; }

#if IS_ENABLED(CONFIG_SETTINGS)
static void save_work_cb(struct k_work *work) {
    settings_save_one("uc9900/scroll_inv", &inverted, sizeof(inverted));
}
static K_WORK_DELAYABLE_DEFINE(save_work, save_work_cb);

static int settings_load_cb(const char *name, size_t len, settings_read_cb read_cb, void *cb_arg) {
    const char *next;

    if (settings_name_steq(name, "scroll_inv", &next) && !next) {
        if (len != sizeof(inverted)) {
            return -EINVAL;
        }
        int rc = read_cb(cb_arg, &inverted, sizeof(inverted));
        return MIN(rc, 0);
    }
    return -ENOENT;
}

SETTINGS_STATIC_HANDLER_DEFINE(uc9900, "uc9900", NULL, settings_load_cb, NULL, NULL);
#endif

int bb9900_scroll_inverted_toggle(void) {
    inverted = !inverted;
    LOG_INF("scroll direction %s", inverted ? "inverted" : "natural");
#if IS_ENABLED(CONFIG_SETTINGS)
    k_work_reschedule(&save_work, K_MSEC(CONFIG_ZMK_SETTINGS_SAVE_DEBOUNCE));
#endif
    return 0;
}

static int scroll_dir_handle_event(const struct device *dev, struct input_event *event,
                                   uint32_t param1, uint32_t param2,
                                   struct zmk_input_processor_state *state) {
    if (inverted && event->type == INPUT_EV_REL &&
        (event->code == INPUT_REL_WHEEL || event->code == INPUT_REL_HWHEEL)) {
        event->value = -event->value;
    }
    return ZMK_INPUT_PROC_CONTINUE;
}

static const struct zmk_input_processor_driver_api scroll_dir_api = {
    .handle_event = scroll_dir_handle_event,
};

static int scroll_dir_init(const struct device *dev) { return 0; }

static int scroll_dir_settings_init(void) {
#if IS_ENABLED(CONFIG_SETTINGS)
    settings_subsys_init();
    settings_load_subtree("uc9900");
#endif
    return 0;
}

SYS_INIT(scroll_dir_settings_init, APPLICATION, CONFIG_APPLICATION_INIT_PRIORITY);

#define SCROLL_DIR_INST(n)                                                                         \
    DEVICE_DT_INST_DEFINE(n, scroll_dir_init, NULL, NULL, NULL, POST_KERNEL,                       \
                          CONFIG_KERNEL_INIT_PRIORITY_DEFAULT, &scroll_dir_api);

DT_INST_FOREACH_STATUS_OKAY(SCROLL_DIR_INST)

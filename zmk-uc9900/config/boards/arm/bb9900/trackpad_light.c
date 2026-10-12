/*
 * Trackpad light on P0.10. The vendor firmware drove this pin through its
 * Caps Lock indicator (lit while Caps Lock was off). Here it is a plain GPIO.
 *
 * The light is on when wanted (default: yes) and none of these gates holds
 * it off: the scroll layer is active (CONFIG_UC9900_SCROLL_LIGHT), the host
 * is asleep (CONFIG_UC9900_HOST_SLEEP), or the keyboard has gone idle
 * (CONFIG_UC9900_TRACKPAD_LIGHT_IDLE_OFF; a touch or a key counts as activity
 * and relights it).
 *
 * SPDX-License-Identifier: MIT
 */

#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/init.h>
#include <zephyr/logging/log.h>

#include <zmk/activity.h>
#include <zmk/event_manager.h>
#include <zmk/events/activity_state_changed.h>
#include <zmk/events/layer_state_changed.h>
#include <zmk/keymap.h>

#include "bb9900.h"

LOG_MODULE_REGISTER(trackpad_light, CONFIG_ZMK_LOG_LEVEL);

static const struct gpio_dt_spec light = GPIO_DT_SPEC_GET(DT_NODELABEL(trackpad_light_led), gpios);

static bool wanted = true;
static bool scrolling;

static bool host_asleep(void) {
#if IS_ENABLED(CONFIG_UC9900_HOST_SLEEP)
    return bb9900_host_asleep();
#else
    return false;
#endif
}

static bool idle(void) {
#if IS_ENABLED(CONFIG_UC9900_TRACKPAD_LIGHT_IDLE_OFF)
    return zmk_activity_get_state() != ZMK_ACTIVITY_ACTIVE;
#else
    return false;
#endif
}

void bb9900_trackpad_light_refresh(void) {
    if (!gpio_is_ready_dt(&light)) {
        return;
    }
    bool on = wanted && !scrolling && !host_asleep() && !idle();
    gpio_pin_set_dt(&light, on ? 1 : 0);
}

int bb9900_trackpad_light_set(bool on) {
    wanted = on;
    bb9900_trackpad_light_refresh();
    return 0;
}

static int trackpad_light_init(void) {
    if (!gpio_is_ready_dt(&light)) {
        LOG_ERR("trackpad light GPIO not ready");
        return 0;
    }
    if (gpio_pin_configure_dt(&light, GPIO_OUTPUT_ACTIVE) != 0) {
        LOG_ERR("trackpad light GPIO configure failed");
    }
    bb9900_trackpad_light_refresh();
    return 0;
}

SYS_INIT(trackpad_light_init, APPLICATION, CONFIG_APPLICATION_INIT_PRIORITY);

static int trackpad_light_listener(const zmk_event_t *eh) {
#if IS_ENABLED(CONFIG_UC9900_SCROLL_LIGHT)
    const struct zmk_layer_state_changed *lev = as_zmk_layer_state_changed(eh);
    if (lev != NULL && lev->layer == zmk_keymap_layer_index_to_id(CONFIG_UC9900_SCROLL_LAYER)) {
        scrolling = lev->state;
    }
#endif
    /* Activity changes are read live in idle(); nothing to store. */
    bb9900_trackpad_light_refresh();
    return ZMK_EV_EVENT_BUBBLE;
}

ZMK_LISTENER(trackpad_light, trackpad_light_listener);
#if IS_ENABLED(CONFIG_UC9900_SCROLL_LIGHT)
ZMK_SUBSCRIPTION(trackpad_light, zmk_layer_state_changed);
#endif
#if IS_ENABLED(CONFIG_UC9900_TRACKPAD_LIGHT_IDLE_OFF)
ZMK_SUBSCRIPTION(trackpad_light, zmk_activity_state_changed);
#endif

/*
 * Host Caps Lock = trackpad scroll mode, as on the vendor firmware, but done
 * by switching the scroll layer on and off, so it shares the direction and
 * speed of hold-Select scrolling. Nothing here touches P0.10.
 *
 * SPDX-License-Identifier: MIT
 */

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include <zmk/event_manager.h>
#include <zmk/events/hid_indicators_changed.h>
#include <zmk/keymap.h>

LOG_MODULE_REGISTER(caps_scroll, CONFIG_ZMK_LOG_LEVEL);

/* Bit 1 of the HID LED report (HID_USAGE_LED_CAPS_LOCK). */
#define CAPS_LOCK_BIT BIT(1)

static int caps_scroll_listener(const zmk_event_t *eh) {
    const struct zmk_hid_indicators_changed *ev = as_zmk_hid_indicators_changed(eh);

    if (ev == NULL) {
        return ZMK_EV_EVENT_BUBBLE;
    }

    zmk_keymap_layer_id_t layer = zmk_keymap_layer_index_to_id(CONFIG_UC9900_SCROLL_LAYER);
    bool caps = (ev->indicators & CAPS_LOCK_BIT) != 0;

    if (caps != zmk_keymap_layer_active(layer)) {
        LOG_DBG("caps lock %s: scroll layer %s", caps ? "on" : "off", caps ? "on" : "off");
        if (caps) {
            zmk_keymap_layer_activate(layer);
        } else {
            zmk_keymap_layer_deactivate(layer);
        }
    }
    return ZMK_EV_EVENT_BUBBLE;
}

ZMK_LISTENER(caps_scroll, caps_scroll_listener);
ZMK_SUBSCRIPTION(caps_scroll, zmk_hid_indicators_changed);

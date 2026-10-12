/*
 * Host sleep. The uConsole-sleep service on the host sets a bit of the HID
 * LED output report (Kana, bit 4, by default) just before it unbinds the USB
 * driver and suspends the link, and clears it after it rebinds; the USB
 * suspend itself is a second cue. While the host is asleep:
 *   - a keymap layer of &none sits on top, so no HID reports (and no USB
 *     remote-wakeup requests) are generated;
 *   - the A320 trackpad is no longer polled;
 *   - the keyboard backlight and the trackpad light are off, and stay off
 *     even though keypresses still move ZMK's activity state (the stock
 *     backlight listener would relight it; we re-assert afterwards).
 *
 * The backlight is driven through the LED device directly, not through
 * zmk_backlight_on/off: those persist to settings and would leave the
 * backlight logically off after wake.
 *
 * SPDX-License-Identifier: MIT
 */

#include <zephyr/device.h>
#include <zephyr/drivers/led.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/usb/usb_device.h>

#include <zmk/backlight.h>
#include <zmk/event_manager.h>
#include <zmk/events/activity_state_changed.h>
#include <zmk/events/hid_indicators_changed.h>
#include <zmk/events/layer_state_changed.h>
#include <zmk/events/usb_conn_state_changed.h>
#include <zmk/keymap.h>
#include <zmk/usb.h>

#include "bb9900.h"

LOG_MODULE_REGISTER(host_sleep, CONFIG_ZMK_LOG_LEVEL);

#define HOST_SLEEP_BIT BIT(CONFIG_UC9900_HOST_SLEEP_LED_BIT)

static bool led_says_asleep;
static bool usb_suspended;
static bool asleep;

#if IS_ENABLED(CONFIG_ZMK_BACKLIGHT) && DT_HAS_CHOSEN(zmk_backlight)
static const struct device *const backlight_dev = DEVICE_DT_GET(DT_CHOSEN(zmk_backlight));

static void backlight_apply(void) {
    if (!device_is_ready(backlight_dev)) {
        return;
    }
    uint8_t brt = 0;
    if (!asleep && zmk_backlight_is_on()) {
        brt = zmk_backlight_get_brt();
    }
    led_set_brightness(backlight_dev, 0, brt);
}
#else
static void backlight_apply(void) {}
#endif

bool bb9900_host_asleep(void) { return asleep; }

static void apply_lights(void) {
    backlight_apply();
    bb9900_trackpad_light_refresh();
}

/* Runs after the stock listeners that handled the same event. */
static void reassert_work_cb(struct k_work *work) {
    if (asleep) {
        apply_lights();
    }
}
static K_WORK_DEFINE(reassert_work, reassert_work_cb);

static void set_asleep(bool value) {
    if (value == asleep) {
        return;
    }
    asleep = value;
    LOG_INF("host %s", asleep ? "asleep" : "awake");

    zmk_keymap_layer_id_t layer = zmk_keymap_layer_index_to_id(CONFIG_UC9900_HOST_SLEEP_LAYER);
    if (asleep) {
        bb9900_a320_set_enabled(false);
        zmk_keymap_layer_activate(layer);
    } else {
        zmk_keymap_layer_deactivate(layer);
        bb9900_a320_set_enabled(true);
    }
    apply_lights();
}

static int host_sleep_listener(const zmk_event_t *eh) {
    const struct zmk_hid_indicators_changed *iev = as_zmk_hid_indicators_changed(eh);
    if (iev != NULL) {
        led_says_asleep = (iev->indicators & HOST_SLEEP_BIT) != 0;
        set_asleep(led_says_asleep || usb_suspended);
        return ZMK_EV_EVENT_BUBBLE;
    }

    if (as_zmk_usb_conn_state_changed(eh) != NULL) {
        usb_suspended = zmk_usb_get_status() == USB_DC_SUSPEND;
        set_asleep(led_says_asleep || usb_suspended);
        /* The stock backlight listener may also react to this event. */
        if (asleep) {
            k_work_submit(&reassert_work);
        }
        return ZMK_EV_EVENT_BUBBLE;
    }

    /* Activity and layer changes while asleep: the stock backlight listener
     * and our own trackpad light run on the same event; put ours last. */
    if (asleep) {
        k_work_submit(&reassert_work);
    }
    return ZMK_EV_EVENT_BUBBLE;
}

ZMK_LISTENER(host_sleep, host_sleep_listener);
ZMK_SUBSCRIPTION(host_sleep, zmk_hid_indicators_changed);
ZMK_SUBSCRIPTION(host_sleep, zmk_usb_conn_state_changed);
ZMK_SUBSCRIPTION(host_sleep, zmk_activity_state_changed);
ZMK_SUBSCRIPTION(host_sleep, zmk_layer_state_changed);

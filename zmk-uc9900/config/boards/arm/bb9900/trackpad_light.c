/*
 * Trackpad light on P0.10. The vendor firmware drove this pin through its
 * Caps Lock indicator (lit while Caps Lock was off). Here it is a plain GPIO,
 * lit at boot, with a setter for later use as a mode light.
 *
 * SPDX-License-Identifier: MIT
 */

#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/init.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(trackpad_light, CONFIG_ZMK_LOG_LEVEL);

static const struct gpio_dt_spec light = GPIO_DT_SPEC_GET(DT_NODELABEL(trackpad_light_led), gpios);

int bb9900_trackpad_light_set(bool on) {
    if (!gpio_is_ready_dt(&light)) {
        return -ENODEV;
    }
    return gpio_pin_set_dt(&light, on ? 1 : 0);
}

static int trackpad_light_init(void) {
    if (!gpio_is_ready_dt(&light)) {
        LOG_ERR("trackpad light GPIO not ready");
        return 0;
    }
    if (gpio_pin_configure_dt(&light, GPIO_OUTPUT_ACTIVE) != 0) {
        LOG_ERR("trackpad light GPIO configure failed");
    }
    return 0;
}

SYS_INIT(trackpad_light_init, APPLICATION, CONFIG_APPLICATION_INIT_PRIORITY);

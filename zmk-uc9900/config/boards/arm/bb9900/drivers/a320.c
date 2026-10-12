/*
 * Avago ADBS-A320 optical finger-navigation sensor, polled over I2C, reported
 * through Zephyr's input subsystem for ZMK's input listener.
 *
 * Register sequence (from the sensor datasheet and the vendor's driver,
 * ZitaoTech/zmk app/module/drivers/sensor/a320, MIT): reading Motion (0x02)
 * latches the deltas; bit 7 says motion happened, bit 4 that a delta
 * overflowed. Delta_X (0x03) and Delta_Y (0x04) are signed bytes.
 *
 * SPDX-License-Identifier: MIT
 */

#define DT_DRV_COMPAT avago_a320

#include <zephyr/device.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/input/input.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include "bb9900.h"

LOG_MODULE_REGISTER(a320, CONFIG_INPUT_LOG_LEVEL);

#define A320_REG_PRODUCT_ID 0x00
#define A320_REG_MOTION 0x02
#define A320_REG_DELTA_X 0x03
#define A320_REG_DELTA_Y 0x04
#define A320_REG_OFN_ENGINE 0x60

#define A320_PRODUCT_ID 0x83
#define A320_MOTION_MOT BIT(7)
#define A320_MOTION_OVF BIT(4)

/* How many polls to wait between attempts to (re)write OFN_Engine. */
#define A320_ENGINE_RETRY_POLLS 64

struct a320_config {
    struct i2c_dt_spec bus;
};

struct a320_data {
    const struct device *dev;
    struct k_work_delayable work;
    bool engine_ok;
    bool enabled;
    uint8_t discard; /* polls whose deltas are thrown away (stale motion after a restart) */
    uint32_t polls;
};

/* Motion accumulated while the sensor was not polled would arrive as one big
 * jump; the first polls after a (re)start are read and dropped instead. */
#define A320_DISCARD_POLLS 3

/* Single instance on this board; kept for the enable/disable API. */
static const struct device *a320_dev;

static int a320_read(const struct device *dev, uint8_t reg, uint8_t *val) {
    const struct a320_config *cfg = dev->config;

    return i2c_reg_read_byte_dt(&cfg->bus, reg, val);
}

/* Write OFN_Engine and read it back. The sensor is not reset when the
 * keyboard firmware restarts, so this is done even for 0x00. */
static bool a320_apply_engine(const struct device *dev) {
    const struct a320_config *cfg = dev->config;
    uint8_t val;

    if (a320_read(dev, A320_REG_OFN_ENGINE, &val) == 0 && val == CONFIG_INPUT_A320_OFN_ENGINE) {
        return true;
    }
    if (i2c_reg_write_byte_dt(&cfg->bus, A320_REG_OFN_ENGINE, CONFIG_INPUT_A320_OFN_ENGINE) != 0) {
        return false;
    }
    return a320_read(dev, A320_REG_OFN_ENGINE, &val) == 0 && val == CONFIG_INPUT_A320_OFN_ENGINE;
}

static void a320_poll(struct k_work *work) {
    struct k_work_delayable *dwork = k_work_delayable_from_work(work);
    struct a320_data *data = CONTAINER_OF(dwork, struct a320_data, work);
    const struct device *dev = data->dev;
    uint8_t motion, x, y;

    if (!data->enabled) {
        return;
    }
    data->polls++;
    if (!data->engine_ok && (data->polls % A320_ENGINE_RETRY_POLLS) == 1) {
        data->engine_ok = a320_apply_engine(dev);
        if (!data->engine_ok) {
            LOG_DBG("OFN_Engine not applied yet");
        }
    }

    if (a320_read(dev, A320_REG_MOTION, &motion) == 0 && (motion & A320_MOTION_MOT)) {
        if (a320_read(dev, A320_REG_DELTA_X, &x) == 0 && a320_read(dev, A320_REG_DELTA_Y, &y) == 0) {
            int8_t dx = (int8_t)x;
            int8_t dy = (int8_t)y;

            if (motion & A320_MOTION_OVF) {
                LOG_DBG("delta overflow");
            }
            if (data->discard > 0) {
                data->discard--;
            } else if (dx != 0 || dy != 0) {
                input_report_rel(dev, INPUT_REL_X, dx, false, K_FOREVER);
                input_report_rel(dev, INPUT_REL_Y, dy, true, K_FOREVER);
            }
        }
    }

    k_work_reschedule(&data->work, K_MSEC(CONFIG_INPUT_A320_POLL_INTERVAL_MS));
}

/* Flush any latched motion, re-arm the OFN_Engine write, and start polling. */
static void a320_start(const struct device *dev) {
    struct a320_data *data = dev->data;
    uint8_t v;

    a320_read(dev, A320_REG_MOTION, &v);
    a320_read(dev, A320_REG_DELTA_X, &v);
    a320_read(dev, A320_REG_DELTA_Y, &v);
    data->engine_ok = false;
    data->polls = 0;
    data->discard = A320_DISCARD_POLLS;
    data->enabled = true;
    k_work_reschedule(&data->work, K_MSEC(CONFIG_INPUT_A320_POLL_INTERVAL_MS));
}

/* Stop polling (host asleep). Left alone, the sensor drops into its own
 * rest modes after a while without motion; no register write is needed. */
void bb9900_a320_set_enabled(bool enabled) {
    if (a320_dev == NULL) {
        return;
    }
    struct a320_data *data = a320_dev->data;

    if (enabled && !data->enabled) {
        a320_start(a320_dev);
        LOG_INF("polling resumed");
    } else if (!enabled && data->enabled) {
        data->enabled = false;
        k_work_cancel_delayable(&data->work);
        LOG_INF("polling stopped");
    }
}

static int a320_init(const struct device *dev) {
    const struct a320_config *cfg = dev->config;
    struct a320_data *data = dev->data;
    uint8_t id = 0;

    data->dev = dev;
    k_work_init_delayable(&data->work, a320_poll);

    if (!device_is_ready(cfg->bus.bus)) {
        LOG_ERR("I2C bus %s is not ready", cfg->bus.bus->name);
        return -ENODEV;
    }

    /* Identify. A failure here is logged but never blocks boot: the keyboard
     * must work without the trackpad. */
    if (a320_read(dev, A320_REG_PRODUCT_ID, &id) != 0) {
        LOG_WRN("no answer from the sensor at 0x%02x", cfg->bus.addr);
    } else if (id != A320_PRODUCT_ID) {
        LOG_WRN("unexpected product id 0x%02x", id);
    }

    a320_dev = dev;
    a320_start(dev);
    LOG_INF("A320 polling every %d ms", CONFIG_INPUT_A320_POLL_INTERVAL_MS);
    return 0;
}

#define A320_DEFINE(inst)                                                                          \
    static struct a320_data a320_data_##inst;                                                      \
    static const struct a320_config a320_config_##inst = {                                         \
        .bus = I2C_DT_SPEC_INST_GET(inst),                                                         \
    };                                                                                             \
    DEVICE_DT_INST_DEFINE(inst, a320_init, NULL, &a320_data_##inst, &a320_config_##inst,           \
                          POST_KERNEL, CONFIG_INPUT_A320_INIT_PRIORITY, NULL);

DT_INST_FOREACH_STATUS_OKAY(A320_DEFINE)

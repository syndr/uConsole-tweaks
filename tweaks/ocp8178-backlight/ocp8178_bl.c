/*
 * ocp8178_bl.c - ocp8178 backlight driver
 *
 * uConsole-tweaks build: exposes all 32 brightness levels of the OCP8178.
 *
 * Based on drivers/video/backlight/ocp8178_bl.c from the ClockworkPi kernel
 * (https://github.com/ak-rex/ClockworkPi-linux, branch rpi-7.1.y). The stock
 * driver reports max_brightness = 9 and maps those ten steps onto the chip's
 * 0-31 range through a fixed table, which makes brightness keys jump ~11% per
 * press. Here max_brightness is 31 and the value is sent to the chip as-is;
 * the old table is kept only to translate the device tree's
 * "default-brightness" (written for the 0-9 scale) so boot brightness is
 * unchanged.
 *
 * Resync rule: the stock driver (as shipped in the ClockworkPi kernel
 * packages) runs the shutdown + detect sequence before EVERY write, which
 * blanks the LED for ~3 ms per change but also means a chip that has dropped
 * out of 1-wire mode is recovered by the next write. Upstream commit
 * 8385d8d31 ("only re-enter 1-wire mode on cold start") streams bare frames
 * instead and only resets on 0 -> N; flicker-free, but if the chip ever
 * leaves 1-wire mode (control line held low > ~2.5 ms) every later frame is
 * ignored and the panel stays dark. This build keeps the streaming for
 * back-to-back writes (key repeat) and re-enters 1-wire mode when the
 * previous write is more than RESYNC_IDLE_MS old, so the first press after
 * a pause resynchronises the chip the way the stock driver did.
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License version 2 as
 * published by the Free Software Foundation.
 */

#include <linux/backlight.h>
#include <linux/err.h>
#include <linux/fb.h>
#include <linux/gpio.h> /* Only for legacy support */
#include <linux/gpio/consumer.h>
#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/gpio/consumer.h>
#include <linux/platform_data/gpio_backlight.h>
#include <linux/platform_device.h>
#include <linux/slab.h>
#include <linux/delay.h>
#include <linux/timer.h>
#include <linux/poll.h>
#include <linux/proc_fs.h>
#include <linux/seq_file.h>
#include <linux/sched.h>
#include <linux/interrupt.h>
#include <linux/irq.h>
#include <linux/io.h>
#include <linux/clk.h>

struct ocp8178_backlight {
	struct device *dev;
	struct device *fbdev;

	struct gpio_desc *gpiod;
	int def_value;
	int current_value;
	bool onewire_ready;
	unsigned long last_write;	/* jiffies of the last frame sent */
};

#define DETECT_DELAY 200
#define DETECT_TIME 500
#define DETECT_WINDOW_TIME 1000
#define START_TIME 10
#define END_TIME 10
#define SHUTDOWN_TIME 3000
#define LOW_BIT_HIGH_TIME 10
#define LOW_BIT_LOW_TIME 50
#define HIGH_BIT_HIGH_TIME 50
#define HIGH_BIT_LOW_TIME 10
#define MAX_BRIGHTNESS_VALUE 31
/* Writes further apart than this re-enter 1-wire mode first (see header). */
#define RESYNC_IDLE_MS 1000
/* Scale the stock driver used for userspace and for "default-brightness". */
#define LEGACY_MAX_BRIGHTNESS_VALUE 9

static void entry_1wire_mode(struct ocp8178_backlight *gbl)
{
	unsigned long flags = 0;
	local_irq_save(flags);
	gpiod_set_value(gbl->gpiod, 0);
	mdelay(SHUTDOWN_TIME/1000);
	gpiod_set_value(gbl->gpiod, 1);
	udelay(DETECT_DELAY);
	gpiod_set_value(gbl->gpiod, 0);
	udelay(DETECT_TIME);
	gpiod_set_value(gbl->gpiod, 1);
	udelay(DETECT_WINDOW_TIME);
	local_irq_restore(flags);
}

static inline void write_bit(struct ocp8178_backlight *gbl, int bit)
{
	if (bit) {
		gpiod_set_value(gbl->gpiod, 0);
		udelay(HIGH_BIT_LOW_TIME);
		gpiod_set_value(gbl->gpiod, 1);
		udelay(HIGH_BIT_HIGH_TIME);
	} else {
		gpiod_set_value(gbl->gpiod, 0);
		udelay(LOW_BIT_LOW_TIME);
		gpiod_set_value(gbl->gpiod, 1);
		udelay(LOW_BIT_HIGH_TIME);
	}
}

static void write_byte(struct ocp8178_backlight *gbl, int byte)
{
	unsigned long flags = 0;
	unsigned char data = 0x72;
	int i;

	local_irq_save(flags);

	gpiod_set_value(gbl->gpiod, 1);
	udelay(START_TIME);
	for(i = 0; i < 8; i++) {
		if(data & 0x80) {
			write_bit(gbl, 1);
		} else {
			write_bit(gbl, 0);
		}
		data <<= 1;
	}
	gpiod_set_value(gbl->gpiod, 0);
	udelay(END_TIME);

	data = byte & 0x1f;

	gpiod_set_value(gbl->gpiod, 1);
	udelay(START_TIME);
	for(i = 0; i < 8; i++) {
		if(data & 0x80) {
			write_bit(gbl, 1);
		} else {
			write_bit(gbl, 0);
		}
		data <<= 1;
	}
	gpiod_set_value(gbl->gpiod, 0);
	udelay(END_TIME);
	gpiod_set_value(gbl->gpiod, 1);

	local_irq_restore(flags);
}

/*
 * The stock driver's 0-9 -> chip level table. Only used to map the device
 * tree default, which the uConsole overlays specify on the old 0-9 scale.
 */
static const unsigned char legacy_default_table[LEGACY_MAX_BRIGHTNESS_VALUE+1] =
	{0, 1, 4, 8, 12, 16, 20, 24, 28, 31};

static int ocp8178_update_status(struct backlight_device *bl)
{
	struct ocp8178_backlight *gbl = bl_get_data(bl);
	int brightness = bl->props.brightness;
	bool resync;

	if (bl->props.power != FB_BLANK_UNBLANK ||
	    bl->props.state & (BL_CORE_SUSPENDED | BL_CORE_FBBLANK))
		brightness = 0;

	if(brightness > MAX_BRIGHTNESS_VALUE)
		brightness = MAX_BRIGHTNESS_VALUE;

	/*
	 * The OCP8178 EasyScale 1-wire interface only needs the shutdown +
	 * re-detect sequence (entry_1wire_mode, which deliberately holds the
	 * LED off for ~3 ms to reset the chip) ONCE after power-up.  While the
	 * chip stays in 1-wire mode a brightness change is just a data frame
	 * (write_byte) with no LED-off reset -- and therefore no visible flash.
	 * Running entry_1wire_mode on every update (twice, as the original code
	 * did) is what blanked the panel on each change and made it strobe under
	 * the GUI brightness slider.
	 *
	 * Only re-detect when the backlight is coming on from a fully off /
	 * blanked state (cold start, DPMS unblank, resume), where the chip may
	 * have dropped out of 1-wire mode.  There the LED is dark anyway, so the
	 * reset is invisible.  Steady-state changes just stream a frame.
	 *
	 * uConsole-tweaks: also re-detect when the previous frame is older than
	 * RESYNC_IDLE_MS. Key repeat and slider drags stay flicker-free (frames
	 * arrive well inside the window); the first write after a pause pays
	 * one ~3 ms reset and recovers a chip that silently left 1-wire mode.
	 */
	resync = !gbl->onewire_ready ||
		 (gbl->current_value == 0 && brightness != 0) ||
		 time_after(jiffies,
			    gbl->last_write + msecs_to_jiffies(RESYNC_IDLE_MS));

	if (resync) {
		entry_1wire_mode(gbl);
		write_byte(gbl, brightness);
		entry_1wire_mode(gbl);
		write_byte(gbl, brightness);
		gbl->onewire_ready = true;
	} else {
		write_byte(gbl, brightness);
	}

	gbl->current_value = brightness;
	gbl->last_write = jiffies;

	return 0;
}

static int ocp8178_get_brightness(struct backlight_device *bl)
{
	struct ocp8178_backlight *gbl = bl_get_data(bl);
	return gbl->current_value;
}

static bool ocp8178_controls_device(struct backlight_device *bl, struct device *display_dev)
{
	struct ocp8178_backlight *gbl = bl_get_data(bl);
	return !gbl->fbdev || gbl->fbdev == display_dev;
}

static const struct backlight_ops ocp8178_backlight_ops = {
	.options = BL_CORE_SUSPENDRESUME,
	.update_status = ocp8178_update_status,
	.get_brightness = ocp8178_get_brightness,
	.controls_device = ocp8178_controls_device,
};

static int ocp8178_probe_dt(struct platform_device *pdev,
				   struct ocp8178_backlight *gbl)
{
	struct device *dev = &pdev->dev;
	struct device_node *np = dev->of_node;
	enum gpiod_flags flags;
	int ret = 0;
	u32 value32;

	/*
	 * "default-brightness" in the uConsole overlays is on the stock 0-9
	 * scale (e.g. 5). Translate it through the stock table so the panel
	 * comes up at the same level it always did (5 -> 16 of 31).
	 */
	value32 = 0;
	of_property_read_u32(np, "default-brightness", &value32);
	if (value32 > LEGACY_MAX_BRIGHTNESS_VALUE)
		value32 = LEGACY_MAX_BRIGHTNESS_VALUE;
	gbl->def_value = legacy_default_table[value32];
	flags = gbl->def_value ? GPIOD_OUT_HIGH : GPIOD_OUT_LOW;

	gbl->gpiod = devm_gpiod_get(dev, "backlight-control", flags);
	if (IS_ERR(gbl->gpiod)) {
		ret = PTR_ERR(gbl->gpiod);

		if (ret != -EPROBE_DEFER) {
			dev_err(dev,
				"Error: The gpios parameter is missing or invalid.\n");
		}
	}

	return ret;
}

static struct backlight_device *backlight;

static int ocp8178_probe(struct platform_device *pdev)
{
	struct backlight_properties props;
	struct backlight_device *bl;
	struct ocp8178_backlight *gbl;
	struct device_node *np = pdev->dev.of_node;
	int ret;

	if ( !np) {
		dev_err(&pdev->dev,
			"failed to find platform data or device tree node.\n");
		return -ENODEV;
	}

	gbl = devm_kzalloc(&pdev->dev, sizeof(*gbl), GFP_KERNEL);
	if (gbl == NULL)
		return -ENOMEM;

	gbl->dev = &pdev->dev;

	ret = ocp8178_probe_dt(pdev, gbl);
	if (ret)
		return ret;

	gbl->current_value = gbl->def_value;

	memset(&props, 0, sizeof(props));
	props.type = BACKLIGHT_RAW;
	props.max_brightness = MAX_BRIGHTNESS_VALUE;
	bl = devm_backlight_device_register(&pdev->dev, dev_name(&pdev->dev),
					&pdev->dev, gbl, &ocp8178_backlight_ops,
					&props);
	if (IS_ERR(bl)) {
		dev_err(&pdev->dev, "failed to register backlight\n");
		return PTR_ERR(bl);
	}

//	entry_1wire_mode(gbl);

	bl->props.brightness = gbl->def_value;
	backlight_update_status(bl);

	platform_set_drvdata(pdev, bl);

	backlight = bl;
	return 0;
}

static int ocp8178_suspend(struct platform_device *pdev, pm_message_t state)
{
	return 0;
}

static int ocp8178_resume(struct platform_device *pdev)
{
	return 0;
}

static struct of_device_id ocp8178_of_match[] = {
	{ .compatible = "ocp8178-backlight" },
	{ /* sentinel */ }
};

MODULE_DEVICE_TABLE(of, ocp8178_of_match);

static struct platform_driver ocp8178_driver = {
	.driver		= {
		.name		= "ocp8178-backlight",
		.of_match_table = of_match_ptr(ocp8178_of_match),
	},
	.probe		= ocp8178_probe,
	.suspend		= ocp8178_suspend,
	.resume		= ocp8178_resume,
};

module_platform_driver(ocp8178_driver);

MODULE_DESCRIPTION("OCP8178 backlight driver (32 levels, uConsole-tweaks)");
MODULE_LICENSE("GPL");

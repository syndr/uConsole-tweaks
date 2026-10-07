#!/usr/bin/python3
# uConsole Camera - a Picamera2 camera app sized for the ClockworkPi uConsole.
#
# Forked from Picamera2's apps/app_full.py (tag v0.3.37), Copyright (c) 2021,
# Raspberry Pi, BSD 2-Clause License - see LICENSE.picamera2. The camera
# control widgets, HDR bracketing and pan/zoom maths are upstream's; the layout,
# autofocus tab, save location, timestamped filenames, persisted preferences,
# keyboard shortcuts and the preview crash guard are uConsole-tweaks additions.
#
# Layout for a 1280x720 screen:
#   - the live preview fills the window,
#   - one bottom bar: Photo/Video, shutter, zoom, AF, settings toggle, status,
#   - one collapsible settings drawer on the right (show/hide only - never a
#     window resize, which is what glitched upstream's hide button on a tiling
#     compositor).

import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime

import numpy as np
from PyQt5.QtCore import QEvent, QSettings, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QKeySequence, QPainter, QPalette
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QShortcut,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from picamera2 import Picamera2
from picamera2.encoders import H264Encoder, Quality
from picamera2.outputs import FfmpegOutput, FileOutput

try:
    import cv2

    cv_present = True
except ImportError:
    cv_present = False
    print("OpenCV not found - HDR not available")


# --- Preferences --------------------------------------------------------------
# ~/.config/uconsole-camera/uconsole-camera.conf. Only "setup" choices are kept
# (where/what to save, resolutions, AF mode, window state); per-shot controls
# such as exposure, gains, tuning sliders and zoom start fresh every launch.

prefs_path = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "uconsole-camera", "uconsole-camera.conf"
)
prefs = QSettings(prefs_path, QSettings.IniFormat)


def pref(key, default):
    """Read a preference, coerced to the type of `default`."""
    val = prefs.value(key, default)
    if isinstance(default, bool):
        return str(val).lower() in ("true", "1", "yes")
    try:
        return type(default)(val)
    except (TypeError, ValueError):
        return default


def default_pictures_dir():
    base = os.environ.get("XDG_PICTURES_DIR")
    if not base:
        try:
            with open(os.path.expanduser("~/.config/user-dirs.dirs")) as f:
                for line in f:
                    if line.startswith("XDG_PICTURES_DIR="):
                        base = os.path.expandvars(line.split("=", 1)[1].strip().strip('"'))
        except OSError:
            pass
    return os.path.join(base or os.path.expanduser("~/Pictures"), "Camera")


def output_path(kind, ext, name=""):
    """Where the next capture goes: <dir>/<name or IMG_/VID_timestamp>.<ext>, never overwriting."""
    directory = capture_tab.video_dir() if kind == "VID" else capture_tab.photo_dir()
    os.makedirs(directory, exist_ok=True)
    stem = name.strip() or datetime.now().strftime(f"{kind}_%Y%m%d_%H%M%S")
    path = os.path.join(directory, f"{stem}.{ext}")
    n = 1
    while os.path.exists(path):
        path = os.path.join(directory, f"{stem}_{n}.{ext}")
        n += 1
    return path


# --- Camera -------------------------------------------------------------------

metadata_crop = None  # ScalerCrop libcamera actually applied to the latest frame


def post_callback(request):
    global metadata_crop
    metadata = request.get_metadata()
    metadata_crop = metadata.get("ScalerCrop", metadata_crop)
    if info_tab.isVisible():
        sorted_metadata = sorted(metadata.items(), key=lambda x: x[0] if "Awb" not in x[0] else f"Z{x[0]}")
        pretty_metadata = []
        for k, v in sorted_metadata:
            try:
                iter(v)
                if k == "ColourCorrectionMatrix":
                    matrix = np.around(np.reshape(v, (-1, 3)), decimals=2)
                    row = f"{k}:\n{matrix}"
                else:
                    row_data = [f'{x:.2f}' if type(x) is float else f'{x}' for x in v]
                    row = f"{k}: ({', '.join(row_data)})"
            except TypeError:
                row = f"{k}: {v:.2f}" if type(v) is float else f"{k}: {v}"
            pretty_metadata.append(row)
        info_tab.setText('\n'.join(pretty_metadata))

    if not aec_tab.exposure_time.isEnabled():
        aec_tab.exposure_time.setValue(metadata["ExposureTime"])
        aec_tab.analogue_gain.setValue(metadata["AnalogueGain"])
    if hasattr(aec_tab, "colour_gain_r") and not aec_tab.colour_gain_r.isEnabled():
        aec_tab.colour_gain_r.setValue(metadata.get("ColourGains", [1.0, 1.0])[0])
        aec_tab.colour_gain_b.setValue(metadata.get("ColourGains", [1.0, 1.0])[1])
    vid_tab.frametime = metadata["FrameDuration"]
    if focus_tab is not None:
        focus_tab.show_state(metadata)


picam2 = Picamera2()
picam2.post_callback = post_callback
lores_size = picam2.sensor_resolution
while lores_size[0] > 1600:
    lores_size = (lores_size[0] // 2 & ~1, lores_size[1] // 2 & ~1)
# buffer_count=2 (upstream used 1): with a single buffer the preview widget does
# not hold a reference to the frame it is showing, and a repaint after the
# request has been recycled crashed the app ('NoneType' object has no attribute
# 'buffers'). Two buffers let the widget keep its frame alive.
still_kwargs = {"lores": {"size": lores_size}, "display": "lores", "encode": "lores", "buffer_count": 2}


def still_config(main_size, raw=None):
    """Still configuration with the preview (lores) stream clamped to the main size.

    Picamera2 rejects a lores stream larger than main, which happened upstream
    whenever a small custom resolution was chosen.
    """
    lores = (min(lores_size[0], main_size[0]) & ~1, min(lores_size[1], main_size[1]) & ~1)
    kwargs = dict(still_kwargs, lores={"size": lores})
    if raw is not None:
        kwargs["raw"] = raw
    return picam2.create_still_configuration(main={"size": tuple(main_size)}, **kwargs)


picam2.still_configuration = picam2.create_still_configuration(**still_kwargs)
picam2.configure("still")
_ = picam2.sensor_modes
has_af = "AfMode" in picam2.camera_controls

app = QApplication([])
app.setApplicationName("uConsole Camera")


def drop_preview_frame():
    """Forget the frame the preview is showing before the camera is stopped/reconfigured."""
    lock = getattr(qpicamera2, "lock", None)
    if lock is None:
        return
    with lock:
        req = qpicamera2.current_request
        if req is not None and getattr(qpicamera2, "own_current", False) and req.request is not None:
            req.release()
        qpicamera2.current_request = None


def switch_config(new_config):
    print("Switching to", new_config)
    drop_preview_frame()
    picam2.stop()
    picam2.configure(new_config)
    update_controls()
    picam2.start()
    update_controls()
    if focus_tab is not None:
        focus_tab.apply()


def update_controls():
    global scaler_crop, crop_frame

    # Carry the zoom level and centre across configurations. Sensor modes have
    # different ScalerCrop frames (the 1536x864 mode is a centre crop at
    # (768, 432, 3072, 1728) of the 4608x2592 sensor), and upstream kept the old
    # crop *size* when switching, which produced a crop larger than the frame
    # with a negative origin - harmless to libcamera, which clamps it, but it
    # made the pan map and anything else using scaler_crop point at the wrong
    # place.
    _, full_img, _ = picam2.camera_controls['ScalerCrop']
    ox, oy, ow, oh = crop_frame or full_img
    zoom = ow / scaler_crop[2] if scaler_crop[2] else 1.0
    centre_x = (scaler_crop[0] + scaler_crop[2] / 2 - ox) / ow
    centre_y = (scaler_crop[1] + scaler_crop[3] / 2 - oy) / oh
    w = int(full_img[2] / zoom)
    h = int(full_img[3] / zoom)
    x = int(full_img[0] + centre_x * full_img[2] - w / 2)
    y = int(full_img[1] + centre_y * full_img[3] - h / 2)
    x = min(max(x, full_img[0]), full_img[0] + full_img[2] - w)
    y = min(max(y, full_img[1]), full_img[1] + full_img[3] - h)
    scaler_crop = (x, y, w, h)
    crop_frame = full_img

    with picam2.controls as controls:
        controls.ScalerCrop = scaler_crop
    aec_tab.aec_update()
    aec_tab.awb_update()
    vid_tab.vid_update()
    pic_tab.pic_update()
    pan_tab.pan_display.update()

    vid_tab.resolution_h.setValue(picam2.video_configuration.main.size[1])
    vid_tab.resolution_w.setValue(picam2.video_configuration.main.size[0])
    pic_tab.resolution_h.setValue(picam2.still_configuration.main.size[1])
    pic_tab.resolution_w.setValue(picam2.still_configuration.main.size[0])


# --- Capture ------------------------------------------------------------------

status_timer = QTimer()
status_timer.setSingleShot(True)


MIME_TYPES = {"jpg": "image/jpeg", "png": "image/png", "bmp": "image/bmp", "gif": "image/gif"}


def copy_to_clipboard(path):
    """Put a saved photo on the clipboard.

    Prefers a clipboard tool that keeps serving the data after this app exits:
    wl-copy on Wayland, xclip on X11. Falls back to Qt's clipboard, which on
    both systems only lasts as long as the app (or until a clipboard manager
    picks it up).
    """
    ext = path.rsplit(".", 1)[-1].lower()
    mime = MIME_TYPES.get(ext)
    if mime is None:
        return "not copied (clipboard supports jpg/png/bmp/gif)"
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        tool = ["wl-copy", "--type", mime]
    elif os.environ.get("DISPLAY") and shutil.which("xclip"):
        tool = ["xclip", "-selection", "clipboard", "-t", mime, "-i"]
    else:
        tool = None
    if tool:
        with open(path, "rb") as f:
            subprocess.Popen(tool, stdin=f, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "copied to clipboard"
    image = QImage(path)
    if image.isNull():
        return "not copied (could not load image)"
    app.clipboard().setImage(image)
    return "copied to clipboard"


def set_status(text, clear_after_ms=None):
    """Show text in the bar; with clear_after_ms it disappears after that long."""
    status_timer.stop()
    status_label.setText(text)
    if clear_after_ms:
        status_timer.start(clear_after_ms)


status_timer.timeout.connect(lambda: status_label.setText(""))


def on_rec_button_clicked():
    # Self-timer: the first press starts a countdown; pressing again cancels it.
    if self_timer.isActive():
        cancel_timer()
        return
    delay = capture_tab.timer_seconds()
    if delay and rec_button.isEnabled() and not recording:
        start_timer(delay)
        return
    fire_shutter()


def fire_shutter():
    if video_mode():
        on_vid_button_clicked()
    else:
        on_pic_button_clicked()


self_timer = QTimer()
self_timer.setInterval(1000)
timer_left = 0


def start_timer(seconds):
    global timer_left
    timer_left = seconds
    mode_group_enabled(False)
    show_timer()
    self_timer.start()


def timer_tick():
    global timer_left
    timer_left -= 1
    if timer_left > 0:
        show_timer()
        return
    self_timer.stop()
    restore_shutter_text()
    fire_shutter()


def show_timer():
    rec_button.setText(f"{timer_left}\u2026")
    set_status(f"Self-timer: {timer_left} s  (press again to cancel)")


def cancel_timer():
    self_timer.stop()
    restore_shutter_text()
    mode_group_enabled(True)
    set_status("Self-timer cancelled")


def restore_shutter_text():
    rec_button.setText("\u25cf Record" if video_mode() else "Shoot")


self_timer.timeout.connect(timer_tick)


def on_vid_button_clicked():
    global recording
    if not recording:
        mode_group_enabled(False)
        encoder = H264Encoder()
        ext = vid_tab.filetype.currentText()
        path = output_path("VID", ext, vid_tab.filename.text())
        if ext in ["mp4", "mkv", "mov", "ts", "avi"]:
            output = FfmpegOutput(path)
        else:
            output = FileOutput(path)
        picam2.start_encoder(encoder, output, vid_tab.quality)
        rec_button.setText("\u25a0 Stop")
        set_status(f"Recording {path}")
        recording = True
    else:
        picam2.stop_encoder()
        rec_button.setText("\u25cf Record")
        set_status(f"Saved {status_label.text().removeprefix('Recording ')}")
        mode_group_enabled(True)
        recording = False


def on_pic_button_clicked():
    # The HDR sequence re-triggers this while the button is disabled; anything
    # else arriving mid-capture (double press, Space held) is ignored.
    hdr_in_progress = pic_tab.hdr.isChecked() and hdr_imgs["exposures"] is not None
    if not rec_button.isEnabled() and not hdr_in_progress:
        return
    if rec_button.isEnabled():
        rec_button.setEnabled(False)
        mode_group_enabled(False)
        set_status("Capturing...")
        if pic_tab.preview_check.isChecked():
            switch_config("still")
    picam2.capture_request(signal_function=qpicamera2.signal_done)


def mode_group_enabled(enabled):
    photo_button.setEnabled(enabled)
    video_button.setEnabled(enabled)


def video_mode():
    return video_button.isChecked()


def on_mode_change():
    global recording
    if self_timer.isActive():
        cancel_timer()
    if recording:
        print("Not switching, recording in progress, so back to video")
        video_button.setChecked(True)
        return
    is_video = video_mode()
    print(f"Switch to {'video' if is_video else 'photo'}")
    vid_tab.reset()
    pic_tab.reset()
    capture_tab.stack.setCurrentIndex(1 if is_video else 0)
    clip_check.setEnabled(not is_video)
    fill_res_combo()
    if is_video:
        rec_button.setText("\u25cf Record")
        switch_config("video")
    else:
        rec_button.setText("Shoot")
        switch_config("preview" if pic_tab.preview_check.isChecked() else "still")
        pic_tab.apply_settings()


def capture_done(job):
    # Here's the request we captured. But we must always release it when we're done with it!
    if not pic_tab.hdr.isChecked():
        request = picam2.wait(job)
        ext = pic_tab.filetype.currentText()
        if ext == "raw":
            path = output_path("IMG", "dng", pic_tab.filename.text())
            request.save_dng(path)
        else:
            path = output_path("IMG", ext, pic_tab.filename.text())
            picam2.options["quality"] = pic_tab.jpeg_quality.value()
            request.save("main", path)
        request.release()
        note = f"Saved {path}"
        if clip_check.isChecked():
            note += f" \u2014 {copy_to_clipboard(path)}"
        set_status(note)
        rec_button.setEnabled(True)
        mode_group_enabled(True)
        if pic_tab.preview_check.isChecked():
            switch_config("preview")
    else:
        # HDR capture (upstream logic, unchanged apart from file naming)
        global hdr_imgs  # noqa
        request = picam2.wait(job)
        new_img = request.make_array("main")
        new_cv_img = cv2.cvtColor(new_img, cv2.COLOR_RGB2BGR)
        metadata = request.get_metadata()
        request.release()
        new_exposure = metadata["ExposureTime"]
        if hdr_imgs["exposures"] is None:
            pic_tab.pic_update()
            e_log = np.log2(new_exposure)
            max_e = np.log2(pic_tab.pic_dict["FrameDurationLimits"][1])
            below = pic_tab.stops_hdr_below.value()
            above = pic_tab.stops_hdr_above.value()
            if e_log + 1 > max_e:
                above = max_e - e_log
                print("Desired exposure too long, reducing", e_log + 1, max_e, above)
            hdr_imgs["exposures"] = {
                "all": list(
                    set(np.logspace(e_log - below, e_log + above, pic_tab.num_hdr.value(), base=2.0, dtype=np.integer))
                )
            }
            if 0 in hdr_imgs["exposures"]["all"]:
                i = hdr_imgs["exposures"]["all"].index(0)
                hdr_imgs["exposures"]["all"][i] = picam2.camera_controls["ExposureTime"][0]
            hdr_imgs["exposures"]["all"].sort()
            hdr_imgs["exposures"]["left"] = hdr_imgs["exposures"]["all"].copy()
            hdr_imgs["exposures"]["number"] = 0
            hdr_imgs["stem"] = output_path("IMG", pic_tab.filetype.currentText(), pic_tab.filename.text()).rsplit(".", 1)[0]
            print("Picked exposures", hdr_imgs)
            aec_tab.aec_check.setChecked(False)
            cv2.imwrite(f"{hdr_imgs['stem']}_base.{pic_tab.filetype.currentText()}", new_cv_img)
            set_status("HDR: capturing brackets...")
        else:
            nearest_exposure = min(hdr_imgs["exposures"]["all"], key=lambda x: abs(x - new_exposure))
            if nearest_exposure == hdr_imgs["exposures"]["left"][0]:
                hdr_imgs[new_exposure] = new_cv_img
                hdr_imgs["exposures"]["number"] += 1
                hdr_imgs["exposures"]["left"].pop(0)
                print("Taken", hdr_imgs["exposures"]["number"], "images")
            else:
                print("Waiting for exposure switch from", new_exposure, "to", hdr_imgs["exposures"]["left"][0])
        if hdr_imgs["exposures"]["number"] == len(hdr_imgs["exposures"]["all"]):
            print("All HDR exposures captured, dispatching thread to process them")
            thread = threading.Thread(target=process_hdr, daemon=True)
            thread.start()
            aec_tab.aec_check.setChecked(True)
            mode_group_enabled(True)
            rec_button.setEnabled(True)
            pic_tab.hdr.setChecked(False)
            pic_tab.hdr.setEnabled(False)
            if pic_tab.preview_check.isChecked():
                switch_config("preview")
            return
        else:
            picam2.controls.ExposureTime = hdr_imgs["exposures"]["left"][0]
            thread = threading.Thread(target=rec_button.clicked.emit, daemon=True)
            thread.start()


def process_hdr():
    global hdr_imgs
    stem = hdr_imgs.pop("stem")
    ext = pic_tab.filetype.currentText()
    del hdr_imgs["exposures"]
    img_list = []
    exposures = []
    for k, v in hdr_imgs.items():
        img_list.append(v)
        exposures.append(int(k))
    exposures = np.array(exposures, dtype=np.float32)
    exposures /= 1e6
    tonemap = cv2.createTonemap(gamma=pic_tab.hdr_gamma.value())
    pic_tab.hdr_label.setText("HDR (Processing)")

    mean_image = np.average(np.array(img_list), axis=0)
    cv2.imwrite(f"{stem}_mean.{ext}", mean_image.astype('uint8'))
    del mean_image

    merge_debevec = cv2.createMergeDebevec()
    hdr_debevec = merge_debevec.process(img_list, times=exposures.copy())
    res_debevec = tonemap.process(hdr_debevec.copy())
    cv2.imwrite(f"{stem}_debevec.{ext}", np.clip(res_debevec * 255, 0, 255).astype('uint8'))
    del merge_debevec, hdr_debevec, res_debevec

    merge_robertson = cv2.createMergeRobertson()
    hdr_robertson = merge_robertson.process(img_list, times=exposures.copy())
    res_robertson = tonemap.process(hdr_robertson.copy())
    cv2.imwrite(f"{stem}_robertson.{ext}", np.clip(res_robertson * 255, 0, 255).astype('uint8'))
    del merge_robertson, hdr_robertson, res_robertson

    merge_mertens = cv2.createMergeMertens()
    res_mertens = merge_mertens.process(img_list)
    cv2.imwrite(f"{stem}_mertens.{ext}", np.clip(res_mertens * 255, 0, 255).astype('uint8'))
    del merge_mertens, res_mertens

    print("Saved All HDR Images")
    hdr_imgs = {"exposures": None}
    pic_tab.hdr.setEnabled(True)
    pic_tab.hdr_label.setText("HDR")
    set_status(f"Saved HDR set {stem}_*.{ext}")


# --- Control widgets (upstream) -------------------------------------------------

class logControlSlider(QWidget):
    def __init__(self):
        super().__init__()
        self.layout = QHBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.layout)

        self.slider = QSlider(Qt.Horizontal)
        self.box = QDoubleSpinBox()

        self.valueChanged = self.box.valueChanged
        self.valueChanged.connect(lambda: self.setValue(self.value()))
        self.slider.valueChanged.connect(self.updateValue)

        self.layout.addWidget(self.box)
        self.layout.addWidget(self.slider)

        self.precision = self.box.singleStep()
        self.slider.setSingleStep(1)
        self.minimum = 0.0
        self.maximum = 2.0

    @property
    def points(self):
        return int(1.0 / self.precision) * 2

    def boxToSlider(self, val=None):
        if val is None:
            val = self.box.value()
        if val == 0:
            return 0
        center = self.points // 2
        scaling = center / np.log2(self.maximum)
        return round(np.log2(val) * scaling) + center

    def sliderToBox(self, val=None):
        if val is None:
            val = self.slider.value()
        if val == 0:
            return 0
        center = self.points // 2
        scaling = center / np.log2(self.maximum)
        return round(2 ** ((val - center) / scaling), int(-np.log10(self.precision)))

    def updateValue(self):
        self.blockAllSignals(True)
        if self.box.value() != self.sliderToBox():
            self.box.setValue(self.sliderToBox())
        self.blockAllSignals(False)
        self.valueChanged.emit(self.value())

    def redrawSlider(self):
        self.slider.setMinimum(0)
        self.slider.setMaximum(self.points)
        self.slider.setValue(self.boxToSlider())

    def setSingleStep(self, val):
        self.box.setSingleStep(val)
        self.precision = val

    def setValue(self, val, emit=False):
        self.blockAllSignals(True)
        self.box.setValue(val)
        self.redrawSlider()
        self.blockAllSignals(False)
        if emit:
            self.valueChanged.emit(self.value())

    def setMinimum(self, val):
        self.box.setMinimum(val)
        self.minimum = val
        self.redrawSlider()

    def setMaximum(self, val):
        self.box.setMaximum(val)
        self.maximum = val
        self.redrawSlider()

    def blockAllSignals(self, y):
        self.box.blockSignals(y)
        self.slider.blockSignals(y)

    def value(self):
        return self.box.value()


class controlSlider(QWidget):
    def __init__(self, box_type=float):
        super().__init__()
        self.layout = QHBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.layout)

        self.slider = QSlider(Qt.Horizontal)
        self.box = QDoubleSpinBox() if box_type is float else QSpinBox()

        self.valueChanged = self.box.valueChanged
        self.valueChanged.connect(lambda: self.setValue(self.value()))
        self.slider.valueChanged.connect(self.updateValue)

        self.layout.addWidget(self.box)
        self.layout.addWidget(self.slider)

        self.precision = self.box.singleStep()
        self.slider.setSingleStep(1)

    def updateValue(self):
        self.blockAllSignals(True)
        if self.box.value() != self.slider.value() * self.precision:
            self.box.setValue(self.slider.value() * self.precision)
        self.blockAllSignals(False)
        self.valueChanged.emit(self.value())

    def setSingleStep(self, val):
        self.box.setSingleStep(val)
        self.precision = val

    def setValue(self, val, emit=False):
        self.blockAllSignals(True)
        if val is None:
            val = 0
        self.box.setValue(val)
        self.slider.setValue(int(val / self.precision))
        self.blockAllSignals(False)
        if emit:
            self.valueChanged.emit(self.value())

    def setMinimum(self, val):
        self.box.setMinimum(val)
        self.slider.setMinimum(int(val / self.precision))

    def setMaximum(self, val):
        self.box.setMaximum(val)
        self.slider.setMaximum(int(val / self.precision))

    def blockAllSignals(self, y):
        self.box.blockSignals(y)
        self.slider.blockSignals(y)

    def value(self):
        return self.box.value()


def compact_form():
    layout = QFormLayout()
    layout.setContentsMargins(6, 6, 6, 6)
    layout.setHorizontalSpacing(8)
    layout.setVerticalSpacing(4)
    layout.setRowWrapPolicy(QFormLayout.WrapLongRows)
    layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
    return layout


# --- Pan / zoom (upstream) -------------------------------------------------------

class panTab(QWidget):
    def __init__(self):
        super().__init__()
        self.layout = compact_form()
        self.setLayout(self.layout)

        self.label = QLabel(
            "Scroll on the preview or the map to zoom; drag to pan.\n"
            "Keys: + / - zoom, 0 reset.",
            alignment=Qt.AlignCenter,
        )
        self.label.setWordWrap(True)
        self.zoom_text = QLabel("Zoom: 1.0x", alignment=Qt.AlignCenter)
        self.pan_display = panZoomDisplay()
        self.pan_display.updated.connect(self.on_updated)

        self.layout.addRow(self.label)
        self.layout.addRow(self.zoom_text)
        self.layout.addRow(self.pan_display)
        self.layout.setAlignment(self.pan_display, Qt.AlignCenter)

    def on_updated(self):
        level = self.pan_display.zoom_level
        self.zoom_text.setText(f"Zoom: {level:.1f}x")
        zoom_slider.blockSignals(True)
        zoom_slider.setValue(round(level * 10))
        zoom_slider.blockSignals(False)
        zoom_label.setText(f"{level:.1f}x")


class panZoomDisplay(QWidget):
    updated = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(201, 151)
        _, full_img, _ = picam2.camera_controls['ScalerCrop']
        self.scale = 200 / full_img[2]
        self.zoom_level_ = 1.0
        self.max_zoom = 7.0
        self.zoom_step = 0.1

    @property
    def zoom_level(self):
        return self.zoom_level_

    @zoom_level.setter
    def zoom_level(self, val):
        if val != self.zoom_level:
            self.zoom_level_ = val
            self.setZoom()

    def setZoomLevel(self, val):
        self.zoom_level = val

    def paintEvent(self, event):
        painter = QPainter()
        painter.begin(self)
        _, full_img, _ = picam2.camera_controls['ScalerCrop']
        self.scale = 200 / full_img[2]
        scaled_full_img = [int(i * self.scale) for i in full_img]
        origin = scaled_full_img[:2]
        scaled_full_img[:2] = [0, 0]
        painter.drawRect(*scaled_full_img)
        scaled_scaler_crop = [int(i * self.scale) for i in scaler_crop]
        scaled_scaler_crop[0] -= origin[0]
        scaled_scaler_crop[1] -= origin[1]
        painter.drawRect(*scaled_scaler_crop)
        painter.end()
        self.updated.emit()

    def draw_centered(self, pos):
        global scaler_crop
        center = [int(i / self.scale) for i in pos]
        _, full_img, _ = picam2.camera_controls['ScalerCrop']
        w = scaler_crop[2]
        h = scaler_crop[3]
        x = center[0] - w // 2 + full_img[0]
        y = center[1] - h // 2 + full_img[1]
        self.set_crop([x, y, w, h])

    def pan_by(self, dx, dy):
        """Shift the crop by a fraction (dx, dy) of its own size."""
        x, y, w, h = scaler_crop
        self.set_crop([int(x + dx * w), int(y + dy * h), w, h])

    def set_crop(self, new_scaler_crop):
        global scaler_crop
        _, full_img, _ = picam2.camera_controls['ScalerCrop']
        new_scaler_crop[1] = max(new_scaler_crop[1], full_img[1])
        new_scaler_crop[1] = min(new_scaler_crop[1], full_img[1] + full_img[3] - new_scaler_crop[3])
        new_scaler_crop[0] = max(new_scaler_crop[0], full_img[0])
        new_scaler_crop[0] = min(new_scaler_crop[0], full_img[0] + full_img[2] - new_scaler_crop[2])
        scaler_crop = tuple(new_scaler_crop)
        picam2.controls.ScalerCrop = scaler_crop
        self.update()
        # paintEvent also emits this, but only when the pan map is visible; the
        # bottom-bar slider and label must follow wheel/key zoom regardless.
        self.updated.emit()

    def mouseMoveEvent(self, event):
        pos = event.pos()
        self.draw_centered((pos.x(), pos.y()))

    def setZoom(self):
        if self.zoom_level < 1:
            self.zoom_level = 1.0
        if self.zoom_level > self.max_zoom:
            self.zoom_level = self.max_zoom
        factor = 1.0 / self.zoom_level
        _, full_img, _ = picam2.camera_controls['ScalerCrop']
        current_center = (scaler_crop[0] + scaler_crop[2] // 2, scaler_crop[1] + scaler_crop[3] // 2)
        w = int(factor * full_img[2])
        h = int(factor * full_img[3])
        self.set_crop([current_center[0] - w // 2, current_center[1] - h // 2, w, h])

    def wheelEvent(self, event):
        zoom_dir = np.sign(event.angleDelta().y())
        self.zoom_level += zoom_dir * self.zoom_step
        self.setZoom()

    def zoom_about(self, level, anchor):
        """Zoom to `level` keeping the sensor point `anchor` = (sx, sy, (nx, ny)) under the cursor."""
        level = min(max(level, 1.0), self.max_zoom)
        if level == self.zoom_level_:
            return
        self.zoom_level_ = level
        _, full_img, _ = picam2.camera_controls['ScalerCrop']
        w = int(full_img[2] / level)
        h = int(full_img[3] / level)
        sx, sy, (nx, ny) = anchor
        self.set_crop([int(sx - nx * w), int(sy - ny * h), w, h])


class PreviewMouse(QWidget):
    """Event filter on the preview: wheel zooms, drag pans, a tap focuses there."""

    DRAG_THRESHOLD = 6  # px before a press counts as a drag rather than a tap

    def __init__(self):
        super().__init__()
        self.last = None
        self.press = None
        self.dragged = False

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QEvent.Wheel:
            # Zoom about the point under the cursor; fall back to centre zoom off the image
            display = pan_tab.pan_display
            anchor = preview_to_sensor(obj, event.position().toPoint() if hasattr(event, "position") else event.pos())
            step = np.sign(event.angleDelta().y()) * display.zoom_step * 5
            if anchor is None:
                display.zoom_level += step
                display.setZoom()
            else:
                display.zoom_about(display.zoom_level + step, anchor)
            return True
        if t == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self.last = self.press = event.pos()
            self.dragged = False
            return True
        if t == QEvent.MouseMove and self.last is not None and event.buttons() & Qt.LeftButton:
            if not self.dragged and (event.pos() - self.press).manhattanLength() < self.DRAG_THRESHOLD:
                return True
            self.dragged = True
            d = event.pos() - self.last
            self.last = event.pos()
            # Dragging the image moves the crop the opposite way, scaled to the widget size
            pan_tab.pan_display.pan_by(-d.x() / max(obj.width(), 1), -d.y() / max(obj.height(), 1))
            return True
        if t == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            if self.press is not None and not self.dragged:
                focus_at(obj, event.pos())
            self.last = self.press = None
            return True
        return False


def preview_to_sensor(widget, pos):
    """Map a point on the preview widget to sensor coordinates inside the current crop, or None."""
    dpr = widget.devicePixelRatioF()
    x_off, y_off, w, h = widget.recalculate_viewport()
    nx = (pos.x() * dpr - x_off) / max(w, 1)
    ny = (pos.y() * dpr - y_off) / max(h, 1)
    if not (0 <= nx <= 1 and 0 <= ny <= 1):
        return None  # tapped the letterbox bars
    cx, cy, cw, ch = metadata_crop or scaler_crop
    return int(cx + nx * cw), int(cy + ny * ch), (nx, ny)


def focus_at(widget, pos):
    """Tap-to-focus: point the AF window at the tapped spot and (re)focus."""
    if focus_tab is None:
        return
    mapped = preview_to_sensor(widget, pos)
    if mapped is None:
        return
    sx, sy, (nx, ny) = mapped
    cx, cy, cw, ch = metadata_crop or scaler_crop
    ww, wh = max(cw // 5, 16), max(ch // 5, 16)
    wx = min(max(sx - ww // 2, cx), cx + cw - ww)
    wy = min(max(sy - wh // 2, cy), cy + ch - wh)
    focus_tab.set_window((wx, wy, ww, wh))
    show_focus_box(nx, ny, ww / cw, wh / ch)
    set_status("Focusing on the tapped region\u2026")


focus_box_timer = QTimer()
focus_box_timer.setSingleShot(True)
focus_box_timer.setInterval(1500)


def show_focus_box(nx, ny, fw, fh):
    """Draw a box over the preview where the AF window is, for a moment."""
    overlay = np.zeros((360, 640, 4), dtype=np.uint8)
    x0 = int(min(max(nx - fw / 2, 0), 1 - fw) * 640)
    y0 = int(min(max(ny - fh / 2, 0), 1 - fh) * 360)
    x1, y1 = x0 + max(int(fw * 640), 4), y0 + max(int(fh * 360), 4)
    colour = (80, 255, 80, 230)
    overlay[y0:y0 + 2, x0:x1] = colour
    overlay[y1 - 2:y1, x0:x1] = colour
    overlay[y0:y1, x0:x0 + 2] = colour
    overlay[y0:y1, x1 - 2:x1] = colour
    qpicamera2.set_overlay(overlay)
    focus_box_timer.start()


focus_box_timer.timeout.connect(lambda: qpicamera2.set_overlay(None))


# --- Settings tabs (upstream, compacted) -------------------------------------------

STANDARD_SIZES = [(3840, 2160), (1920, 1080), (1280, 720)]


def resolution_presets(max_height=None):
    """Sensor-mode sizes plus common sizes that fit the sensor, largest first."""
    sizes = {tuple(m["size"]) for m in picam2.sensor_modes}
    sw, sh = picam2.sensor_resolution
    sizes.update(size for size in STANDARD_SIZES if size[0] <= sw and size[1] <= sh)
    if max_height:
        sizes = {size for size in sizes if size[1] <= max_height}
    return sorted(sizes, key=lambda size: size[0] * size[1], reverse=True)


def megapixels(size):
    return f"{size[0] * size[1] / 1e6:.1f} MP"


def sensor_mode_for(size):
    """The sensor mode Picamera2 will pick for an output size: the smallest that covers it."""
    fits = [m for m in picam2.sensor_modes if m["size"][0] >= size[0] and m["size"][1] >= size[1]]
    pool = fits or picam2.sensor_modes
    return min(pool, key=lambda m: m["size"][0] * m["size"][1]) if fits else max(pool, key=lambda m: m["size"][0] * m["size"][1])


class PresetPicker:
    """Keeps a preset combo and a pair of width/height spinboxes in step."""

    def __init__(self, combo, w_box, h_box, presets, label):
        self.combo, self.w_box, self.h_box, self.presets = combo, w_box, h_box, presets
        self.listeners = []  # called with the preset index after any change
        combo.addItems([label(size) for size in presets] + ["Custom"])
        combo.currentIndexChanged.connect(self.on_combo)
        w_box.valueChanged.connect(self.sync)
        h_box.valueChanged.connect(self.sync)
        self.sync()

    def on_combo(self, i):
        if i < len(self.presets):
            w, h = self.presets[i]
            self.w_box.setValue(w)
            self.h_box.setValue(h)

    def sync(self):
        size = (self.w_box.value(), self.h_box.value())
        index = self.presets.index(size) if size in self.presets else len(self.presets)
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(index)
        self.combo.blockSignals(False)
        for fn in self.listeners:
            fn(index)

class AECTab(QWidget):
    def __init__(self, is_mono: bool):
        super().__init__()
        self.layout = compact_form()
        self.setLayout(self.layout)

        self.aec_check = QCheckBox("Auto exposure")
        self.aec_check.setChecked(True)
        self.aec_check.stateChanged.connect(self.aec_update)
        self.aec_meter = QComboBox()
        self.aec_meter.addItems(["Centre Weighted", "Spot", "Matrix"])
        self.aec_meter.setCurrentIndex(pref("exposure/metering", 1))  # Spot by default
        self.aec_meter.currentIndexChanged.connect(lambda i: prefs.setValue("exposure/metering", i))
        self.aec_meter.currentIndexChanged.connect(self.aec_update)
        self.aec_constraint = QComboBox()
        self.aec_constraint.addItems(["Default", "Highlight"])
        self.aec_constraint.currentIndexChanged.connect(self.aec_update)
        self.aec_exposure = QComboBox()
        self.aec_exposure.addItems(["Normal", "Short", "Long"])
        self.aec_exposure.currentIndexChanged.connect(self.aec_update)
        self.exposure_val = controlSlider()
        self.exposure_val.valueChanged.connect(self.aec_update)
        self.exposure_val.setSingleStep(0.1)
        self.exposure_time = QSpinBox()
        self.exposure_time.setSingleStep(1000)
        self.analogue_gain = QDoubleSpinBox()
        self.analogue_label = QLabel()
        self.analogue_label.setWordWrap(True)
        self.aec_apply = QPushButton("Apply manual values")
        self.aec_apply.setEnabled(False)
        self.aec_apply.clicked.connect(self.aec_manual_update)
        self.exposure_time.valueChanged.connect(lambda: self.aec_apply.setEnabled(self.exposure_time.isEnabled()))
        self.analogue_gain.valueChanged.connect(lambda: self.aec_apply.setEnabled(self.exposure_time.isEnabled()))
        self.is_mono = is_mono

        if not self.is_mono:
            self.awb_check = QCheckBox("Auto white balance")
            self.awb_check.setChecked(True)
            self.awb_check.stateChanged.connect(self.awb_update)
            self.awb_mode = QComboBox()
            self.awb_mode.addItems(["Auto", "Incandescent", "Tungsten", "Fluorescent", "Indoor", "Daylight", "Cloudy"])
            self.awb_mode.currentIndexChanged.connect(self.awb_update)
            self.colour_gain_r = QDoubleSpinBox()
            self.colour_gain_r.setSingleStep(0.1)
            self.colour_gain_r.valueChanged.connect(self.awb_update)
            self.colour_gain_b = QDoubleSpinBox()
            self.colour_gain_b.setSingleStep(0.1)
            self.colour_gain_b.valueChanged.connect(self.awb_update)

        self.reset()
        self.aec_update()
        self.awb_update()
        self.aec_apply.setEnabled(False)

        self.layout.addRow(self.aec_check)
        self.layout.addRow("Metering", self.aec_meter)
        self.layout.addRow("Constraint", self.aec_constraint)
        self.layout.addRow("Exposure mode", self.aec_exposure)
        self.layout.addRow("EV", self.exposure_val)
        self.layout.addRow("Shutter μs", self.exposure_time)
        self.layout.addRow("Gain", self.analogue_gain)
        self.layout.addRow(self.analogue_label)
        self.layout.addRow(self.aec_apply)

        if not self.is_mono:
            self.layout.addRow(self.awb_check)
            self.layout.addRow("AWB mode", self.awb_mode)
            self.layout.addRow("Red gain", self.colour_gain_r)
            self.layout.addRow("Blue gain", self.colour_gain_b)

    def reset(self):
        self.aec_check.setChecked(True)
        self.exposure_time.setValue(10000)
        self.analogue_gain.setValue(1.0)
        if not self.is_mono:
            self.awb_check.setChecked(True)
            self.colour_gain_r.setValue(1.0)
            self.colour_gain_b.setValue(1.0)

    @property
    def aec_dict(self):
        ret = {
            "AeEnable": self.aec_check.isChecked(),
            "AeMeteringMode": self.aec_meter.currentIndex(),
            "AeConstraintMode": self.aec_constraint.currentIndex(),
            "AeExposureMode": self.aec_exposure.currentIndex(),
            "ExposureValue": self.exposure_val.value(),
            "ExposureTime": self.exposure_time.value(),
            "AnalogueGain": self.analogue_gain.value(),
        }
        if self.aec_check.isChecked():
            del ret["ExposureTime"]
            del ret["AnalogueGain"]
        return ret

    def aec_update(self):
        self.exposure_val.setMinimum(picam2.camera_controls["ExposureValue"][0])
        self.exposure_val.setMaximum(picam2.camera_controls["ExposureValue"][1])
        self.exposure_time.setMinimum(picam2.camera_controls["ExposureTime"][0])
        self.exposure_time.setMaximum(picam2.camera_controls["ExposureTime"][1])
        self.analogue_gain.setMinimum(picam2.camera_controls["AnalogueGain"][0])
        self.analogue_label.setText(f"Analogue up to {picam2.camera_controls['AnalogueGain'][1]:.2f}, then digital")

        self.aec_meter.setEnabled(self.aec_check.isChecked())
        self.aec_constraint.setEnabled(self.aec_check.isChecked())
        self.aec_exposure.setEnabled(self.aec_check.isChecked())
        self.exposure_val.setEnabled(self.aec_check.isChecked())
        self.exposure_time.setEnabled(not self.aec_check.isChecked())
        self.analogue_gain.setEnabled(not self.aec_check.isChecked())
        if self.aec_check.isChecked():
            self.aec_apply.setEnabled(False)
        picam2.set_controls(self.aec_dict)

    def aec_manual_update(self):
        if not self.aec_check.isChecked():
            self.aec_update()
        self.aec_apply.setEnabled(False)

    @property
    def awb_dict(self):
        ret = {
            "AwbEnable": self.awb_check.isChecked(),
            "AwbMode": self.awb_mode.currentIndex(),
            "ColourGains": [self.colour_gain_r.value(), self.colour_gain_b.value()],
        }
        if self.awb_check.isChecked():
            del ret["ColourGains"]
        return ret

    def awb_update(self):
        if self.is_mono:
            return
        self.colour_gain_r.setMinimum(picam2.camera_controls["ColourGains"][0] + 0.01)
        self.colour_gain_r.setMaximum(picam2.camera_controls["ColourGains"][1])
        self.colour_gain_b.setMinimum(picam2.camera_controls["ColourGains"][0] + 0.01)
        self.colour_gain_b.setMaximum(picam2.camera_controls["ColourGains"][1])
        self.colour_gain_r.setEnabled(not self.awb_check.isChecked())
        self.colour_gain_b.setEnabled(not self.awb_check.isChecked())
        picam2.set_controls(self.awb_dict)


class FocusTab(QWidget):
    """Autofocus controls (new; upstream ignored the Af* controls)."""

    MODES = ["Manual", "Auto (trigger)", "Continuous"]
    STATES = {0: "idle", 1: "scanning", 2: "focused", 3: "failed"}

    def __init__(self):
        super().__init__()
        self.layout = compact_form()
        self.setLayout(self.layout)

        self.mode = QComboBox()
        self.mode.addItems(self.MODES)
        self.mode.setCurrentIndex(pref("focus/mode", 2))
        self.mode.currentIndexChanged.connect(self.on_mode)
        self.range = QComboBox()
        self.range.addItems(["Normal", "Macro", "Full"])
        self.range.currentIndexChanged.connect(self.apply)
        self.speed = QComboBox()
        self.speed.addItems(["Normal", "Fast"])
        self.speed.currentIndexChanged.connect(self.apply)
        lo, hi, default = picam2.camera_controls["LensPosition"]
        self.lens = controlSlider()
        self.lens.setSingleStep(0.1)
        self.lens.setMinimum(lo)
        self.lens.setMaximum(hi)
        self.lens.setValue(default)
        self.lens.valueChanged.connect(self.apply)
        self.lens_label = QLabel("Lens position (dioptres; 0 = infinity)")
        self.lens_label.setWordWrap(True)
        self.trigger = QPushButton("Trigger autofocus (F)")
        self.trigger.clicked.connect(self.do_trigger)
        self.window = None  # AF window in sensor coordinates, set by tapping the preview
        self.window_label = QLabel("Metering: whole frame")
        self.window_label.setWordWrap(True)
        self.whole_frame = QPushButton("Whole frame")
        self.whole_frame.setToolTip("Stop focusing on the tapped region")
        self.whole_frame.clicked.connect(lambda: self.set_window(None))
        self.state = QLabel("AF state: -")
        self._last_state = None

        self.layout.addRow("Mode", self.mode)
        self.layout.addRow("Range", self.range)
        self.layout.addRow("Speed", self.speed)
        self.layout.addRow(self.lens_label)
        self.layout.addRow(self.lens)
        self.layout.addRow(self.trigger)
        self.layout.addRow(self.window_label)
        self.layout.addRow(self.whole_frame)
        self.layout.addRow(QLabel("Tap the preview to focus on a spot."))
        self.layout.addRow(self.state)
        self.whole_frame.setEnabled(False)
        self.on_mode()

    def on_mode(self):
        prefs.setValue("focus/mode", self.mode.currentIndex())
        manual = self.mode.currentIndex() == 0
        self.lens.setEnabled(manual)
        self.trigger.setEnabled(self.mode.currentIndex() == 1)
        self.apply()

    def apply(self):
        controls = {
            "AfMode": self.mode.currentIndex(),
            "AfRange": self.range.currentIndex(),
            "AfSpeed": self.speed.currentIndex(),
            "AfMetering": 1 if self.window else 0,  # Windows / Auto
        }
        if self.window:
            controls["AfWindows"] = [self.window]
        if self.mode.currentIndex() == 0:
            controls["LensPosition"] = self.lens.value()
        picam2.set_controls(controls)

    def set_window(self, window):
        """Focus on a region (sensor coordinates, inside the current ScalerCrop) or the whole frame."""
        self.window = window
        self.whole_frame.setEnabled(window is not None)
        if window:
            self.window_label.setText(f"Metering: region {window[2]}x{window[3]} at ({window[0]}, {window[1]})")
        else:
            self.window_label.setText("Metering: whole frame")
            set_status("Focusing on the whole frame\u2026")
        self.apply()
        if window:
            # Continuous AF re-aims on its own; the other modes need a kick.
            if self.mode.currentIndex() != 2:
                self.do_trigger()
        elif self.mode.currentIndex() == 1:
            self.do_trigger()

    def do_trigger(self):
        if self.mode.currentIndex() == 2:
            return  # continuous AF is already running
        if self.mode.currentIndex() == 0:
            self.mode.setCurrentIndex(1)
        picam2.set_controls({"AfMode": 1, "AfTrigger": 0})

    def show_state(self, metadata):
        s = metadata.get("AfState")
        if s != self._last_state:
            self._last_state = s
            pos = metadata.get("LensPosition")
            text = f"AF state: {self.STATES.get(s, s)}"
            if pos is not None:
                text += f"   lens {pos:.2f}"
            self.state.setText(text)
            # Resolve a "Focusing..." note in the bar once the AF run ends
            if status_label.text().startswith("Focusing") and s in (2, 3):
                set_status("Focused" if s == 2 else "Focus failed", 2500)


class IMGTab(QWidget):
    def __init__(self, is_mono: bool):
        super().__init__()
        self.layout = compact_form()
        self.setLayout(self.layout)

        self.saturation = logControlSlider()
        self.saturation.valueChanged.connect(self.img_update)
        self.saturation.setSingleStep(0.1)
        self.contrast = logControlSlider()
        self.contrast.valueChanged.connect(self.img_update)
        self.contrast.setSingleStep(0.1)
        self.sharpness = logControlSlider()
        self.sharpness.valueChanged.connect(self.img_update)
        self.sharpness.setSingleStep(0.1)
        self.brightness = controlSlider()
        self.brightness.setSingleStep(0.1)
        self.brightness.valueChanged.connect(self.img_update)
        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(self.reset)
        self.is_mono = is_mono

        self.reset()
        self.img_update()

        if not self.is_mono:
            self.layout.addRow("Saturation", self.saturation)
        self.layout.addRow("Contrast", self.contrast)
        self.layout.addRow("Sharpness", self.sharpness)
        self.layout.addRow("Brightness", self.brightness)
        self.layout.addRow(self.reset_button)

    @property
    def img_dict(self):
        values = {
            "Contrast": self.contrast.value(),
            "Sharpness": self.sharpness.value(),
            "Brightness": self.brightness.value(),
        }
        if not self.is_mono:
            values["Saturation"] = self.saturation.value()
        return values

    def reset(self):
        if not self.is_mono:
            self.saturation.setValue(picam2.camera_controls["Saturation"][2], emit=True)
        self.contrast.setValue(picam2.camera_controls["Contrast"][2], emit=True)
        self.sharpness.setValue(picam2.camera_controls["Sharpness"][2], emit=True)
        self.brightness.setValue(picam2.camera_controls["Brightness"][2], emit=True)

    def img_update(self):
        if not self.is_mono:
            self.saturation.setMinimum(picam2.camera_controls["Saturation"][0])
        self.saturation.setMaximum(6.0)
        self.contrast.setMinimum(picam2.camera_controls["Contrast"][0])
        self.contrast.setMaximum(6.0)
        self.sharpness.setMinimum(picam2.camera_controls["Sharpness"][0])
        self.sharpness.setMaximum(picam2.camera_controls["Sharpness"][1])
        self.brightness.setMinimum(picam2.camera_controls["Brightness"][0])
        self.brightness.setMaximum(picam2.camera_controls["Brightness"][1])
        picam2.set_controls(self.img_dict)


class otherTab(QWidget):
    # Sliders for every camera control nothing else covers
    def __init__(self):
        super().__init__()
        self.layout = compact_form()
        self.setLayout(self.layout)

        other_controls = [
            c for c in picam2.camera_controls.keys() if c not in implemented_controls and c not in ignore_controls
        ]
        self.fields = {}
        for control in other_controls:
            widget = controlSlider(box_type=type(picam2.camera_controls[control][0]))
            widget.setMinimum(picam2.camera_controls[control][0])
            widget.setMaximum(picam2.camera_controls[control][1])
            widget.setValue(picam2.camera_controls[control][2])
            widget.valueChanged.connect(self.other_update)
            self.fields[control] = widget
        for k, v in self.fields.items():
            self.layout.addRow(k, v)
        print("Other controls", other_controls)

    @property
    def other_dict(self):
        return {k: v.value() for k, v in self.fields.items()}

    def other_update(self):
        picam2.set_controls(self.other_dict)


class vidTab(QWidget):
    def __init__(self):
        super().__init__()
        self.layout = compact_form()
        self.setLayout(self.layout)
        self.filename = QLineEdit()
        self.filename.setPlaceholderText("VID_<timestamp>")
        self.filetype = QComboBox()
        self.filetype.addItems(["mp4", "mkv", "ts", "mov", "avi", "h264"])
        self.filetype.setCurrentText(pref("video/format", "mp4"))
        self.filetype.currentTextChanged.connect(lambda t: prefs.setValue("video/format", t))
        self.quality_box = QComboBox()
        self.quality_box.addItems(["Very Low", "Low", "Medium", "High", "Very High"])
        self.quality_box.setCurrentIndex(pref("video/quality", 2))
        self.quality_box.currentIndexChanged.connect(lambda i: prefs.setValue("video/quality", i))
        self.framerate = QSpinBox()
        self.framerate.setMinimum(1)
        self.framerate.setMaximum(500)
        self.framerate.setValue(pref("video/framerate", 30))
        self.framerate.valueChanged.connect(self.vid_update)
        self.actual_framerate = QLabel()
        self.preset = QComboBox()
        self.resolution_w = QSpinBox()
        self.resolution_w.setMaximum(picam2.sensor_resolution[0])
        self.resolution_h = QSpinBox()
        # Upstream capped video height at 1080 for the Pi 4 hardware encoder; the
        # Pi 5 encodes in software, so anything the sensor can do is allowed.
        self.resolution_h.setMaximum(picam2.sensor_resolution[1])
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.raw_format = QComboBox()
        self.raw_format.addItem("Default")
        self.raw_format.addItems([f'{x["format"].format} {x["size"]}, {x["fps"]:.0f}fps' for x in picam2.sensor_modes])
        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self.apply_settings)

        resolution = QWidget()
        res_layout = QHBoxLayout()
        res_layout.setContentsMargins(0, 0, 0, 0)
        res_layout.addWidget(self.resolution_w)
        res_layout.addWidget(QLabel("x"), alignment=Qt.AlignHCenter)
        res_layout.addWidget(self.resolution_h)
        resolution.setLayout(res_layout)

        self.layout.addRow("Name", self.filename)
        self.layout.addRow("Format", self.filetype)
        self.layout.addRow("Quality", self.quality_box)
        self.layout.addRow("Frame rate", self.framerate)
        self.layout.addRow(self.actual_framerate)
        self.layout.addRow("Preset", self.preset)
        self.layout.addRow("Resolution", resolution)
        self.layout.addRow(self.note)
        self.layout.addRow("Sensor mode", self.raw_format)
        self.layout.addRow(self.apply_button)

        self.frametime_ = None
        self.resolution_w.setValue(pref("video/width", 1920))
        self.resolution_h.setValue(pref("video/height", 1080))
        self.picker = PresetPicker(self.preset, self.resolution_w, self.resolution_h, resolution_presets(), self.label)
        for widget in (self.resolution_w, self.resolution_h, self.framerate):
            widget.valueChanged.connect(self.update_note)
        self.update_note()
        self.reset()

    NAMES = {(3840, 2160): "4K", (1920, 1080): "1080p", (1280, 720): "720p"}

    @classmethod
    def label(cls, size):
        text = f"{cls.NAMES.get(size, '')} {size[0]}x{size[1]}".strip()
        fps = sensor_mode_for(size)["fps"]
        if fps < 30:
            text += f" (\u2264{fps:.0f} fps)"
        return text

    def update_note(self):
        """Explain the frame-rate ceiling for the chosen size (sensor mode + software encoder)."""
        size = (self.resolution_w.value(), self.resolution_h.value())
        mode = sensor_mode_for(size)
        fps = mode["fps"]
        text = f"Sensor mode {mode['size'][0]}x{mode['size'][1]}: up to {fps:.0f} fps at this size."
        if self.framerate.value() > fps + 0.5:
            text += f" The {self.framerate.value()} fps setting will be limited to about {fps:.0f} fps."
        if size[1] > 1080:
            text += " H.264 is software-encoded on the Pi 5; expect high CPU load above 1080p."
        self.note.setText(text)

    @property
    def quality(self):
        qualities = {
            "Very Low": Quality.VERY_LOW,
            "Low": Quality.LOW,
            "Medium": Quality.MEDIUM,
            "High": Quality.HIGH,
            "Very High": Quality.VERY_HIGH,
        }
        return qualities[self.quality_box.currentText()]

    @property
    def sensor_mode(self):
        configs = [None]
        for mode in picam2.sensor_modes:
            configs.append({"size": mode["size"], "format": mode["format"].format})
        return configs[self.raw_format.currentIndex()]

    @property
    def frametime(self):
        return self.frametime_

    @frametime.setter
    def frametime(self, value):
        self.frametime_ = value
        self.actual_framerate.setText(f"Actual: {1e6 / self.frametime:.1f} fps")

    @property
    def vid_dict(self):
        return {"FrameRate": self.framerate.value()}

    def vid_update(self):
        prefs.setValue("video/framerate", self.framerate.value())
        if self.isVisible():
            picam2.set_controls(self.vid_dict)

    def reset(self):
        picam2.video_configuration = picam2.create_video_configuration(
            main={"size": (self.resolution_w.value(), self.resolution_h.value())}, raw=self.sensor_mode
        )

    def apply_settings(self):
        prefs.setValue("video/width", self.resolution_w.value())
        prefs.setValue("video/height", self.resolution_h.value())
        picam2.video_configuration = picam2.create_video_configuration(
            main={"size": (self.resolution_w.value(), self.resolution_h.value())}, raw=self.sensor_mode
        )
        switch_config("video")


class picTab(QWidget):
    def __init__(self):
        super().__init__()
        self.layout = compact_form()
        self.setLayout(self.layout)

        self.filename = QLineEdit()
        self.filename.setPlaceholderText("IMG_<timestamp>")
        self.filetype = QComboBox()
        self.filetype.addItems(["jpg", "png", "bmp", "gif", "raw"])
        self.filetype.setCurrentText(pref("photo/format", "jpg"))
        self.filetype.currentTextChanged.connect(self.on_filetype)
        self.jpeg_quality = QSpinBox()
        self.jpeg_quality.setRange(50, 100)
        self.jpeg_quality.setValue(pref("photo/jpeg_quality", 93))
        self.jpeg_quality.valueChanged.connect(lambda v: prefs.setValue("photo/jpeg_quality", v))
        self.preset = QComboBox()
        self.resolution_w = QSpinBox()
        self.resolution_w.setMaximum(picam2.sensor_resolution[0])
        self.resolution_w.valueChanged.connect(lambda: self.apply_button.setEnabled(True))
        self.resolution_h = QSpinBox()
        self.resolution_h.setMaximum(picam2.sensor_resolution[1])
        self.resolution_h.valueChanged.connect(lambda: self.apply_button.setEnabled(True))
        self.raw_format = QComboBox()
        self.raw_format.addItem("Default")
        self.raw_format.addItems([f'{x["format"].format} {x["size"]} ({megapixels(x["size"])})' for x in picam2.sensor_modes])
        self.raw_format.setCurrentIndex(pref("photo/sensor_mode", 0))
        self.raw_format.currentIndexChanged.connect(self.update_options)
        self.preview_format = QComboBox()
        self.preview_format.currentIndexChanged.connect(lambda: self.apply_button.setEnabled(True))
        self.preview_check = QCheckBox()
        self.preview_check.setChecked(pref("photo/preview_mode", True))
        self.preview_check.stateChanged.connect(self.apply_settings)
        self.preview_warning = QLabel("Preview and capture have different fields of view")
        self.preview_warning.setWordWrap(True)
        self.preview_warning.hide()
        self.hdr_label = QLabel("HDR")
        self.hdr = QCheckBox()
        self.hdr.setChecked(False)
        self.hdr.setEnabled(cv_present)
        if cv_present:
            self.hdr.stateChanged.connect(self.pic_update)
            self.num_hdr = QSpinBox()
            self.num_hdr.setRange(3, 8)
            self.stops_hdr_above = QSpinBox()
            self.stops_hdr_above.setRange(1, 10)
            self.stops_hdr_below = QSpinBox()
            self.stops_hdr_below.setRange(1, 10)
            self.hdr_gamma = QDoubleSpinBox()
            self.hdr_gamma.setSingleStep(0.1)
        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self.apply_settings)
        self.apply_button.setEnabled(False)

        resolution = QWidget()
        res_layout = QHBoxLayout()
        res_layout.setContentsMargins(0, 0, 0, 0)
        res_layout.addWidget(self.resolution_w)
        res_layout.addWidget(QLabel("x"), alignment=Qt.AlignHCenter)
        res_layout.addWidget(self.resolution_h)
        resolution.setLayout(res_layout)

        self.pic_update()
        self.update_options()
        # Remembered resolution wins over the sensor-mode default
        self.resolution_w.setValue(pref("photo/width", picam2.sensor_resolution[0]))
        self.resolution_h.setValue(pref("photo/height", picam2.sensor_resolution[1]))
        self.picker = PresetPicker(
            self.preset, self.resolution_w, self.resolution_h, resolution_presets(),
            lambda size: f"{size[0]}x{size[1]} ({megapixels(size)})",
        )
        self.reset()

        self.layout.addRow("Name", self.filename)
        self.layout.addRow("Format", self.filetype)
        self.layout.addRow("JPEG quality", self.jpeg_quality)
        self.layout.addRow("Preset", self.preset)
        self.layout.addRow("Resolution", resolution)
        self.layout.addRow("Sensor mode", self.raw_format)
        self.layout.addRow("Live preview mode", self.preview_check)
        self.layout.addRow(self.preview_warning)
        self.layout.addRow("Preview mode", self.preview_format)
        if cv_present:
            self.layout.addRow(self.hdr_label, self.hdr)
            self.layout.addRow("HDR frames", self.num_hdr)
            self.layout.addRow("HDR stops above", self.stops_hdr_above)
            self.layout.addRow("HDR stops below", self.stops_hdr_below)
            self.layout.addRow("HDR gamma", self.hdr_gamma)
        else:
            self.layout.addRow(QLabel("HDR unavailable - install python3-opencv"))
        self.layout.addRow(self.apply_button)
        self.on_filetype(self.filetype.currentText())

    def on_filetype(self, text):
        prefs.setValue("photo/format", text)
        # Only JPEG has a quality setting; hide the row (label + field) otherwise
        is_jpg = text == "jpg"
        self.jpeg_quality.setVisible(is_jpg)
        label = self.layout.labelForField(self.jpeg_quality)
        if label is not None:
            label.setVisible(is_jpg)

    @property
    def sensor_mode(self):
        configs = [{}]
        for mode in picam2.sensor_modes:
            configs.append({"size": mode["size"], "format": mode["format"].format})
        return configs[self.raw_format.currentIndex()]

    @property
    def preview_mode(self):
        configs = [self.sensor_mode]
        for mode in self.preview_modes:
            configs.append({"size": mode["size"], "format": mode["format"].format})
        return configs[self.preview_format.currentIndex()]

    @property
    def pic_dict(self):
        return {"FrameDurationLimits": picam2.camera_controls["FrameDurationLimits"][0:2]}

    def pic_update(self):
        if cv_present:
            self.stops_hdr_above.setEnabled(self.hdr.isChecked())
            self.stops_hdr_below.setEnabled(self.hdr.isChecked())
            self.num_hdr.setEnabled(self.hdr.isChecked())
            self.hdr_gamma.setEnabled(self.hdr.isChecked())
        if self.isVisible():
            picam2.set_controls(self.pic_dict)

    def reset(self):
        if cv_present:
            self.hdr_gamma.setValue(2.2)
        picam2.still_configuration = still_config(
            (self.resolution_w.value(), self.resolution_h.value()), raw=self.sensor_mode
        )

    def update_options(self):
        self.apply_button.setEnabled(True)
        try:
            self.resolution_w.setValue(self.sensor_mode["size"][0])
            self.resolution_h.setValue(self.sensor_mode["size"][1])
        except KeyError:
            self.resolution_h.setValue(picam2.still_configuration.main.size[1])
            self.resolution_w.setValue(picam2.still_configuration.main.size[0])

        preview_index = max(self.preview_format.currentIndex(), 0)
        if self.sensor_mode:
            crop_limits = picam2.sensor_modes[self.raw_format.currentIndex() - 1]["crop_limits"]
        else:
            crop_limits = (0, 0, *picam2.sensor_resolution)
        self.preview_format.clear()
        self.preview_format.addItem("Same as capture")
        self.preview_modes = []
        for mode in picam2.sensor_modes:
            if mode["crop_limits"] == crop_limits:
                self.preview_format.addItem(f'{mode["format"].format} {mode["size"]}')
                self.preview_modes.append(mode)
        try:
            self.preview_format.setCurrentIndex(preview_index)
        except IndexError:
            self.preview_format.setCurrentIndex(0)

    def apply_settings(self):
        prefs.setValue("photo/width", self.resolution_w.value())
        prefs.setValue("photo/height", self.resolution_h.value())
        prefs.setValue("photo/sensor_mode", self.raw_format.currentIndex())
        prefs.setValue("photo/preview_mode", self.preview_check.isChecked())

        picam2.still_configuration = still_config(
            (self.resolution_w.value(), self.resolution_h.value()), raw=self.sensor_mode
        )
        preview_w = max(qpicamera2.width(), 640)
        picam2.preview_configuration = picam2.create_preview_configuration(
            main={"size": (preview_w, int(preview_w * (self.resolution_h.value() / self.resolution_w.value())))},
            raw=self.preview_mode,
        )
        self.preview_format.setEnabled(self.preview_check.isChecked())

        if self.preview_check.isChecked():
            switch_config("still")
            _, current_crop, _ = picam2.camera_controls['ScalerCrop']
            switch_config("preview")
            _, preview_crop, _ = picam2.camera_controls['ScalerCrop']
            self.preview_warning.setVisible(current_crop != preview_crop)
        else:
            switch_config("still")
            self.preview_warning.hide()
        self.apply_button.setEnabled(False)


class CaptureTab(QWidget):
    """Save location (new) plus the photo or video settings for the current mode."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setLayout(layout)

        form = compact_form()
        self.photo_dir_edit = QLineEdit(pref("paths/photos", default_pictures_dir()))
        self.photo_dir_edit.editingFinished.connect(lambda: prefs.setValue("paths/photos", self.photo_dir_edit.text()))
        self.video_dir_edit = QLineEdit(pref("paths/videos", ""))
        self.video_dir_edit.setPlaceholderText("same as photos")
        self.video_dir_edit.editingFinished.connect(lambda: prefs.setValue("paths/videos", self.video_dir_edit.text()))
        form.addRow("Photos to", self.dir_row(self.photo_dir_edit, "paths/photos"))
        form.addRow("Videos to", self.dir_row(self.video_dir_edit, "paths/videos"))
        self.timer = QComboBox()
        self.timer_values = [0, 3, 5, 10]
        self.timer.addItems(["Off"] + [f"{v} s" for v in self.timer_values[1:]])
        self.timer.setCurrentIndex(min(pref("capture/timer", 0), len(self.timer_values) - 1))
        self.timer.currentIndexChanged.connect(lambda i: prefs.setValue("capture/timer", i))
        form.addRow("Self-timer", self.timer)
        self.reset_button = QPushButton("Reset all preferences")
        self.reset_button.clicked.connect(self.reset_prefs)
        form.addRow(self.reset_button)
        top = QWidget()
        top.setLayout(form)
        layout.addWidget(top)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        layout.addWidget(line)

        self.stack = QStackedWidget()
        self.stack.addWidget(pic_tab)
        self.stack.addWidget(vid_tab)
        layout.addWidget(self.stack)
        layout.addStretch(1)

    def dir_row(self, edit, key):
        row = QWidget()
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(edit)
        browse = QToolButton()
        browse.setText("...")
        browse.clicked.connect(lambda: self.browse(edit, key))
        h.addWidget(browse)
        row.setLayout(h)
        return row

    def browse(self, edit, key):
        start = edit.text() or self.photo_dir()
        chosen = QFileDialog.getExistingDirectory(window, "Choose folder", start)
        if chosen:
            edit.setText(chosen)
            prefs.setValue(key, chosen)

    def timer_seconds(self):
        return self.timer_values[self.timer.currentIndex()]

    def photo_dir(self):
        return os.path.expanduser(self.photo_dir_edit.text().strip() or default_pictures_dir())

    def video_dir(self):
        text = self.video_dir_edit.text().strip()
        return os.path.expanduser(text) if text else self.photo_dir()

    def reset_prefs(self):
        prefs.clear()
        prefs.sync()
        set_status("Preferences cleared - restart the app for defaults")


# --- Preview widget ----------------------------------------------------------------

def make_preview(bg_colour):
    """QGlPicamera2 with a guard against repainting a frame the camera has recycled."""
    from picamera2.previews import qt as pq

    try:
        from picamera2.previews.qt_compatibility import _QT_BINDING

        base = pq._get_qglpicamera2_wl(_QT_BINDING.PyQt5) if pq._is_wayland() else pq._get_qglpicamera2(_QT_BINDING.PyQt5)
    except Exception as e:  # internal API moved - fall back to the stock widget
        print("Preview guard unavailable:", e)
        return pq.QGlPicamera2(picam2, width=640, height=360, keep_ar=True, bg_colour=bg_colour)

    class GuardedPreview(base):
        def _live_request(self):
            req = self.current_request
            if req is not None and req.request is None:
                # The camera recycled this request behind our back; forget it.
                self.current_request = None
                return None
            return req

        def paintGL(self):
            if not getattr(self, "_gl_ready", True):
                return
            with self.lock:
                self._repaint(self._live_request())

        def resizeGL(self, w, h):
            if getattr(self, "_gl_ready", True):
                with self.lock:
                    self._repaint(self._live_request())

    return GuardedPreview(picam2, width=640, height=360, keep_ar=True, bg_colour=bg_colour)


# --- Window ------------------------------------------------------------------------

implemented_controls = [
    "ColourCorrectionMatrix", "Saturation", "Contrast", "Sharpness", "Brightness", "NoiseReductionMode",
    "AeEnable", "AeMeteringMode", "AeConstraintMode", "AeExposureMode", "AwbEnable", "AwbMode",
    "ExposureValue", "ExposureTime", "AnalogueGain", "ColourGains", "ScalerCrop", "FrameDurationLimits",
    "AfMode", "AfTrigger", "AfSpeed", "AfRange", "LensPosition",
]
ignore_controls = {"AfWindows", "AfPause", "AfMetering", "ScalerCrops"}

window = QWidget()
window.setWindowTitle("uConsole Camera")
bg_colour = window.palette().color(QPalette.Background).getRgb()[:3]

focus_tab = None  # referenced from post_callback before the tabs exist
qpicamera2 = make_preview(bg_colour)
qpicamera2.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
qpicamera2.setMinimumSize(320, 180)
preview_mouse = PreviewMouse()
qpicamera2.installEventFilter(preview_mouse)

# Bottom bar
photo_button = QPushButton("Photo")
video_button = QPushButton("Video")
for b in (photo_button, video_button):
    b.setCheckable(True)
    b.setAutoExclusive(True)
photo_button.setChecked(True)
# The shutter sits apart from the other controls: double width, taller, a
# bigger bold label - all via size/font so the system theme is untouched.
rec_button = QPushButton("Shoot")
rec_button.setMinimumSize(240, 44)
rec_font = rec_button.font()
rec_font.setBold(True)
rec_font.setPointSizeF(rec_font.pointSizeF() + 2)
rec_button.setFont(rec_font)
rec_button.clicked.connect(on_rec_button_clicked)
qpicamera2.done_signal.connect(capture_done)
zoom_slider = QSlider(Qt.Horizontal)
zoom_slider.setRange(10, 70)
zoom_slider.setValue(10)
zoom_slider.setMaximumWidth(130)
zoom_label = QLabel("1.0x")
zoom_label.setMinimumWidth(36)
clip_check = QCheckBox("Clipboard")
clip_check.setToolTip("Also copy each captured photo to the clipboard")
clip_check.setChecked(pref("photo/clipboard", False))
clip_check.toggled.connect(lambda v: prefs.setValue("photo/clipboard", v))
ev_box = QDoubleSpinBox()
ev_box.setPrefix("EV ")
ev_box.setDecimals(1)
ev_box.setSingleStep(0.5)
ev_box.setToolTip("Exposure compensation")
res_combo = QComboBox()
res_combo.setToolTip("Resolution preset for the current mode")
drawer_button = QPushButton("⚙")
drawer_button.setCheckable(True)
drawer_button.setToolTip("Settings (Tab)")
status_label = QLabel("")
status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

bar = QHBoxLayout()
bar.setContentsMargins(6, 4, 6, 4)
bar.setSpacing(6)
bar.addWidget(photo_button)
bar.addWidget(video_button)
bar.addSpacing(12)
bar.addWidget(clip_check)
bar.addWidget(ev_box)
bar.addWidget(res_combo)
bar.addWidget(QLabel("Zoom"))
bar.addWidget(zoom_slider)
bar.addWidget(zoom_label)
bar.addWidget(status_label, 1)
bar.addSpacing(12)
bar.addWidget(rec_button)
bar.addSpacing(12)
bar.addWidget(drawer_button)

# Settings drawer
tabs = QTabWidget()
tabs.setDocumentMode(True)
img_tab = IMGTab(picam2.is_mono)
pan_tab = panTab()
aec_tab = AECTab(picam2.is_mono)
info_tab = QLabel(alignment=Qt.AlignTop)
info_tab.setTextInteractionFlags(Qt.TextSelectableByMouse)
other_tab = otherTab()
pic_tab = picTab()
vid_tab = vidTab()
capture_tab = CaptureTab()
if has_af:
    focus_tab = FocusTab()


def scrolled(widget):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setWidget(widget)
    return area


tabs.addTab(scrolled(capture_tab), "Capture")
tabs.addTab(scrolled(aec_tab), "Exposure")
if focus_tab is not None:
    tabs.addTab(scrolled(focus_tab), "Focus")
tabs.addTab(scrolled(img_tab), "Tuning")
tabs.addTab(scrolled(pan_tab), "Zoom")
tabs.addTab(scrolled(info_tab), "Info")
tabs.addTab(scrolled(other_tab), "More")
tabs.setCurrentIndex(min(pref("ui/tab", 0), tabs.count() - 1))
tabs.currentChanged.connect(lambda i: prefs.setValue("ui/tab", i))
tabs.setFixedWidth(430)
# Seven tabs have to fit across the drawer: tighten the tab bar a little
tab_font = tabs.tabBar().font()
tab_font.setPointSizeF(max(tab_font.pointSizeF() - 2, 8))
tabs.tabBar().setFont(tab_font)
tabs.setElideMode(Qt.ElideNone)

# Final setup
recording = False
# Current digital-zoom crop and the ScalerCrop frame it is expressed in (both from
# the same configuration, so update_controls() can rescale between frames).
# Start at 1.0x: the whole frame. (The control's "default" value is the crop
# for whatever aspect ratio was last configured, e.g. a 4:3 cut, not the full frame.)
_, crop_frame, _ = picam2.camera_controls['ScalerCrop']
scaler_crop = crop_frame
hdr_imgs = {"exposures": None}
pic_tab.apply_settings()

photo_button.toggled.connect(lambda checked: checked and on_mode_change())
video_button.toggled.connect(lambda checked: checked and on_mode_change())
zoom_slider.valueChanged.connect(lambda v: pan_tab.pan_display.setZoomLevel(v / 10))


# Bar <-> drawer mirrors: exposure compensation, resolution preset.
ev_box.setRange(picam2.camera_controls["ExposureValue"][0], picam2.camera_controls["ExposureValue"][1])
ev_box.setValue(aec_tab.exposure_val.value())
ev_box.valueChanged.connect(lambda v: aec_tab.exposure_val.setValue(v, emit=True))


def ev_from_tab():
    ev_box.blockSignals(True)
    ev_box.setValue(aec_tab.exposure_val.value())
    ev_box.blockSignals(False)
    ev_box.setEnabled(aec_tab.aec_check.isChecked())


aec_tab.exposure_val.valueChanged.connect(ev_from_tab)
aec_tab.aec_check.stateChanged.connect(ev_from_tab)
ev_from_tab()


def active_tab():
    return vid_tab if video_mode() else pic_tab


def short_label(size, video):
    if video:
        return vidTab.NAMES.get(size, f"{size[0]}x{size[1]}")
    return megapixels(size)


def fill_res_combo():
    tab = active_tab()
    picker = tab.picker
    res_combo.blockSignals(True)
    res_combo.clear()
    res_combo.addItems([short_label(size, tab is vid_tab) for size in picker.presets] + ["Custom"])
    res_combo.setCurrentIndex(picker.combo.currentIndex())
    res_combo.blockSignals(False)


def res_from_bar(i):
    tab = active_tab()
    if i >= len(tab.picker.presets):
        return  # "Custom" is only ever a reflection of hand-typed values
    tab.preset.setCurrentIndex(i)
    tab.apply_settings()


def res_from_tab(index):
    if res_combo.count():
        res_combo.blockSignals(True)
        res_combo.setCurrentIndex(index)
        res_combo.blockSignals(False)


res_combo.currentIndexChanged.connect(res_from_bar)
pic_tab.picker.listeners.append(lambda i: video_mode() or res_from_tab(i))
vid_tab.picker.listeners.append(lambda i: video_mode() and res_from_tab(i))
fill_res_combo()


def set_drawer(visible):
    tabs.setVisible(visible)
    drawer_button.setChecked(visible)
    prefs.setValue("ui/drawer", visible)


drawer_button.toggled.connect(set_drawer)


def toggle_fullscreen():
    if window.isFullScreen():
        window.showMaximized()
    else:
        window.showFullScreen()
    prefs.setValue("ui/fullscreen", window.isFullScreen())


def zoom_by(step):
    pan_tab.pan_display.zoom_level += step
    pan_tab.pan_display.setZoom()


def zoom_reset():
    pan_tab.pan_display.zoom_level = 1.0
    pan_tab.pan_display.setZoom()


for keys, fn in (
    (("Space",), rec_button.click),
    (("Tab",), lambda: set_drawer(not tabs.isVisible())),
    (("F",), lambda: focus_tab and focus_tab.do_trigger()),
    (("+", "="), lambda: zoom_by(0.5)),
    (("-",), lambda: zoom_by(-0.5)),
    (("0",), zoom_reset),
    (("F11",), toggle_fullscreen),
    (("Escape", "Q"), window.close),
):
    for k in keys:
        QShortcut(QKeySequence(k), window, activated=fn)

content = QHBoxLayout()
content.setContentsMargins(0, 0, 0, 0)
content.setSpacing(0)
content.addWidget(qpicamera2, 1)
content.addWidget(tabs)

root = QVBoxLayout()
root.setContentsMargins(0, 0, 0, 0)
root.setSpacing(0)
root.addLayout(content, 1)
root.addLayout(bar)
window.setLayout(root)
window.resize(1280, 690)
set_drawer(pref("ui/drawer", True))


def on_quit():
    if recording:
        picam2.stop_encoder()
    prefs.sync()


app.aboutToQuit.connect(on_quit)

if __name__ == "__main__":
    if pref("ui/fullscreen", False):
        window.showFullScreen()
    else:
        window.showMaximized()
    sys.exit(app.exec())

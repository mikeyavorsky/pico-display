# main.py - writes "hello" on a Pimoroni Pico Display Pack and re-checks for
# firmware updates periodically (or on demand via the 'A' button). Wrapped so
# that a crash drops into a recovery loop instead of bricking the device.

import time
from machine import Pin
from picographics import PicoGraphics, DISPLAY_PICO_DISPLAY, PEN_P4

OTA_EVERY = 300   # re-check for new code every 5 minutes

button_a = Pin(12, Pin.IN, Pin.PULL_UP)   # 'A' button on the Display Pack (active-low)

# 240x135 IPS LCD on the Display Pack. PEN_P4 is a 16-colour palette - plenty
# for text and easy on memory. The driver defaults to ROTATE_270 (portrait
# 135x240), so we pass rotate=0 for the landscape 240x135 layout; use 180 to
# flip it the other way up. Text is centred and auto-sized to the bounds.
display = PicoGraphics(display=DISPLAY_PICO_DISPLAY, pen_type=PEN_P4, rotate=0)
display.set_backlight(0.8)

WIDTH, HEIGHT = display.get_bounds()
BLACK = display.create_pen(0, 0, 0)
WHITE = display.create_pen(255, 255, 255)

MARGIN = 8     # px to keep clear around the text
SUB_SCALE = 2  # small footer text (8px tall)


def _fit_scale(text, avail_w, avail_h, max_scale=8):
    # Largest integer scale where the text fits within the given area.
    for scale in range(max_scale, 0, -1):
        if (display.measure_text(text, scale=scale) <= avail_w
                and 8 * scale <= avail_h):
            return scale
    return 1


def _centre(text, scale, y):
    x = (WIDTH - display.measure_text(text, scale=scale)) // 2
    display.text(text, x, y, scale=scale)


def show(text, sub=None):
    display.set_pen(BLACK)
    display.clear()
    display.set_pen(WHITE)

    # Reserve a strip at the bottom for the small footer line, if any.
    sub_h = 8 * SUB_SCALE if sub else 0
    main_h = HEIGHT - 2 * MARGIN - sub_h
    scale = _fit_scale(text, WIDTH - 2 * MARGIN, main_h)

    # Centre the main text within the area above the footer.
    _centre(text, scale, MARGIN + (main_h - 8 * scale) // 2)
    if sub:
        _centre(sub, SUB_SCALE, HEIGHT - MARGIN - sub_h)
    display.update()


def loop():
    import ota
    # We reached a clean running state: confirm any pending update so it won't
    # be rolled back on the next boot.
    ota.mark_boot_ok()

    def home():
        show("hello", "v" + (ota._local_version() or "?"))

    home()
    last_ota = time.time()
    prev_a = button_a.value()
    while True:
        a = button_a.value()
        if prev_a == 1 and a == 0:           # 'A' pressed (falling edge)
            show("hello", "checking...")
            ota.check_and_update(fresh=True)  # bypass CDN cache for on-demand checks
            last_ota = time.time()
            home()                           # back to the version footer if no update
        elif time.time() - last_ota > OTA_EVERY:
            ota.check_and_update()           # resets if it updates
            last_ota = time.time()
        prev_a = a
        time.sleep(0.05)


try:
    loop()
except Exception as e:
    # Self-healing recovery: never hard-crash. Keep polling for an OTA fix.
    print("fatal:", e)
    import ota
    try:
        show("recovery")
    except Exception:
        pass
    while True:
        ota.check_and_update()
        time.sleep(60)

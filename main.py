# main.py - writes "hello" on a Pimoroni Pico Display Pack and re-checks for
# firmware updates periodically. Wrapped so that a crash drops into a recovery
# loop instead of bricking the device.

import time
from picographics import PicoGraphics, DISPLAY_PICO_DISPLAY, PEN_P4

OTA_EVERY = 300   # re-check for new code every 5 minutes

# 240x135 IPS LCD on the Display Pack. PEN_P4 is a 16-colour palette - plenty
# for text and easy on memory. The driver defaults to ROTATE_270 (portrait
# 135x240), so we pass rotate=0 for the landscape 240x135 layout; use 180 to
# flip it the other way up. Text is centred and auto-sized to the bounds.
display = PicoGraphics(display=DISPLAY_PICO_DISPLAY, pen_type=PEN_P4, rotate=0)
display.set_backlight(0.8)

WIDTH, HEIGHT = display.get_bounds()
BLACK = display.create_pen(0, 0, 0)
WHITE = display.create_pen(255, 255, 255)

MARGIN = 8   # px to keep clear around the text


def _fit_scale(text, max_scale=8):
    # Largest integer scale where the text fits within the screen margins.
    for scale in range(max_scale, 0, -1):
        if (display.measure_text(text, scale=scale) <= WIDTH - 2 * MARGIN
                and 8 * scale <= HEIGHT - 2 * MARGIN):
            return scale
    return 1


def show(text):
    scale = _fit_scale(text)
    display.set_pen(BLACK)
    display.clear()
    display.set_pen(WHITE)
    # Centre the text on the screen.
    x = (WIDTH - display.measure_text(text, scale=scale)) // 2
    y = (HEIGHT - 8 * scale) // 2
    display.text(text, x, y, scale=scale)
    display.update()


def loop():
    import ota
    # We reached a clean running state: confirm any pending update so it won't
    # be rolled back on the next boot.
    ota.mark_boot_ok()

    show("hello")

    last_ota = time.time()
    while True:
        if time.time() - last_ota > OTA_EVERY:
            ota.check_and_update()   # resets if it updates
            last_ota = time.time()
        time.sleep(1)


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

# main.py - shows the next departures from Quincy Center on a Pimoroni Pico
# Display Pack: the next Red Line train to Alewife (red) and the next commuter
# rail to South Station (purple), refreshed every minute. Below them: the time
# of the last successful fetch, then the firmware version. Also re-checks for
# firmware updates periodically, or on demand via the 'A' button. Wrapped so
# that a crash drops into a recovery loop instead of bricking the device.

import time, gc
from machine import Pin
import urequests
from picographics import PicoGraphics, DISPLAY_PICO_DISPLAY, PEN_P4

OTA_EVERY  = 300   # re-check for new code every 5 minutes
MBTA_EVERY = 60    # refresh departures every minute
TZ_DEFAULT = -4 * 3600   # fallback if the API doesn't report an offset (EDT)

# MBTA v3 predictions for Quincy Center (parent station place-qnctr). page[limit]=1
# + trimmed fields keep each response tiny, which matters on the Pico.
# Brackets are percent-encoded (%5B/%5D) so the URL is strictly valid on-device.
_BASE = ("https://api-v3.mbta.com/predictions?filter%5Bstop%5D=place-qnctr"
         "&sort=departure_time&page%5Blimit%5D=1"
         "&fields%5Bprediction%5D=departure_time,arrival_time&")
RED_URL = _BASE + "filter%5Broute%5D=Red&filter%5Bdirection_id%5D=1"        # -> Alewife
CR_URL  = _BASE + "filter%5Broute_type%5D=2&filter%5Bdirection_id%5D=1"     # -> South Station

# An MBTA API key is optional (2 req/min is well under the keyless limit), but
# honoured if you add MBTA_KEY to secrets.py.
try:
    from secrets import MBTA_KEY
except ImportError:
    MBTA_KEY = ""
HEADERS = {"x-api-key": MBTA_KEY} if MBTA_KEY else {}

button_a = Pin(12, Pin.IN, Pin.PULL_UP)   # 'A' button on the Display Pack (active-low)

# 240x135 IPS LCD on the Display Pack. PEN_P4 is a 16-colour palette - plenty
# for text and easy on memory. The driver defaults to ROTATE_270 (portrait
# 135x240), so we pass rotate=0 for the landscape 240x135 layout; use 180 to
# flip it the other way up.
display = PicoGraphics(display=DISPLAY_PICO_DISPLAY, pen_type=PEN_P4, rotate=0)
display.set_backlight(0.8)

WIDTH, HEIGHT = display.get_bounds()
BLACK  = display.create_pen(0, 0, 0)
WHITE  = display.create_pen(255, 255, 255)
RED    = display.create_pen(0xDA, 0x29, 0x1C)   # Red Line
PURPLE = display.create_pen(0x80, 0x27, 0x6C)   # Commuter Rail

MARGIN = 8     # px to keep clear around the text
SUB_SCALE = 2  # small footer text (8px tall per scale step)


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


def _left(text, scale, y):
    display.text(text, MARGIN, y, scale=scale)


def banner(text):
    # Single centred line - used for startup/recovery messages.
    display.set_pen(BLACK)
    display.clear()
    display.set_pen(WHITE)
    scale = _fit_scale(text, WIDTH - 2 * MARGIN, HEIGHT - 2 * MARGIN)
    _centre(text, scale, (HEIGHT - 8 * scale) // 2)
    display.update()


def draw_board(t1, t2, fetched, version):
    display.set_pen(BLACK)
    display.clear()

    sub_h = 8 * SUB_SCALE
    ver_y = HEIGHT - MARGIN - sub_h          # version line (bottom)
    fetch_y = ver_y - sub_h                   # last-fetched line (above version)

    # Two big departure times share the area above the footer lines.
    line_h = (fetch_y - 2 - MARGIN) // 2
    scale = min(_fit_scale(t1, WIDTH - 2 * MARGIN, line_h),
                _fit_scale(t2, WIDTH - 2 * MARGIN, line_h))

    # Big time centred on each line, with a small same-colour tag pinned left.
    tag_h = 8 * SUB_SCALE
    top1, top2 = MARGIN, MARGIN + line_h
    display.set_pen(RED)
    _centre(t1, scale, top1 + (line_h - 8 * scale) // 2)
    _left("RL", SUB_SCALE, top1 + (line_h - tag_h) // 2)
    display.set_pen(PURPLE)
    _centre(t2, scale, top2 + (line_h - 8 * scale) // 2)
    _left("CR", SUB_SCALE, top2 + (line_h - tag_h) // 2)

    display.set_pen(WHITE)
    _centre(fetched, SUB_SCALE, fetch_y)
    _centre("v" + version, SUB_SCALE, ver_y)
    display.update()


def _tz_offset(t):
    # Pull the numeric UTC offset out of an ISO time like "...T22:39:57-04:00".
    z = t[19:]
    if not z or z[0] not in "+-":
        return TZ_DEFAULT
    return (-1 if z[0] == "-" else 1) * (int(z[1:3]) * 3600 + int(z[4:6]) * 60)


def _next_departure(url):
    # Return (HH:MM, tz_offset_seconds) for the soonest prediction, or (None, None).
    r = urequests.get(url, headers=HEADERS)
    try:
        data = r.json()["data"]
    finally:
        r.close()
        gc.collect()
    if not data:
        return None, None
    a = data[0]["attributes"]
    t = a.get("departure_time") or a.get("arrival_time")
    if not t:
        return None, None
    return t[11:16], _tz_offset(t)


def _sync_clock():
    # NTP sets the RTC to UTC; the local offset comes from the API per-fetch.
    try:
        import ntptime
        ntptime.settime()
        return True
    except Exception as e:
        print("NTP sync failed:", e)
        return False


def _now_hhmm(offset):
    lt = time.localtime(time.time() + offset)
    return "%02d:%02d" % (lt[3], lt[4])


def loop():
    import ota
    # We reached a clean running state: confirm any pending update so it won't
    # be rolled back on the next boot.
    ota.mark_boot_ok()
    version = ota._local_version() or "?"

    banner("loading")
    clock_ok = _sync_clock()
    t1 = t2 = fetched = "--:--"
    offset = TZ_DEFAULT

    last_ota = time.time()
    last_mbta = last_ota - MBTA_EVERY   # fetch departures immediately
    prev_a = button_a.value()
    while True:
        a = button_a.value()
        now = time.time()

        if prev_a == 1 and a == 0:               # 'A' pressed (falling edge)
            draw_board(t1, t2, "checking", version)
            ota.check_and_update(fresh=True)      # resets if it updates
            last_ota = now
            version = ota._local_version() or "?"
            draw_board(t1, t2, fetched, version)
        else:
            if now - last_mbta >= MBTA_EVERY:
                if not clock_ok:
                    clock_ok = _sync_clock()
                try:
                    r1, o1 = _next_departure(RED_URL)
                    r2, o2 = _next_departure(CR_URL)
                    if r1:
                        t1 = r1
                    if r2:
                        t2 = r2
                    offset = o1 or o2 or offset
                    if clock_ok:
                        fetched = _now_hhmm(offset)
                    draw_board(t1, t2, fetched, version)
                except Exception as e:
                    print("MBTA fetch failed:", e)
                last_mbta = now

            if now - last_ota >= OTA_EVERY:
                ota.check_and_update()           # resets if it updates
                last_ota = now

        prev_a = a
        time.sleep(0.05)


try:
    loop()
except Exception as e:
    # Self-healing recovery: never hard-crash. Keep polling for an OTA fix.
    print("fatal:", e)
    import ota
    try:
        banner("recovery")
    except Exception:
        pass
    while True:
        ota.check_and_update()
        time.sleep(60)

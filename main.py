# main.py - shows the next departures from Quincy Center on a Pimoroni Pico
# Display Pack: the next Red Line train to Alewife (red) and the next commuter
# rail to South Station (purple), refreshed every minute. Below them: the time
# of the last successful fetch, then the firmware version. Also re-checks for
# firmware updates periodically, or on demand via the 'A' button. Wrapped so
# that a crash drops into a recovery loop instead of bricking the device.

import time, gc
from machine import Pin
import urequests
from pimoroni import RGBLED
from picographics import PicoGraphics, DISPLAY_PICO_DISPLAY, PEN_P4

OTA_EVERY  = 300   # re-check for new code every 5 minutes
MBTA_EVERY = 60    # refresh departures every minute
TZ_DEFAULT = -4 * 3600   # fallback if the API doesn't report an offset (EDT)

# MBTA v3 predictions for Quincy Center (parent station place-qnctr). page[limit]=1
# + trimmed fields keep each response tiny, which matters on the Pico.
# Brackets are percent-encoded (%5B/%5D) so the URL is strictly valid on-device.
_BASE = ("https://api-v3.mbta.com/predictions?filter%5Bstop%5D=place-qnctr"
         "&sort=departure_time&page%5Blimit%5D=3"
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
display.set_font("bitmap8")   # default glyphs, not as narrow as bitmap6

# Turn off the Display Pack's RGB LED (GP6/7/8).
RGBLED(6, 7, 8).set_rgb(0, 0, 0)

WIDTH, HEIGHT = display.get_bounds()
BLACK  = display.create_pen(0, 0, 0)
WHITE  = display.create_pen(255, 255, 255)
RED    = display.create_pen(0xDA, 0x29, 0x1C)   # Red Line
PURPLE = display.create_pen(0xC7, 0x92, 0xEA)   # Commuter Rail (lightened for contrast)

MARGIN = 2     # px to keep clear around the text
FONT_H = 8     # glyph height of the bitmap8 font (px per scale step)
SUB_SCALE = 2  # small footer text
DASH = "--"    # placeholder for a missing / over-an-hour departure
# Widest 3-entry list, used to pick one stable digit size (so the numbers don't
# resize as they change). Allows for two-digit minutes plus space separators.
TEMPLATE = "59 59 59"
# Reserve space on each edge so the centred times clear the left RL/CR tag.
TAG_W = max(display.measure_text("RL", scale=SUB_SCALE),
            display.measure_text("CR", scale=SUB_SCALE))
SIDE = MARGIN + TAG_W + 6


def _fit_scale(text, avail_w, avail_h, max_scale=12):
    # Largest integer scale where the text fits within the given area.
    for scale in range(max_scale, 0, -1):
        if (display.measure_text(text, scale=scale) <= avail_w
                and FONT_H * scale <= avail_h):
            return scale
    return 1


def _centre(text, scale, y):
    x = (WIDTH - display.measure_text(text, scale=scale)) // 2
    display.text(text, x, y, scale=scale)


def _left(text, scale, y):
    display.text(text, MARGIN, y, scale=scale)


def _right(text, scale, y):
    display.text(text, WIDTH - MARGIN - display.measure_text(text, scale=scale), y, scale=scale)


def _minutes_until(iso, offset):
    # Floor minutes from now until an ISO departure like "2026-06-25T22:39:57
    # -04:00". Needs a synced clock; RTC is UTC, so subtract the API's offset.
    try:
        local = (int(iso[0:4]), int(iso[5:7]), int(iso[8:10]),
                 int(iso[11:13]), int(iso[14:16]), int(iso[17:19]), 0, 0)
        secs = (time.mktime(local) - offset) - time.time()
        return 0 if secs < 0 else secs // 60
    except Exception:
        return None


def _rel_list(isos, offset):
    # "5 13 24" for the next (up to 3) departures; "--" per missing/over-60.
    if not isos:
        return DASH
    parts = []
    for t in isos[:3]:
        m = _minutes_until(t, offset)
        parts.append(DASH if (m is None or m > 60) else "%d" % m)
    return " ".join(parts)


def banner(text):
    # Single centred line - used for startup/recovery messages.
    display.set_pen(BLACK)
    display.clear()
    display.set_pen(WHITE)
    scale = _fit_scale(text, WIDTH - 2 * MARGIN, HEIGHT - 2 * MARGIN)
    _centre(text, scale, (HEIGHT - FONT_H * scale) // 2)
    display.update()


def draw_board(t1, t2, fetched, version):
    display.set_pen(BLACK)
    display.clear()

    sub_h = FONT_H * SUB_SCALE
    foot_y = HEIGHT - MARGIN - sub_h          # single footer line at the bottom

    # Two rows of departures share the area above the footer. Size from the
    # worst-case template so the digits keep one stable size; reserve SIDE on
    # each edge so the centred numbers clear the left RL/CR tag.
    line_h = (foot_y - 2 - MARGIN) // 2
    scale = _fit_scale(TEMPLATE, WIDTH - 2 * SIDE, line_h)

    # Place the two times as one vertically-centred group; GAP sets the spacing.
    tag_h = FONT_H * SUB_SCALE
    text_h = FONT_H * scale
    GAP = 2
    block_h = 2 * text_h + GAP
    y1 = MARGIN + ((foot_y - MARGIN) - block_h) // 2
    y2 = y1 + text_h + GAP
    display.set_pen(RED)
    _centre(t1, scale, y1)
    _left("RL", SUB_SCALE, y1 + (text_h - tag_h) // 2)
    display.set_pen(PURPLE)
    _centre(t2, scale, y2)
    _left("CR", SUB_SCALE, y2 + (text_h - tag_h) // 2)

    # Footer on one line: fetched time left, truncated version right.
    display.set_pen(WHITE)
    _left(fetched, SUB_SCALE, foot_y)
    _right(version, SUB_SCALE, foot_y)
    display.update()


def _tz_offset(t):
    # Pull the numeric UTC offset out of an ISO time like "...T22:39:57-04:00".
    z = t[19:]
    if not z or z[0] not in "+-":
        return TZ_DEFAULT
    return (-1 if z[0] == "-" else 1) * (int(z[1:3]) * 3600 + int(z[4:6]) * 60)


def _departures(url):
    # Return (list of up to 3 ISO times soonest-first, tz_offset_seconds).
    r = urequests.get(url, headers=HEADERS)
    try:
        data = r.json()["data"]
    finally:
        r.close()
        gc.collect()
    isos, offset = [], None
    for d in data:
        a = d["attributes"]
        t = a.get("departure_time") or a.get("arrival_time")
        if t:
            isos.append(t)
            if offset is None:
                offset = _tz_offset(t)
    return isos, (offset if offset is not None else TZ_DEFAULT)


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
    h, m = lt[3], lt[4]
    ampm = "AM" if h < 12 else "PM"
    h12 = h % 12
    return "%d:%02d %s" % (h12 if h12 else 12, m, ampm)


def loop():
    import ota
    # We reached a clean running state: confirm any pending update so it won't
    # be rolled back on the next boot.
    ota.mark_boot_ok()
    version = ota._local_version() or "?"

    banner("loading")
    clock_ok = _sync_clock()
    t1 = t2 = DASH
    fetched = "--:--"
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
                    isos1, o1 = _departures(RED_URL)
                    isos2, o2 = _departures(CR_URL)
                    offset = o1 or o2 or offset
                    if clock_ok:
                        t1 = _rel_list(isos1, o1)
                        t2 = _rel_list(isos2, o2)
                        fetched = _now_hhmm(offset)
                    else:
                        t1 = t2 = DASH
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

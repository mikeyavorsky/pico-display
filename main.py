# main.py - the app loop. Polls the relay for an action, drives hardware,
# and re-checks for firmware updates periodically. Wrapped so that a crash
# drops into a recovery loop instead of bricking the device.

import urequests, gc, time
from machine import Pin

RELAY_URL    = "https://your-relay.example.com/decide"  # your server (holds the key)
POLL_SECONDS = 15
OTA_EVERY    = 300   # re-check for new code every 5 minutes

led    = Pin("LED", Pin.OUT)                 # onboard LED
button = Pin(14, Pin.IN, Pin.PULL_UP)        # button to GND on GP14


def ask_claude(state):
    r = urequests.post(RELAY_URL, json={"state": state})
    try:
        return r.json()          # e.g. {"led": "on"}
    finally:
        r.close()
        gc.collect()


def apply(action):
    cmd = action.get("led")
    if cmd == "on":
        led.on()
    elif cmd == "off":
        led.off()


def loop():
    import ota
    last_ota = time.time()
    while True:
        state = {"button_pressed": button.value() == 0}
        try:
            action = ask_claude(state)
            print("Claude ->", action)
            apply(action)
        except Exception as e:
            print("decide failed:", e)

        if time.time() - last_ota > OTA_EVERY:
            ota.check_and_update()   # resets if it updates
            last_ota = time.time()

        time.sleep(POLL_SECONDS)


try:
    loop()
except Exception as e:
    # Self-healing recovery: never hard-crash. Keep polling for an OTA fix.
    print("fatal:", e)
    import ota
    led.off()
    while True:
        ota.check_and_update()
        time.sleep(60)

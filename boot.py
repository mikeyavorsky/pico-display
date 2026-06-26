# boot.py - runs automatically on every power-up / reset, before main.py.
#
# Connects WiFi and checks for new code. Keeping the OTA check here (and in
# main's recovery loop) means the device can always pull a fix, even if a bad
# update lands in main.py.

import network, time
import ota
from secrets import SSID, PASSWORD   # see secrets.example.py; not committed


def connect(timeout=20):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(SSID, PASSWORD)
        start = time.time()
        while not wlan.isconnected():
            if time.time() - start > timeout:
                print("WiFi: connect timed out")
                return False
            time.sleep(0.5)
    print("WiFi:", wlan.ifconfig()[0])
    return True


# Before anything else, roll back a previous update that booted but never
# confirmed itself (see ota.mark_boot_ok). Runs offline so a bad update that
# breaks WiFi can still be undone. Resets if it rolls back.
ota.confirm_or_rollback()

if connect():
    ota.check_and_update()   # resets if an update is applied; else falls through
# Execution continues into main.py

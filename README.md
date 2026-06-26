# pico-display

A minimal MicroPython app for the Raspberry Pi Pico W that writes "hello" on a
Pimoroni Pico Display Pack and supports over-the-air (OTA) updates: it
periodically pulls new firmware from a static host, so you can ship fixes
without physically reflashing.

## Hardware

- Raspberry Pi Pico W
- [Pimoroni Pico Display Pack](https://shop.pimoroni.com/products/pico-display-pack)
  (240x135 IPS LCD)

The display is driven with Pimoroni's `picographics` module, so the board needs
the [Pimoroni MicroPython build](https://github.com/pimoroni/pimoroni-pico)
flashed (it bundles the display drivers), not the stock MicroPython image.

## Files

| File | Role |
|------|------|
| `boot.py` | Runs on every power-up: connects WiFi, then checks for an OTA update. |
| `main.py` | Writes "hello" to the Display Pack, then re-checks for updates every 5 minutes. |
| `ota.py` | Pull-based OTA updater. Stages files to `.new` names, then commits by renaming, so a dropped connection can't corrupt running code. Backs up the old version and rolls back if a new one fails to boot. |
| `manifest.json` | Version marker and the list of files an update covers. |

## Setup

1. Create your WiFi credentials file: `cp secrets.example.py secrets.py` and fill
   in `SSID` / `PASSWORD`. `secrets.py` is gitignored, so it stays off the repo.
2. Edit `ota.py` and point `MANIFEST_URL` / `RAW_BASE` at your repo's raw URLs
   (GitHub raw, or any static host).
3. Copy `boot.py`, `main.py`, `ota.py`, `manifest.json`, and `secrets.py` onto
   the Pico W.

## Shipping an update

1. Change the code.
2. Bump `version` in `manifest.json` and make sure `files` lists everything that
   changed.
3. Publish to the host the Pico polls.

On its next OTA check (on boot, or every 5 minutes while running) the device sees
the new version, downloads the listed files, commits them, and resets into the
updated code.

### Safe updates

Two safeguards protect against a broken update:

- **Staging.** Files are downloaded to `.new` names and only swapped over the
  live files once every download succeeds, so a dropped connection mid-download
  can't leave the device running half-new code.
- **Boot confirmation / rollback.** A freshly applied update is committed but
  marked *pending*, with the previous version backed up to `.bak`. The app calls
  `ota.mark_boot_ok()` once it reaches a clean running state. If a bad update
  never gets there, the next boot (`ota.confirm_or_rollback()`) restores the
  backed-up version and records the failed version so it isn't re-applied in a
  loop.

If an update crashes the app while running, `main.py` also falls into a recovery
loop that keeps polling for a fix.

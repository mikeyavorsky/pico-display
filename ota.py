# ota.py - minimal pull-based OTA updater for Pico W (MicroPython)
#
# Polls a manifest, and if the remote version differs from the one stored
# locally, stages all files to ".new" names, then commits by renaming.
# Staging-then-commit means a dropped connection mid-download can never
# corrupt the code that's currently running.

import urequests, uos, gc, machine

# Point these at a GitHub repo (raw URLs) or your own static host.
MANIFEST_URL = "https://raw.githubusercontent.com/USER/REPO/main/manifest.json"
RAW_BASE     = "https://raw.githubusercontent.com/USER/REPO/main/"
VERSION_FILE = "version.txt"


def _local_version():
    try:
        with open(VERSION_FILE) as f:
            return f.read().strip()
    except OSError:
        return ""


def _fetch_json(url):
    r = urequests.get(url)
    try:
        return r.json()
    finally:
        r.close()
        gc.collect()


def _download(url, dest):
    r = urequests.get(url)
    try:
        if r.status_code != 200:
            raise OSError("HTTP %d for %s" % (r.status_code, url))
        with open(dest, "wb") as f:
            f.write(r.content)
    finally:
        r.close()
        gc.collect()


def check_and_update(reset=True):
    """Return True if an update was applied (device resets before returning
    when reset=True)."""
    try:
        manifest = _fetch_json(MANIFEST_URL)
    except Exception as e:
        print("OTA: manifest fetch failed:", e)
        return False

    remote = str(manifest.get("version", ""))
    if remote == _local_version():
        print("OTA: up to date (%s)" % remote)
        return False

    print("OTA: updating %s -> %s" % (_local_version(), remote))
    staged = []
    try:
        # 1) Download everything to staging names. Nothing live is touched yet.
        for name in manifest["files"]:
            _download(RAW_BASE + name, name + ".new")
            staged.append(name)
        # 2) All good -> commit by swapping staged files over the originals.
        for name in staged:
            try:
                uos.remove(name)
            except OSError:
                pass
            uos.rename(name + ".new", name)
        with open(VERSION_FILE, "w") as f:
            f.write(remote)
    except Exception as e:
        print("OTA: failed, rolling back:", e)
        for name in staged:
            try:
                uos.remove(name + ".new")
            except OSError:
                pass
        return False

    print("OTA: applied %s" % remote)
    if reset:
        machine.reset()
    return True

# ota.py - minimal pull-based OTA updater for Pico W (MicroPython)
#
# Polls a manifest, and if the remote version differs from the one stored
# locally, stages all files to ".new" names, then commits by renaming.
# Staging-then-commit means a dropped connection mid-download can never
# corrupt the code that's currently running.
#
# Boot confirmation: a fresh update is committed but left "pending". The app
# calls mark_boot_ok() once it reaches a clean running state; if it never does
# (a bad update that crashes on boot), the next boot rolls back to the backed-up
# previous version. This closes the remaining failure window: power loss during
# the rename phase, or code that commits cleanly but can't actually run.

import urequests, uos, gc, json, machine, time

# Point these at a GitHub repo (raw URLs) or your own static host.
MANIFEST_URL = "https://raw.githubusercontent.com/mikeyavorsky/pico-display/main/manifest.json"
RAW_BASE     = "https://raw.githubusercontent.com/mikeyavorsky/pico-display/main/"
VERSION_FILE = "version.txt"
PENDING_FILE = "update_pending"   # marks an update awaiting first-boot confirmation
BAD_FILE     = "bad_version.txt"  # a version that booted badly and was rolled back
BOOT_TRIES   = 1                  # trial boots allowed before rolling back


def _local_version():
    try:
        with open(VERSION_FILE) as f:
            return f.read().strip()
    except OSError:
        return ""


def _bad_version():
    try:
        with open(BAD_FILE) as f:
            return f.read().strip()
    except OSError:
        return ""


def _read_pending():
    try:
        with open(PENDING_FILE) as f:
            return json.loads(f.read())
    except (OSError, ValueError):
        return None


def _write_pending(data):
    with open(PENDING_FILE, "w") as f:
        f.write(json.dumps(data))


def _remove(name):
    try:
        uos.remove(name)
    except OSError:
        pass


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


def check_and_update(reset=True, fresh=False):
    """Return True if an update was applied (device resets before returning
    when reset=True). With fresh=True, append a cache-busting query param to
    every request so a just-pushed change isn't masked by the raw-host CDN
    cache (handy for an on-demand check); routine polls leave it off to stay
    cache-friendly."""
    bust = "?t=%d" % time.ticks_ms() if fresh else ""
    try:
        manifest = _fetch_json(MANIFEST_URL + bust)
    except Exception as e:
        print("OTA: manifest fetch failed:", e)
        return False

    remote = str(manifest.get("version", ""))
    local = _local_version()
    if remote == local:
        print("OTA: up to date (%s)" % remote)
        return False
    if remote == _bad_version():
        # We already tried this version and it failed to boot. Don't loop on it;
        # wait for the operator to publish a newer one.
        print("OTA: skipping known-bad version %s" % remote)
        return False

    print("OTA: updating %s -> %s" % (local, remote))
    files = manifest["files"]
    staged = []
    try:
        # 1) Download everything to staging names. Nothing live is touched yet.
        for name in files:
            _download(RAW_BASE + name + bust, name + ".new")
            staged.append(name)
        # 2) All good -> back up the live files, then commit by swapping the
        #    staged copies over them. The .bak copies let a failed boot roll back.
        for name in staged:
            _remove(name + ".bak")
            try:
                uos.rename(name, name + ".bak")   # keep the old version
            except OSError:
                pass                               # new file: nothing to back up
            uos.rename(name + ".new", name)
        with open(VERSION_FILE, "w") as f:
            f.write(remote)
        # Mark the update as on-trial. Confirmed by mark_boot_ok(), or rolled
        # back by confirm_or_rollback() if this boot never reaches the app.
        _write_pending({"prev": local, "bad": remote, "files": staged, "tries": 0})
    except Exception as e:
        print("OTA: failed, rolling back:", e)
        for name in staged:
            _remove(name + ".new")
        return False

    print("OTA: applied %s (pending boot confirmation)" % remote)
    if reset:
        machine.reset()
    return True


def _rollback(pending):
    for name in pending.get("files", []):
        _remove(name)
        try:
            uos.rename(name + ".bak", name)   # restore the previous version
        except OSError:
            pass
    with open(VERSION_FILE, "w") as f:
        f.write(pending.get("prev", ""))
    # Remember the version that failed so we don't re-apply it on the next poll.
    with open(BAD_FILE, "w") as f:
        f.write(pending.get("bad", ""))
    _remove(PENDING_FILE)


def confirm_or_rollback(reset=True):
    """Call at boot, before the app runs. If an update is on trial and a prior
    boot already had its chance but never confirmed boot_ok, roll back to the
    backed-up previous version (and reset). Returns True if it rolled back."""
    pending = _read_pending()
    if not pending:
        return False
    if pending.get("tries", 0) >= BOOT_TRIES:
        # The previous boot never set boot_ok -> treat the update as bad.
        print("OTA: update unconfirmed, rolling back to %s" % pending.get("prev", ""))
        _rollback(pending)
        if reset:
            machine.reset()
        return True
    # Give this boot a chance; record the attempt before handing off to the app.
    pending["tries"] = pending.get("tries", 0) + 1
    _write_pending(pending)
    return False


def mark_boot_ok():
    """Call from the app once it has reached a clean running state. Confirms the
    pending update and discards the rollback backups."""
    pending = _read_pending()
    if pending:
        for name in pending.get("files", []):
            _remove(name + ".bak")
        _remove(PENDING_FILE)
        print("OTA: boot confirmed")
    # A version that now boots cleanly is no longer "bad".
    _remove(BAD_FILE)

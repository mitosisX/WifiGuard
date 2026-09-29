"""Background internet watchdog: detects real internet loss and bounces Wi-Fi."""
import ctypes
import queue
import socket
import threading
import time
from datetime import datetime, timedelta

from PySide6.QtCore import QThread, Signal

import store
import wlan

PROBES = [("1.1.1.1", 443), ("8.8.8.8", 443), ("9.9.9.9", 443)]


def internet_ok(timeout=1.5):
    """True if any well-known public endpoint accepts a TCP connection.

    Probes run in parallel and the first success wins, so a healthy check returns in
    milliseconds and a dead one takes `timeout` seconds (not len(PROBES) * timeout).
    """
    result = queue.Queue()

    def probe(host, port):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                result.put(True)
        except OSError:
            result.put(False)

    for host, port in PROBES:
        threading.Thread(target=probe, args=(host, port), daemon=True).start()
    for _ in PROBES:
        if result.get():
            return True
    return False


_dnsapi = ctypes.WinDLL("dnsapi")
_DNS_TYPE_A = 1
_DNS_QUERY_BYPASS_CACHE = 0x8
DNS_PROBE_NAME = "www.msftconnecttest.com"


def dns_ok(timeout=3.0):
    """True if the configured DNS server answers a fresh lookup.

    DnsQuery with BYPASS_CACHE talks to the real resolver; a plain getaddrinfo could be answered
    from Windows' cache and hide a dead DNS relay. The call can't be cancelled, so it runs in a
    daemon thread and we simply stop waiting after `timeout`.
    """
    result = queue.Queue()

    def query():
        records = ctypes.c_void_p()
        rc = _dnsapi.DnsQuery_W(DNS_PROBE_NAME, _DNS_TYPE_A, _DNS_QUERY_BYPASS_CACHE, None,
                                ctypes.byref(records), None)
        if rc == 0 and records.value:
            _dnsapi.DnsRecordListFree(records, 1)   # DnsFreeRecordList
        result.put(rc == 0)

    threading.Thread(target=query, daemon=True).start()
    try:
        return result.get(timeout=timeout)
    except queue.Empty:
        return False


class Monitor(QThread):
    status = Signal(bool, str)      # internet up?, network name ('' if unknown)
    log = Signal(str)
    stats = Signal(int, str)        # reconnect count, last drop time text
    recovering = Signal(bool)
    notify = Signal(str, str)       # title, message (GUI decides whether to show it)
    historyChanged = Signal()

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._manual = False
        self.paused = False
        self.reconnects = store.today_count()
        self._drop_at = None
        self._last_ok = time.monotonic()
        self.last_drop = "never"
        self.last_network = ""
        self._net_checked = 0.0
        self._dns_checked = 0.0
        self._dns_bad_since = None
        self._fails = 0
        self._failed_recoveries = 0
        self._was_up = True
        self._day = datetime.now().date()

    # -- control (called from the GUI thread) --
    def stop(self):
        self._stop.set()
        self._wake.set()

    def reconnect_now(self):
        self._manual = True
        self._wake.set()

    def set_paused(self, paused):
        self.paused = paused
        self._wake.set()

    # -- internals --
    def _say(self, msg):
        self.log.emit(f"{store.clock(datetime.now())}  {msg}")

    def _target(self):
        fixed = self.cfg.network.value
        if fixed != "Auto":
            try:
                if fixed in wlan.saved_profiles():
                    return fixed
            except wlan.WlanError:
                return fixed
            self._say(f"Saved network '{fixed}' no longer exists - falling back to the current one.")
        return wlan.current_network() or self.last_network

    def _recover(self, reason, kind="auto"):
        self.recovering.emit(True)
        try:
            target = self._target()
            if not target:
                self._say("No Wi-Fi network known yet - cannot reconnect.")
                return False
            self._say(f"{reason} Reconnecting to '{target}'...")
            self.notify.emit("Reconnecting Wi-Fi",
                             f"Internet dropped - reconnecting to {target}." if kind == "auto"
                             else f"Reconnecting to {target}.")
            wlan.reconnect(target)
            store.add(kind, target)
            self.reconnects = store.today_count()
            self.stats.emit(self.reconnects, self.last_drop)
            self.historyChanged.emit()
            return True
        except Exception as e:  # noqa: BLE001 - surface any failure in the log
            self._say(f"Reconnect failed: {e}")
            return False
        finally:
            self.recovering.emit(False)

    def _wait_for_internet(self, seconds):
        """Poll quickly after a reconnect; True as soon as the internet answers."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not self._stop.is_set():
            if internet_ok(1.0):
                return True
            self._stop.wait(0.25)
        return False

    def _sleep(self, seconds):
        """Interruptible sleep. Returns True if the machine slept/hibernated during it."""
        due = time.time() + seconds
        self._wake.wait(seconds)
        self._wake.clear()
        return time.time() - due > 20   # wall clock jumped: the PC was suspended

    def _settle(self, why):
        """Give the network time to come up (boot, resume) without counting it as an outage."""
        if not internet_ok(1.0):
            self._say(why)
            self._wait_for_internet(self.cfg.grace.value)
        self._last_ok = time.monotonic()

    def run(self):
        self._say("Monitoring started.")
        self._settle("Waiting for the network to come up...")
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:  # noqa: BLE001 - one bad iteration must never kill protection
                self._say(f"Internal error (continuing): {e}")
                self._sleep(self.cfg.interval.value)
        self._say("Monitoring stopped.")

    def _tick(self):
        """One monitoring iteration: check, then either record recovery or escalate."""
        cfg = self.cfg
        if self._manual:
            self._manual = False
            self._recover("Manual reconnect.", "manual")
            self._wait_for_internet(cfg.grace.value)
            self._fails = 0
            return
        if self.paused:
            self.status.emit(True, "paused")
            self._sleep(1)
            return

        checked_at = time.monotonic()
        if internet_ok():
            self._on_up(checked_at)
            if self._sleep(cfg.interval.value):
                self._settle("Resumed from sleep - letting the network settle.")
            return

        self._fails += 1
        if self._was_up:
            self._on_drop(checked_at)
        self._was_up = False
        self.status.emit(False, self.last_network)
        if self._fails >= cfg.threshold.value:
            self._recover(f"Internet down for {self._fails} checks.")
            self._failed_recoveries += 1
            self._fails = 0
            if self._wait_for_internet(cfg.grace.value):
                return   # the next tick confirms, logs and notifies the recovery at once
            # Still down: back off so an ISP outage doesn't make us thrash the adapter.
            if self._sleep(min(30 * (self._failed_recoveries - 1), 240)):
                self._settle("Resumed from sleep - letting the network settle.")
        elif self._sleep(cfg.interval.value):
            self._settle("Resumed from sleep - letting the network settle.")

    def _on_drop(self, checked_at):
        # The drop happened somewhere between the last good check and this one; take the
        # midpoint so the outage length isn't systematically too short (or too long).
        self._drop_at = (self._last_ok + checked_at) / 2
        dropped = datetime.now() - timedelta(seconds=time.monotonic() - self._drop_at)
        self.last_drop = f"{dropped:%b %d}, {store.clock(dropped)}"
        store.add("drop", self.last_network)
        self.historyChanged.emit()
        self._say("Internet check failed.")

    def _diagnose_dns(self):
        """Log-only: note when raw connectivity works but name lookups don't. Never reconnects.

        Runs every 30 s and needs two failed lookups in a row, so one lost packet isn't reported.
        """
        now = time.monotonic()
        if now - self._dns_checked < 30:
            return
        self._dns_checked = now
        ok = dns_ok() or dns_ok()
        if not ok and self._dns_bad_since is None:
            self._dns_bad_since = now
            self._say("DNS is not resolving although the internet is reachable (diagnostic only).")
            store.add("dns_fail", self.last_network)
            self.historyChanged.emit()
        elif ok and self._dns_bad_since is not None:
            secs = int(now - self._dns_bad_since)
            self._dns_bad_since = None
            self._say(f"DNS is resolving again after about {secs}s.")
            store.add("dns_ok", self.last_network, secs)
            self.historyChanged.emit()

    def _on_up(self, checked_at):
        if not self._was_up:
            secs = int(time.monotonic() - self._drop_at) if self._drop_at else None
            after = f" after {secs}s." if secs is not None else "."
            self._say("Internet is back" + after)
            store.add("recovered", self.last_network, secs)
            if self._failed_recoveries:   # skip noise from blips that healed on their own
                self.notify.emit("Internet is back", "Connection restored" + after)
            self.historyChanged.emit()
            self._failed_recoveries = 0
        self._was_up, self._fails = True, 0
        self._last_ok = checked_at

        fixed = self.cfg.network.value
        if fixed != "Auto":
            self.last_network = fixed
        elif time.monotonic() - self._net_checked > 120:   # spawns PowerShell, so poll sparingly
            self._net_checked = time.monotonic()
            self.last_network = wlan.current_network() or self.last_network
        self.status.emit(True, self.last_network)

        self._diagnose_dns()

        today = datetime.now().date()
        if today != self._day:   # midnight rollover: "Reconnects today" starts from zero
            self._day = today
            self.reconnects = store.today_count()
            self.stats.emit(self.reconnects, self.last_drop)

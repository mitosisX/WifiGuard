"""Background internet watchdog: detects real internet loss and bounces Wi-Fi."""
import queue
import socket
import threading
import time
from datetime import datetime

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
        self.last_drop = "never"
        self.last_network = ""
        self._net_checked = 0.0

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
        self.log.emit(f"{datetime.now():%H:%M:%S}  {msg}")

    def _target(self):
        fixed = self.cfg.network.value
        if fixed != "Auto":
            return fixed
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
        self._wake.wait(seconds)
        self._wake.clear()

    def run(self):
        fails, failed_recoveries, was_up = 0, 0, True
        self._say("Monitoring started.")
        while not self._stop.is_set():
            if self._manual:
                self._manual = False
                self._recover("Manual reconnect.", "manual")
                self._wait_for_internet(self.cfg.grace.value)
                fails = 0
                continue
            if self.paused:
                self.status.emit(True, "paused")
                self._sleep(1)
                continue

            up = internet_ok()
            if up:
                if not was_up:
                    secs = int(time.monotonic() - self._drop_at) if self._drop_at else None
                    self._say("Internet is back" + (f" after {secs}s." if secs is not None else "."))
                    store.add("recovered", self.last_network, secs)
                    if failed_recoveries:   # skip noise from blips that healed on their own
                        self.notify.emit("Internet is back",
                                         "Connection restored" + (f" after {secs}s." if secs else "."))
                    self.historyChanged.emit()
                    failed_recoveries = 0
                was_up, fails = True, 0
                if self.cfg.network.value != "Auto":
                    self.last_network = self.cfg.network.value
                self.status.emit(True, self.last_network)
                # current_network() shells out to PowerShell, so poll it sparingly.
                if self.cfg.network.value == "Auto" and time.monotonic() - self._net_checked > 60:
                    self._net_checked = time.monotonic()
                    n = wlan.current_network()
                    if n and n != self.last_network:
                        self.last_network = n
                        self.status.emit(True, n)
                self._sleep(self.cfg.interval.value)
                continue

            fails += 1
            if was_up:
                self.last_drop = datetime.now().strftime("%b %d, %H:%M:%S")
                self._drop_at = time.monotonic()
                store.add("drop", self.last_network)
                self.historyChanged.emit()
                self._say("Internet check failed.")
            was_up = False
            self.status.emit(False, self.last_network)
            if fails >= self.cfg.threshold.value:
                self._recover(f"Internet down for {fails} checks.")
                failed_recoveries += 1
                fails = 0
                if self._wait_for_internet(self.cfg.grace.value):
                    continue   # next loop iteration confirms, logs and notifies the recovery at once
                # Still down: back off so an ISP outage doesn't make us thrash the adapter.
                self._sleep(min(30 * (failed_recoveries - 1), 240))
            else:
                self._sleep(self.cfg.interval.value)
        self._say("Monitoring stopped.")

"""DNS failing while raw internet works must eventually trigger a reconnect (with backoff)."""
import unittest
from unittest import mock

import monitor


class DnsRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        patches = [
            mock.patch.object(monitor, "store"),
            mock.patch.object(monitor.time, "monotonic", side_effect=lambda: self.now),
            mock.patch.object(monitor, "dns_ok", return_value=False),
        ]
        self.store, _, self.dns = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.store.today_count.return_value = 0
        self.store.last_drop.return_value = None
        self.mon = monitor.Monitor(mock.MagicMock())
        self.mon.last_network = "TestNet"
        self.recover = mock.patch.object(self.mon, "_recover", return_value=True).start()
        self.addCleanup(mock.patch.stopall)

    def check(self, advance=30):
        self.now += advance
        self.mon._diagnose_dns()

    def test_short_dns_blip_does_not_reconnect(self):
        self.check()          # first failed check: only logged
        self.check()          # 30 s in
        self.recover.assert_not_called()

    def test_sustained_dns_failure_reconnects_once(self):
        for _ in range(3):    # fails at 0 s, 30 s, 60 s
            self.check()
        self.recover.assert_called_once()

    def test_still_failing_after_reconnect_backs_off(self):
        for _ in range(3):
            self.check()
        self.recover.reset_mock()
        self.check()          # 30 s after the reconnect: too soon to bounce again
        self.recover.assert_not_called()

    def test_dns_recovering_resets_the_countdown(self):
        self.check()
        self.check()
        self.dns.return_value = True
        self.check()          # healthy again
        self.dns.return_value = False
        self.check()
        self.check()          # only 2 failures since the reset
        self.recover.assert_not_called()


if __name__ == "__main__":
    unittest.main()

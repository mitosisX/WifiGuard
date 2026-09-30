"""Activity log lines and "last drop" must survive an app restart."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

import store


class PersistenceTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for p in (mock.patch.object(store, "DATA_DIR", tmp.name),
                  mock.patch.object(store, "DB_PATH", os.path.join(tmp.name, "history.db"))):
            p.start()
            self.addCleanup(p.stop)

    def test_activity_lines_come_back_in_order(self):
        store.log_add("Monitoring started.")
        store.log_add("Internet check failed.")
        self.assertEqual([m for _, m in store.log_today()],
                         ["Monitoring started.", "Internet check failed."])

    def test_only_todays_activity_is_restored(self):
        with store.closing(store._connect()) as con, con:
            yesterday = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
            con.execute("INSERT INTO activity (ts, msg) VALUES (?, ?)", (yesterday, "old"))
        store.log_add("new")
        self.assertEqual([m for _, m in store.log_today()], ["new"])

    def test_prune_drops_old_activity_only(self):
        with store.closing(store._connect()) as con, con:
            old = (datetime.now() - timedelta(days=40)).isoformat(timespec="seconds")
            con.execute("INSERT INTO activity (ts, msg) VALUES (?, ?)", (old, "ancient"))
        store.log_add("recent")
        store.prune_log(days=30)
        with store.closing(store._connect()) as con:
            msgs = [m for (m,) in con.execute("SELECT msg FROM activity")]
        self.assertEqual(msgs, ["recent"])

    def test_last_drop_is_none_without_drops(self):
        store.add("auto", "Net")
        self.assertIsNone(store.last_drop())

    def test_last_drop_is_the_newest_drop(self):
        store.add("drop", "Net")
        store.add("recovered", "Net", 5)
        got = store.last_drop()
        self.assertIsInstance(got, datetime)
        self.assertLess(abs(datetime.now() - got), timedelta(seconds=5))

    def test_clearing_history_forgets_last_drop(self):
        store.add("drop", "Net")
        store.clear()
        self.assertIsNone(store.last_drop())


if __name__ == "__main__":
    unittest.main()

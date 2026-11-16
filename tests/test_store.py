"""持久化层单元测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from .helpers import make_arcade
from astrbot_plugin_maimai_card_report.backend.models import AbnormalUser, CardRecord
from astrbot_plugin_maimai_card_report.backend.store import PluginStore


class TestPluginStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = PluginStore(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_arcade_crud(self):
        arcade = make_arcade()
        self.store.upsert_arcade(arcade)
        self.assertEqual(self.store.get_arcade("a_1").name, "天河城")
        self.assertEqual(len(self.store.list_arcades()), 1)
        self.store.delete_arcade("a_1")
        self.assertIsNone(self.store.get_arcade("a_1"))

    def test_record_roundtrip(self):
        rec = CardRecord(arcade_id="a_1", machine_id="m_maimai", position_key="z", count=5)
        self.store.set_record(rec)
        self.store.save_records()
        got = self.store.get_record("a_1", "m_maimai", "z")
        self.assertEqual(got.count, 5)
        recs = self.store.machine_records("a_1", "m_maimai")
        self.assertEqual(len(recs), 1)

    def test_abnormal_roundtrip(self):
        u = AbnormalUser(arcade_id="a_1", qq="123", abnormal_count=3)
        self.store.set_abnormal(u)
        self.store.save_abnormal()
        self.assertEqual(self.store.get_abnormal("a_1", "123").abnormal_count, 3)

    def test_clear_machine_abnormal(self):
        self.store.set_abnormal(AbnormalUser(arcade_id="a_1", qq="1", machine_id="m_1"))
        self.store.set_abnormal(AbnormalUser(arcade_id="a_1", qq="2", machine_id="m_2"))
        self.store.set_abnormal(AbnormalUser(arcade_id="a_2", qq="3", machine_id="m_1"))
        self.store.clear_machine_abnormal("a_1", "m_1")
        self.assertIsNone(self.store.get_abnormal("a_1", "1"))
        self.assertIsNotNone(self.store.get_abnormal("a_1", "2"))
        self.assertIsNotNone(self.store.get_abnormal("a_2", "3"))

    def test_clear_arcade_abnormal(self):
        self.store.set_abnormal(AbnormalUser(arcade_id="a_1", qq="1", machine_id="m_1"))
        self.store.set_abnormal(AbnormalUser(arcade_id="a_1", qq="2", machine_id="m_2"))
        self.store.set_abnormal(AbnormalUser(arcade_id="a_2", qq="3", machine_id="m_1"))
        self.store.clear_arcade_abnormal("a_1")
        self.assertIsNone(self.store.get_abnormal("a_1", "1"))
        self.assertIsNone(self.store.get_abnormal("a_1", "2"))
        self.assertIsNotNone(self.store.get_abnormal("a_2", "3"))

    def test_delete_arcade_cascade(self):
        self.store.upsert_arcade(make_arcade())
        self.store.set_record(CardRecord(arcade_id="a_1", machine_id="m_maimai", position_key="z", count=5))
        self.store.set_abnormal(AbnormalUser(arcade_id="a_1", qq="1", machine_id="m_maimai"))
        self.store.delete_arcade("a_1")
        self.assertIsNone(self.store.get_record("a_1", "m_maimai", "z"))
        self.assertIsNone(self.store.get_abnormal("a_1", "1"))

    def test_logs(self):
        self.store.add_log("info", "111", "测试日志")
        logs = self.store.list_logs(10)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].message, "测试日志")

    def test_persistence_reload(self):
        self.store.upsert_arcade(make_arcade())
        store2 = PluginStore(Path(self.tmp.name))
        self.assertEqual(store2.get_arcade("a_1").name, "天河城")

    def test_log_level_filters_debug(self):
        store = PluginStore(Path(self.tmp.name), log_level="info")
        store.add_log("debug", "111", "调试日志")
        store.add_log("info", "111", "业务日志")
        messages = [x.message for x in store.list_logs(10)]
        self.assertNotIn("调试日志", messages)
        self.assertIn("业务日志", messages)

    def test_log_max_entries_configurable(self):
        store = PluginStore(Path(self.tmp.name), log_max_entries=100)
        for i in range(120):
            store.add_log("info", "111", f"日志{i}")
        self.assertEqual(len(store.list_logs(1000)), 100)
        self.assertEqual(store.list_logs(1)[0].message, "日志119")

    def test_prune_group_sessions(self):
        self.store.upsert_arcade(make_arcade(group_ids=["111111"]))
        self.store.state.group_sessions = {
            "111111": "bot:GroupMessage:111111",
            "222222": "bot:GroupMessage:222222",
        }
        self.store.save_state()
        self.assertEqual(self.store.prune_group_sessions(), 1)
        self.assertIn("111111", self.store.state.group_sessions)
        self.assertNotIn("222222", self.store.state.group_sessions)
        # 重新加载后仍然是清理后的结果
        store2 = PluginStore(Path(self.tmp.name))
        self.assertNotIn("222222", store2.state.group_sessions)


if __name__ == "__main__":
    unittest.main()
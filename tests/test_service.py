"""业务逻辑单元测试：机厅匹配、报卡、查询、异常过滤、黑名单、超时清零。"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from .helpers import FakeEvent, make_arcade, make_machine
from astrbot_plugin_maimai_card_report.backend.models import AbnormalUser, CardRecord
from astrbot_plugin_maimai_card_report.backend.service import ReportService
from astrbot_plugin_maimai_card_report.backend.store import PluginStore
from astrbot_plugin_maimai_card_report.utils import now_ts


class TestService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = PluginStore(Path(self.tmp.name))
        self.store.upsert_arcade(make_arcade(name="天河城", aliases=["zy"], group_ids=["111111"]))
        self.service = ReportService(self.store, context=None)

    def tearDown(self):
        self.tmp.cleanup()

    # ---------- 机厅匹配 ----------

    def test_resolve_by_alias(self):
        res = self.service.resolve_arcade("zy5k", "111111")
        self.assertEqual(res.arcade.name, "天河城")
        self.assertEqual(res.rest, "5k")

    def test_resolve_by_group_binding(self):
        res = self.service.resolve_arcade("5k", "111111")
        self.assertEqual(res.arcade.name, "天河城")

    def test_resolve_unbound_group(self):
        res = self.service.resolve_arcade("5k", "999999")
        self.assertIsNone(res.arcade)

    def test_is_managed_group(self):
        self.assertTrue(self.service.is_managed_group("111111"))
        self.assertFalse(self.service.is_managed_group("999999"))
        self.assertFalse(self.service.is_managed_group(""))
        self.assertFalse(self.service.is_managed_group(None))

    def test_resolve_ambiguous(self):
        self.store.upsert_arcade(make_arcade(arcade_id="a_2", name="白云", group_ids=["111111"]))
        res = self.service.resolve_arcade("5k", "111111")
        self.assertTrue(res.ambiguous)
        self.assertIsNone(res.arcade)

    # ---------- help 指令 ----------

    def test_is_help_request(self):
        for text in ("help", "帮助", "怎么报卡", "报卡说明"):
            self.assertTrue(self.service.is_help_request(text), text)
        for text in ("5k", "左2右3", "几卡"):
            self.assertFalse(self.service.is_help_request(text), text)

    def test_help_reply(self):
        outcome = asyncio.run(self.service.handle_event(FakeEvent("help")))
        self.assertTrue(outcome.should_stop)
        self.assertIn("使用说明", outcome.reply)
        self.assertIn("z3y5", outcome.reply)
        self.assertIn("扣减", outcome.reply)
        self.assertIn("当前机厅「天河城」", outcome.reply)

    def test_help_in_unbound_group(self):
        outcome = asyncio.run(self.service.handle_event(FakeEvent("帮助", group_id="999999")))
        self.assertTrue(outcome.should_stop)
        self.assertIn("使用说明", outcome.reply)
        self.assertNotIn("当前机厅", outcome.reply)

    def test_error_reply_includes_help_hint(self):
        outcome = asyncio.run(self.service.handle_event(FakeEvent("左30")))
        self.assertIn("help", outcome.reply)

    def test_llm_tease_without_context_falls_back(self):
        # 第 4 次异常会尝试调用 LLM 调侃；context 为 None 时必须回退默认文案
        for _ in range(3):
            asyncio.run(self.service.handle_event(FakeEvent("左30")))
        outcome = asyncio.run(self.service.handle_event(FakeEvent("左30")))
        self.assertIn("报卡失败", outcome.reply)
        self.assertIn("help", outcome.reply)
        user = self.store.get_abnormal("a_1", "222222")
        self.assertEqual(user.abnormal_count, 4)
        self.assertEqual(user.status, "warning")

    # ---------- 报卡 ----------

    def test_normal_report(self):
        outcome = asyncio.run(self.service.handle_event(FakeEvent("左2右3")))
        self.assertTrue(outcome.should_stop)
        self.assertEqual(outcome.reply, "天河城 舞萌 左:2 右:3")

    def test_increment_report(self):
        asyncio.run(self.service.handle_event(FakeEvent("左2")))
        outcome = asyncio.run(self.service.handle_event(FakeEvent("左+3")))
        self.assertIn("左:5", outcome.reply)

    def test_overwrite_report(self):
        asyncio.run(self.service.handle_event(FakeEvent("左5")))
        outcome = asyncio.run(self.service.handle_event(FakeEvent("左3")))
        self.assertIn("左:3", outcome.reply)

    def test_decrement_report(self):
        asyncio.run(self.service.handle_event(FakeEvent("左5")))
        outcome = asyncio.run(self.service.handle_event(FakeEvent("左-2")))
        self.assertIn("左:3", outcome.reply)
        self.assertEqual(self.store.get_record("a_1", "m_maimai", "z").count, 3)

    def test_decrement_count_only(self):
        asyncio.run(self.service.handle_event(FakeEvent("5k")))
        outcome = asyncio.run(self.service.handle_event(FakeEvent("-1k")))
        self.assertIn("左:4", outcome.reply)
        self.assertEqual(self.store.get_record("a_1", "m_maimai", "z").count, 4)

    def test_decrement_clamped_at_zero(self):
        asyncio.run(self.service.handle_event(FakeEvent("左2")))
        outcome = asyncio.run(self.service.handle_event(FakeEvent("左-5")))
        self.assertIn("左:0", outcome.reply)
        self.assertEqual(self.store.get_record("a_1", "m_maimai", "z").count, 0)

    def test_decrement_without_record_does_not_create(self):
        outcome = asyncio.run(self.service.handle_event(FakeEvent("左-1")))
        self.assertIn("左:0", outcome.reply)
        self.assertIsNone(self.store.get_record("a_1", "m_maimai", "z"))

    def test_bare_number_ignored(self):
        # 裸数字属于普通聊天：不回复、不写记录、不计异常
        for text in ("6", "666", "2026", "114514"):
            outcome = asyncio.run(self.service.handle_event(FakeEvent(text)))
            self.assertIsNone(outcome.reply, text)
            self.assertFalse(outcome.should_stop, text)
        self.assertIsNone(self.store.get_record("a_1", "m_maimai", "z"))
        self.assertIsNone(self.store.get_abnormal("a_1", "222222"))

    # ---------- 查询 ----------

    def test_query(self):
        asyncio.run(self.service.handle_event(FakeEvent("左2右3")))
        outcome = asyncio.run(self.service.handle_event(FakeEvent("几卡")))
        self.assertIn("排卡", outcome.reply)
        self.assertIn("左：2 人", outcome.reply)
        self.assertIn("右：3 人", outcome.reply)

    def test_query_all_machines(self):
        self.store.upsert_arcade(make_arcade(
            name="真快活",
            machines={
                "m_maimai": make_machine(name="舞萌", is_default=True),
                "m_taiko": make_machine(
                    machine_id="m_taiko",
                    name="太鼓达人",
                    aliases=["太鼓"],
                    is_default=False,
                    position_aliases={"z": "总"},
                ),
            },
        ))
        asyncio.run(self.service.handle_event(FakeEvent("左2")))
        asyncio.run(self.service.handle_event(FakeEvent("太鼓总3")))
        outcome = asyncio.run(self.service.handle_event(FakeEvent("几卡")))
        self.assertIn("舞萌", outcome.reply)
        self.assertIn("太鼓达人", outcome.reply)
        self.assertIn("左：2 人", outcome.reply)
        self.assertIn("总：3 人", outcome.reply)

    # ---------- 异常与黑名单 ----------

    def test_out_of_range(self):
        outcome = asyncio.run(self.service.handle_event(FakeEvent("左30")))
        self.assertIn("30", outcome.reply)
        user = self.store.get_abnormal("a_1", "222222")
        self.assertEqual(user.abnormal_count, 1)
        self.assertEqual(user.status, "warning")

    def test_decrement_keeps_abnormal_untouched(self):
        outcome = asyncio.run(self.service.handle_event(FakeEvent("左-3")))
        self.assertIn("左:0", outcome.reply)
        self.assertIsNone(self.store.get_abnormal("a_1", "222222"))

    def test_blacklist_after_five(self):
        for _ in range(4):
            asyncio.run(self.service.handle_event(FakeEvent("左30")))
        user = self.store.get_abnormal("a_1", "222222")
        self.assertEqual(user.status, "warning")
        self.assertEqual(user.abnormal_count, 4)

        outcome = asyncio.run(self.service.handle_event(FakeEvent("左30")))
        user = self.store.get_abnormal("a_1", "222222")
        self.assertEqual(user.status, "ignored")
        self.assertTrue(outcome.should_stop)
        self.assertIsNone(outcome.reply)

        # 加入黑名单后即使正常报卡也被静默忽略
        outcome = asyncio.run(self.service.handle_event(FakeEvent("左2")))
        self.assertTrue(outcome.should_stop)
        self.assertIsNone(outcome.reply)

    # ---------- 超时清零 ----------

    def test_expire_clear(self):
        rec = CardRecord(
            arcade_id="a_1", machine_id="m_maimai", position_key="z",
            count=5, last_update_at=now_ts() - 5 * 3600,
        )
        self.store.set_record(rec)
        self.store.save_records()
        self.service.clear_expired()
        self.assertEqual(self.store.get_record("a_1", "m_maimai", "z").count, 0)

    def test_not_expired(self):
        rec = CardRecord(
            arcade_id="a_1", machine_id="m_maimai", position_key="z",
            count=5, last_update_at=now_ts(),
        )
        self.store.set_record(rec)
        self.store.save_records()
        self.service.clear_expired()
        self.assertEqual(self.store.get_record("a_1", "m_maimai", "z").count, 5)

    def test_lazy_clear_machine(self):
        rec = CardRecord(
            arcade_id="a_1", machine_id="m_maimai", position_key="z",
            count=5, last_update_at=now_ts() - 10 * 3600,
        )
        self.store.set_record(rec)
        arcade = self.store.get_arcade("a_1")
        machine = arcade.machines["m_maimai"]
        self.assertTrue(self.service.lazy_clear_machine(arcade, machine))
        self.assertEqual(self.store.get_record("a_1", "m_maimai", "z").count, 0)

    def test_query_after_clear(self):
        rec = CardRecord(
            arcade_id="a_1", machine_id="m_maimai", position_key="z",
            count=5, last_update_at=now_ts() - 10 * 3600,
        )
        self.store.set_record(rec)
        outcome = asyncio.run(self.service.handle_event(FakeEvent("几卡")))
        self.assertIn("左：0 人（已超时清零，最后报卡 ", outcome.reply)

    def test_query_stale_zero_count_non_default(self):
        self.store.upsert_arcade(make_arcade(
            name="真快活",
            machines={
                "m_maimai": make_machine(name="舞萌", is_default=True),
                "m_taiko": make_machine(
                    machine_id="m_taiko",
                    name="太鼓达人",
                    aliases=["太鼓"],
                    is_default=False,
                    position_aliases={"z": "总"},
                ),
            },
        ))
        self.store.set_record(CardRecord(
            arcade_id="a_1", machine_id="m_taiko", position_key="z",
            count=0, last_update_at=now_ts() - 10 * 3600,
        ))
        outcome = asyncio.run(self.service.handle_event(FakeEvent("几卡")))
        self.assertIn("总：0 人（已超时清零，最后报卡 ", outcome.reply)

    def test_query_fresh_zero_count_not_cleared(self):
        self.store.upsert_arcade(make_arcade(
            name="真快活",
            machines={
                "m_maimai": make_machine(name="舞萌", is_default=True),
                "m_taiko": make_machine(
                    machine_id="m_taiko",
                    name="太鼓达人",
                    aliases=["太鼓"],
                    is_default=False,
                    position_aliases={"z": "总"},
                ),
            },
        ))
        self.store.set_record(CardRecord(
            arcade_id="a_1", machine_id="m_taiko", position_key="z",
            count=0, last_update_at=now_ts(),
        ))
        outcome = asyncio.run(self.service.handle_event(FakeEvent("几卡")))
        self.assertIn("总：0 人（更新于 ", outcome.reply)
        self.assertNotIn("清零于", outcome.reply)

    # ---------- 异常文案 / 清零 / 通知 ----------

    def test_unparseable_error_message_not_about_range(self):
        # 格式异常不应套用「超出正常范围」模板
        outcome = asyncio.run(self.service.handle_event(FakeEvent("卡")))
        self.assertIn("没能识别出报卡人数", outcome.reply)
        self.assertNotIn("超出正常范围", outcome.reply)

    def test_out_of_range_error_message_keeps_template(self):
        outcome = asyncio.run(self.service.handle_event(FakeEvent("左30")))
        self.assertIn("超出正常范围（0-20）", outcome.reply)

    def test_lazy_clear_machine_clears_blacklist(self):
        # 需求 §7.2：机台全部方位超时清零时解除该机台黑名单
        self.store.set_record(CardRecord(
            arcade_id="a_1", machine_id="m_maimai", position_key="z",
            count=5, last_update_at=now_ts() - 10 * 3600,
        ))
        self.store.set_abnormal(AbnormalUser(
            arcade_id="a_1", qq="u1", machine_id="m_maimai",
            abnormal_count=5, status="ignored",
        ))
        arcade = self.store.get_arcade("a_1")
        cleared = self.service.lazy_clear_machine(arcade, arcade.machines["m_maimai"])
        self.assertTrue(cleared)
        self.assertIsNone(self.store.get_abnormal("a_1", "u1"))

    def test_send_notice_without_session_returns_false(self):
        # 没有群会话时发送失败，调用方不应把当天标记为已发
        arcade = self.store.get_arcade("a_1")
        self.assertFalse(asyncio.run(self.service._send_notice(arcade, "open")))

    # ---------- @ 提及前缀 ----------

    def test_at_prefix_bare_unit(self):
        out = asyncio.run(self.service.handle_event(FakeEvent("@bot 5k")))
        self.assertIn("左:5", out.reply)

    def test_at_prefix_with_qq_id(self):
        out = asyncio.run(self.service.handle_event(FakeEvent("@机器人(123456) 5卡")))
        self.assertIn("左:5", out.reply)

    def test_at_prefix_position(self):
        out = asyncio.run(self.service.handle_event(FakeEvent("@bot 左3")))
        self.assertIn("左:3", out.reply)

    def test_at_prefix_machine_bare_number(self):
        out = asyncio.run(self.service.handle_event(FakeEvent("@bot 舞萌3")))
        self.assertIn("左:3", out.reply)

    def test_at_prefix_does_not_break_plain_chat(self):
        out = asyncio.run(self.service.handle_event(FakeEvent("@小明(123456) 你怎么知道")))
        self.assertIsNone(out.reply)

    # ---------- help 匹配 ----------

    def test_help_independent_word(self):
        for text in ("help", "help me", "could you help?", "帮助", "求帮助"):
            with self.subTest(text=text):
                out = asyncio.run(self.service.handle_event(FakeEvent(text)))
                self.assertIsNotNone(out.reply)
                self.assertIn("使用说明", out.reply)

    def test_help_not_triggered_inside_word(self):
        for text in ("helped", "helper", "helpful"):
            with self.subTest(text=text):
                out = asyncio.run(self.service.handle_event(FakeEvent(text)))
                self.assertIsNone(out.reply)


if __name__ == "__main__":
    unittest.main()
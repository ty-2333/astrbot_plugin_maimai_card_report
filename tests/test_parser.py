"""文本解析单元测试：机厅/机台/方位匹配、报卡与查询解析、正负号与累加。"""

from __future__ import annotations

import unittest

from .helpers import make_arcade, make_machine
from astrbot_plugin_maimai_card_report.utils import (
    cn_num_to_int,
    normalize_text,
    strip_mention_prefix,
)
from astrbot_plugin_maimai_card_report.backend.parser import (
    default_machine,
    extract_signed_count,
    first_position_key,
    is_query,
    looks_like_report_attempt,
    match_arcade,
    match_machine,
    parse_query,
    parse_report,
)


class TestNormalize(unittest.TestCase):
    def test_halfwidth_and_lower(self):
        self.assertEqual(normalize_text("　Ｚｙ　５Ｋ　"), "zy 5k")

    def test_chinese_number(self):
        self.assertEqual(cn_num_to_int("十"), 10)
        self.assertEqual(cn_num_to_int("十五"), 15)
        self.assertEqual(normalize_text("舞萌 左十卡"), "舞萌 左10卡")

    def test_none_and_blank(self):
        self.assertEqual(normalize_text(None), "")
        self.assertEqual(normalize_text("   "), "")


class TestMatchArcade(unittest.TestCase):
    def test_match_alias(self):
        arcade = make_arcade(name="天河城", aliases=["zy", "thc"])
        arcade2 = make_arcade(arcade_id="a_2", name="白云", aliases=["by"])
        matched = match_arcade("zy5k", [arcade, arcade2])
        self.assertIsNotNone(matched)
        arc, rest = matched
        self.assertEqual(arc.id, "a_1")
        self.assertEqual(rest, "5k")

    def test_longest_alias_priority(self):
        arcade = make_arcade(name="天河城", aliases=["zy", "zyx"])
        matched = match_arcade("zyx3k", [arcade])
        self.assertEqual(matched[1], "3k")

    def test_no_match(self):
        arcade = make_arcade(name="天河城", aliases=["zy"])
        self.assertIsNone(match_arcade("白云5k", [arcade]))


class TestMatchMachine(unittest.TestCase):
    def test_match(self):
        arcade = make_arcade()
        m, rest = match_machine("舞萌2k", arcade)
        self.assertEqual(m.name, "舞萌")
        self.assertEqual(rest, "2k")

    def test_default_machine(self):
        arcade = make_arcade()
        self.assertEqual(default_machine(arcade).name, "舞萌")


class TestParseReport(unittest.TestCase):
    def setUp(self):
        self.arcade = make_arcade()

    def test_positions(self):
        parsed = parse_report("左2右3", self.arcade)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.machine.name, "舞萌")
        self.assertEqual([(e.position_key, e.count, e.increment) for e in parsed.entries],
                         [("z", 2, False), ("y", 3, False)])

    def test_number_first_format(self):
        parsed = parse_report("2左3右", self.arcade)
        self.assertEqual([(e.position_key, e.count) for e in parsed.entries],
                         [("z", 2), ("y", 3)])

    def test_numeric_prefix_not_taken_as_count(self):
        # 「中二」会被归一化成「中2」，前缀这个 2 不能被当成左方位的人数
        parsed = parse_report(normalize_text("中二z1y2"), self.arcade)
        self.assertEqual([(e.position_key, e.count) for e in parsed.entries],
                         [("z", 1), ("y", 2)])

    def test_multi_segment_with_space_keeps_all(self):
        parsed = parse_report(normalize_text("左5 z1y2"), self.arcade)
        pairs = [(e.position_key, e.count) for e in parsed.entries]
        self.assertIn(("z", 5), pairs)
        self.assertIn(("y", 2), pairs)

    def test_plus_increment(self):
        parsed = parse_report("左+2", self.arcade)
        self.assertEqual((parsed.entries[0].position_key, parsed.entries[0].count,
                          parsed.entries[0].increment), ("z", 2, True))

    def test_minus_decrement(self):
        parsed = parse_report("左-2", self.arcade)
        entry = parsed.entries[0]
        self.assertEqual((entry.position_key, entry.count, entry.decrement),
                         ("z", 2, True))
        self.assertFalse(entry.increment)

    def test_only_count(self):
        parsed = parse_report("5k", self.arcade)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.entries[0].position_key, "z")
        self.assertEqual(parsed.entries[0].count, 5)
        self.assertFalse(parsed.entries[0].increment)
        self.assertFalse(parsed.entries[0].decrement)

    def test_bare_number_not_report(self):
        # 裸数字属于普通聊天，不再当成默认机台报卡
        for text in ("6", "666", "2026", "114514"):
            self.assertIsNone(parse_report(text, self.arcade), text)
            self.assertIsNone(extract_signed_count(text), text)

    def test_count_only_with_sign(self):
        parsed = parse_report("-2k", self.arcade)
        entry = parsed.entries[0]
        self.assertEqual((entry.position_key, entry.count, entry.decrement), ("z", 2, True))

        parsed = parse_report("+3", self.arcade)
        entry = parsed.entries[0]
        self.assertEqual((entry.position_key, entry.count, entry.increment), ("z", 3, True))

    def test_position_decrement_number_first(self):
        parsed = parse_report("-1z", self.arcade)
        entry = parsed.entries[0]
        self.assertEqual((entry.position_key, entry.count, entry.decrement), ("z", 1, True))

    def test_unparseable(self):
        self.assertIsNone(parse_report("你好", self.arcade))

    def test_prefix_junk_not_count_only(self):
        # 杂散前缀 + 数字不应被当成「默认机台仅数量」报卡
        self.assertIsNone(parse_report("ij2k", self.arcade))
        self.assertIsNone(parse_report("tg1k", self.arcade))

    def test_tg_alias_matches_taiko(self):
        arcade = make_arcade(machines={
            "m_maimai": make_machine(name="舞萌", is_default=True),
            "m_taiko": make_machine(
                machine_id="m_taiko",
                name="太鼓达人",
                aliases=["太鼓", "tg"],
                is_default=False,
                position_aliases={"z": "总"},
            ),
        })
        parsed = parse_report("tg1k", arcade)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.machine.name, "太鼓达人")
        self.assertEqual(parsed.entries[0].count, 1)

    def test_first_position_key(self):
        self.assertEqual(first_position_key(self.arcade.machines["m_maimai"]), "z")


class TestQuery(unittest.TestCase):
    def setUp(self):
        self.arcade = make_arcade()

    def test_is_query(self):
        self.assertTrue(is_query("几卡"))
        self.assertTrue(is_query("jk"))
        self.assertTrue(is_query("?k"))
        self.assertTrue(is_query("?卡"))
        self.assertFalse(is_query("?"))
        self.assertFalse(is_query("现在?"))
        self.assertFalse(is_query("不是?"))
        self.assertFalse(is_query("5k"))

    def test_double_question_mark_not_query(self):
        self.assertFalse(is_query("??"))
        self.assertFalse(is_query("??2"))
        self.assertFalse(is_query("??2k"))

    def test_parse_query(self):
        q = parse_query("几卡", self.arcade)
        self.assertIsNotNone(q)
        self.assertIsNone(q.machine)  # 未指定机台时查询机厅内所有机台

    def test_parse_query_machine(self):
        arcade = make_arcade(machines={
            "m_maimai": make_machine(name="舞萌", is_default=True),
            "m_chuni": make_machine(machine_id="m_chuni", name="中二", aliases=["中二"], is_default=False, position_aliases={"z": "左"}),
        })
        # 输入需与消息处理一致地经过归一化（中文数字「二」→ 2）
        q = parse_query(normalize_text("中二几卡"), arcade)
        self.assertEqual(q.machine.name, "中二")


class TestLooksLikeAttempt(unittest.TestCase):
    def test_attempt(self):
        arcade = make_arcade()
        # 含卡数单位 / 方位别名但缺数字 → 视为一次失败的报卡尝试
        self.assertTrue(looks_like_report_attempt("左k", arcade))

    def test_not_attempt(self):
        arcade = make_arcade()
        self.assertFalse(looks_like_report_attempt("今天天气不错", arcade))

    def test_ordinary_sentence_with_person_char_not_attempt(self):
        arcade = make_arcade()
        # 普通聊天里的“人”不应被当成报卡单位
        self.assertFalse(looks_like_report_attempt("我那天还是别人请的", arcade))
        self.assertFalse(looks_like_report_attempt("又不是每个人都有这么多号", arcade))

    def test_question_mark_suffix_not_attempt(self):
        arcade = make_arcade()
        self.assertFalse(looks_like_report_attempt("现在?", arcade))
        self.assertFalse(looks_like_report_attempt("不是?", arcade))

    def test_english_ok_not_attempt(self):
        arcade = make_arcade()
        # “ok”里虽然有 k，但不属于报卡格式
        self.assertFalse(looks_like_report_attempt("ok", arcade))

    def test_bare_number_not_attempt(self):
        arcade = make_arcade()
        # 裸数字不再触发异常报卡，也不计入黑名单
        for text in ("6", "666", "2026", "114514"):
            self.assertFalse(looks_like_report_attempt(text, arcade), text)

    def test_date_with_dash_not_attempt(self):
        arcade = make_arcade()
        self.assertFalse(looks_like_report_attempt("2026-11", arcade))


class TestReportBoundaries(unittest.TestCase):
    """报卡边界：裸数字只有在显式机台前缀位于句首时才成立。"""

    def setUp(self):
        self.arcade = make_arcade(
            name="真快活",
            aliases=["wx"],
            machines={
                "m_maimai": make_machine(
                    machine_id="m_maimai", name="舞萌", aliases=["wm"],
                    is_default=True, position_aliases={"z": "左", "y": "右"},
                ),
                "m_taiko": make_machine(
                    machine_id="m_taiko", name="太鼓达人", aliases=["太鼓", "tg"],
                    is_default=False, position_aliases={"z": "总"},
                ),
            },
        )

    def test_machine_prefix_bare_number_accepted(self):
        cases = [
            ("tg2", "太鼓达人", "z", 2),
            ("tg 2", "太鼓达人", "z", 2),
            ("太鼓2", "太鼓达人", "z", 2),
            ("太鼓 2", "太鼓达人", "z", 2),
            ("太鼓达人2", "太鼓达人", "z", 2),
            ("wm3", "舞萌", "z", 3),
            ("舞萌3", "舞萌", "z", 3),
        ]
        for text, machine, pos, count in cases:
            with self.subTest(text=text):
                parsed = parse_report(text, self.arcade)
                self.assertIsNotNone(parsed, text)
                self.assertEqual(parsed.machine.name, machine)
                self.assertEqual(
                    (parsed.entries[0].position_key, parsed.entries[0].count),
                    (pos, count),
                )

    def test_machine_prefix_bare_number_with_sign_still_works(self):
        parsed = parse_report("tg+1", self.arcade)
        self.assertTrue(parsed.entries[0].increment)
        self.assertEqual(parsed.entries[0].count, 1)

    def test_plain_numbers_rejected(self):
        for text in ("6", "666", "2026", "114514", "5", "0"):
            self.assertIsNone(parse_report(text, self.arcade), text)

    def test_machine_alias_not_at_start_rejects_bare_number(self):
        # tg 只是出现在句中，不构成「机台前缀 + 人数」
        for text in ("wtg2", "打tg2"):
            self.assertIsNone(parse_report(text, self.arcade), text)

    def test_machine_prefix_with_other_text_rejected(self):
        # 机台后面不是纯数字时不放行，避免把「太鼓1号机」当成报卡
        self.assertIsNone(parse_report("太鼓1号机", self.arcade))


class TestMentionPrefix(unittest.TestCase):
    def test_strip_with_qq_id(self):
        self.assertEqual(strip_mention_prefix("@bot(123456) 5k"), "5k")

    def test_strip_plain(self):
        self.assertEqual(strip_mention_prefix("@bot 5k"), "5k")

    def test_strip_bidi_name(self):
        self.assertEqual(
            strip_mention_prefix("@\u2067~\u2067(806845531) 你怎么知道"),
            "你怎么知道",
        )

    def test_strip_name_with_parens(self):
        self.assertEqual(
            strip_mention_prefix("@腱鞘炎我恨你1辈子(接跑图)(3373773885) 教我呗"),
            "教我呗",
        )

    def test_keep_text_without_space(self):
        # 没有空格分隔时不剥离，避免把整段内容吃掉
        self.assertEqual(strip_mention_prefix("@botz1y2"), "@botz1y2")

    def test_plain_text_untouched(self):
        self.assertEqual(strip_mention_prefix("左5"), "左5")
        self.assertEqual(strip_mention_prefix(""), "")


if __name__ == "__main__":
    unittest.main()
"""配置校验单元测试。"""

from __future__ import annotations

import unittest

from .helpers import make_arcade, make_machine
from astrbot_plugin_maimai_card_report.backend.validation import validate_arcade


class TestValidateArcade(unittest.TestCase):
    def test_ok(self):
        self.assertIsNone(validate_arcade(make_arcade(), []))

    def test_empty_name(self):
        self.assertEqual(validate_arcade(make_arcade(name=""), []), "机厅名不能为空")

    def test_name_alias_conflict(self):
        a1 = make_arcade(name="天河城", aliases=["zy"])
        a2 = make_arcade(arcade_id="a_2", name="白云", aliases=["zy"])
        self.assertIn("别名「zy」已被机厅「白云」使用", validate_arcade(a1, [a2]))

    def test_invalid_group_id(self):
        arcade = make_arcade(group_ids=["12"])
        self.assertIn("群号格式无效", validate_arcade(arcade, []))

    def test_normal_range(self):
        arcade = make_arcade(normal_count_min=10, normal_count_max=5)
        self.assertEqual(validate_arcade(arcade, []), "正常卡数下限不能大于上限")

    def test_negative_min(self):
        arcade = make_arcade(normal_count_min=-1)
        self.assertEqual(validate_arcade(arcade, []), "正常卡数下限不能小于 0")

    def test_expire_hours(self):
        arcade = make_arcade(expire_hours=0)
        self.assertEqual(validate_arcade(arcade, []), "过期小时数必须大于 0")

    def test_invalid_time(self):
        arcade = make_arcade(open_time="9:00")
        self.assertEqual(validate_arcade(arcade, []), "开门/闭店时间格式应为 HH:MM")

    def test_open_after_close(self):
        arcade = make_arcade(open_time="22:00", close_time="09:00")
        self.assertEqual(validate_arcade(arcade, []), "开门时间必须早于闭店时间")

    def test_machine_alias_conflict(self):
        arcade = make_arcade(machines={
            "m_1": make_machine(machine_id="m_1", name="舞萌", aliases=["maimai"]),
            "m_2": make_machine(machine_id="m_2", name="中二", aliases=["maimai"]),
        })
        self.assertIn("机台别名", validate_arcade(arcade, []))

    def test_duplicate_default_machine(self):
        arcade = make_arcade(machines={
            "m_1": make_machine(machine_id="m_1", name="舞萌", aliases=["maimai"], is_default=True),
            "m_2": make_machine(machine_id="m_2", name="中二", aliases=["chuni"], is_default=True),
        })
        self.assertEqual(validate_arcade(arcade, []), "默认机台必须唯一")

    def test_empty_position_aliases(self):
        arcade = make_arcade(machines={
            "m_1": make_machine(machine_id="m_1", name="舞萌", position_aliases={}),
        })
        self.assertIn("至少需要一个方位", validate_arcade(arcade, []))

    def test_duplicate_position_label(self):
        arcade = make_arcade(machines={
            "m_1": make_machine(machine_id="m_1", name="舞萌", position_aliases={"z": "左", "y": "左"}),
        })
        self.assertIn("方位显示名「左」重复", validate_arcade(arcade, []))


if __name__ == "__main__":
    unittest.main()
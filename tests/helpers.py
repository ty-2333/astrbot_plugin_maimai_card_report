"""测试辅助：构造机厅 / 事件 / 临时存储等。"""

from __future__ import annotations

import sys
from pathlib import Path

# 让测试可从任意目录运行：将插件包父目录加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from astrbot_plugin_maimai_card_report.backend.models import Arcade, Machine  # noqa: E402
from astrbot_plugin_maimai_card_report.backend.store import PluginStore  # noqa: E402


def make_machine(
    machine_id: str = "m_maimai",
    name: str = "舞萌",
    aliases: list[str] | None = None,
    is_default: bool = True,
    position_aliases: dict[str, str] | None = None,
) -> Machine:
    return Machine(
        id=machine_id,
        name=name,
        aliases=aliases if aliases is not None else ["maimai"],
        is_default=is_default,
        position_aliases=position_aliases if position_aliases is not None else {"z": "左", "y": "右"},
    )


def make_arcade(
    arcade_id: str = "a_1",
    name: str = "天河城",
    aliases: list[str] | None = None,
    group_ids: list[str] | None = None,
    machines: dict[str, Machine] | None = None,
    **kwargs,
) -> Arcade:
    data = dict(
        id=arcade_id,
        name=name,
        aliases=aliases or [],
        group_ids=group_ids or ["111111"],
        normal_count_min=0,
        normal_count_max=20,
        expire_hours=4,
        expire_scope="slot",
    )
    data.update(kwargs)
    data["machines"] = machines or {"m_maimai": make_machine()}
    return Arcade(**data)


class FakeEvent:
    """模拟 AstrBot 群消息事件。"""

    def __init__(
        self,
        text: str,
        group_id: str = "111111",
        sender_id: str = "222222",
        sender_name: str = "测试用户",
    ):
        self._text = text
        self._group_id = group_id
        self._sender_id = sender_id
        self._sender_name = sender_name
        self.unified_msg_origin = "test-session"
        self.stopped = False
        self.reply = None

    def get_group_id(self) -> str:
        return self._group_id

    def get_sender_id(self) -> str:
        return self._sender_id

    def get_sender_name(self) -> str:
        return self._sender_name

    def get_message_str(self) -> str:
        return self._text

    def stop_event(self) -> None:
        self.stopped = True

    def plain_result(self, s: str) -> str:
        self.reply = s
        return s
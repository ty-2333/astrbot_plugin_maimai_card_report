"""核心数据模型：机厅、机台、报卡记录、异常用户、日志、状态。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import (
    DEFAULT_ERROR_MESSAGE_TEMPLATE,
    DEFAULT_EXPIRE_HOURS,
    DEFAULT_EXPIRE_SCOPE,
    DEFAULT_NORMAL_COUNT_MAX,
    DEFAULT_NORMAL_COUNT_MIN,
    DEFAULT_POSITION_ALIASES,
    DEFAULT_POSITION_MODE,
    DEFAULT_TIMEZONE,
)
from ..utils import now_ts


def _float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _str(v: Any, default: str = "") -> str:
    return v if isinstance(v, str) else default


def _list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v]
    return []


def _dict(v: Any) -> dict:
    return dict(v) if isinstance(v, dict) else {}


def _bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(v, (int, float)):
        return bool(v)
    return default


@dataclass
class Machine:
    """机台：舞萌 / 中二 / …"""

    id: str = ""
    name: str = ""
    aliases: list[str] = field(default_factory=list)
    is_default: bool = False
    position_mode: str = DEFAULT_POSITION_MODE
    position_aliases: dict[str, str] = field(default_factory=dict)
    position_count: int = 2

    @property
    def position_keys(self) -> list[str]:
        return list(self.position_aliases.keys())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "aliases": self.aliases,
            "is_default": self.is_default,
            "position_mode": self.position_mode,
            "position_aliases": self.position_aliases,
            "position_count": self.position_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Machine":
        data = data or {}
        position_aliases = _dict(data.get("position_aliases"))
        return cls(
            id=_str(data.get("id")),
            name=_str(data.get("name")),
            aliases=_list(data.get("aliases")),
            is_default=_bool(data.get("is_default")),
            position_mode=_str(data.get("position_mode"), DEFAULT_POSITION_MODE),
            position_aliases=position_aliases,
            position_count=_int(data.get("position_count"), len(position_aliases)),
        )


@dataclass
class Arcade:
    """机厅。"""

    id: str = ""
    name: str = ""
    aliases: list[str] = field(default_factory=list)
    group_ids: list[str] = field(default_factory=list)
    allow_cross_group: bool = False
    open_time: str = ""
    close_time: str = ""
    timezone: str = DEFAULT_TIMEZONE
    open_message_enabled: bool = False
    close_message_enabled: bool = False
    open_prompt_ref: str = ""
    close_prompt_ref: str = ""
    expire_hours: float = DEFAULT_EXPIRE_HOURS
    expire_scope: str = DEFAULT_EXPIRE_SCOPE
    normal_count_min: int = DEFAULT_NORMAL_COUNT_MIN
    normal_count_max: int = DEFAULT_NORMAL_COUNT_MAX
    error_message_template: str = DEFAULT_ERROR_MESSAGE_TEMPLATE
    machines: dict[str, Machine] = field(default_factory=dict)
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "aliases": self.aliases,
            "group_ids": self.group_ids,
            "allow_cross_group": self.allow_cross_group,
            "open_time": self.open_time,
            "close_time": self.close_time,
            "timezone": self.timezone,
            "open_message_enabled": self.open_message_enabled,
            "close_message_enabled": self.close_message_enabled,
            "open_prompt_ref": self.open_prompt_ref,
            "close_prompt_ref": self.close_prompt_ref,
            "expire_hours": self.expire_hours,
            "expire_scope": self.expire_scope,
            "normal_count_min": self.normal_count_min,
            "normal_count_max": self.normal_count_max,
            "error_message_template": self.error_message_template,
            "machines": {k: v.to_dict() for k, v in self.machines.items()},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Arcade":
        data = data or {}
        machines: dict[str, Machine] = {}
        for mid, mdata in _dict(data.get("machines")).items():
            machines[str(mid)] = Machine.from_dict(mdata)
        return cls(
            id=_str(data.get("id")),
            name=_str(data.get("name")),
            aliases=_list(data.get("aliases")),
            group_ids=_list(data.get("group_ids")),
            allow_cross_group=_bool(data.get("allow_cross_group")),
            open_time=_str(data.get("open_time")),
            close_time=_str(data.get("close_time")),
            timezone=_str(data.get("timezone"), DEFAULT_TIMEZONE),
            open_message_enabled=_bool(data.get("open_message_enabled")),
            close_message_enabled=_bool(data.get("close_message_enabled")),
            open_prompt_ref=_str(data.get("open_prompt_ref")),
            close_prompt_ref=_str(data.get("close_prompt_ref")),
            expire_hours=_float(data.get("expire_hours"), DEFAULT_EXPIRE_HOURS),
            expire_scope=_str(data.get("expire_scope"), DEFAULT_EXPIRE_SCOPE),
            normal_count_min=_int(data.get("normal_count_min"), DEFAULT_NORMAL_COUNT_MIN),
            normal_count_max=_int(data.get("normal_count_max"), DEFAULT_NORMAL_COUNT_MAX),
            error_message_template=_str(
                data.get("error_message_template"), DEFAULT_ERROR_MESSAGE_TEMPLATE
            ),
            machines=machines,
            created_at=_float(data.get("created_at")),
            updated_at=_float(data.get("updated_at")),
        )


@dataclass
class CardRecord:
    """报卡记录：按「机厅 + 机台 + 方位」记录。"""

    arcade_id: str = ""
    machine_id: str = ""
    position_key: str = ""
    count: int = 0
    last_update_at: float = 0.0
    last_update_by: str = ""
    updated_group_id: str = ""
    last_clear_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "arcade_id": self.arcade_id,
            "machine_id": self.machine_id,
            "position_key": self.position_key,
            "count": self.count,
            "last_update_at": self.last_update_at,
            "last_update_by": self.last_update_by,
            "updated_group_id": self.updated_group_id,
            "last_clear_at": self.last_clear_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CardRecord":
        data = data or {}
        return cls(
            arcade_id=_str(data.get("arcade_id")),
            machine_id=_str(data.get("machine_id")),
            position_key=_str(data.get("position_key")),
            count=_int(data.get("count")),
            last_update_at=_float(data.get("last_update_at")),
            last_update_by=_str(data.get("last_update_by")),
            updated_group_id=_str(data.get("updated_group_id")),
            last_clear_at=_float(data.get("last_clear_at")),
        )


@dataclass
class AbnormalUser:
    """异常报卡 / 黑名单记录：按「机厅 + QQ」记录。"""

    arcade_id: str = ""
    qq: str = ""
    machine_id: str = ""
    abnormal_count: int = 0
    first_abnormal_at: float = 0.0
    last_abnormal_at: float = 0.0
    last_raw_message: str = ""
    last_abnormal_value: str = ""
    status: str = "warning"  # warning | ignored
    ignored_at: float = 0.0
    source_group_id: str = ""

    def to_dict(self) -> dict:
        return {
            "arcade_id": self.arcade_id,
            "qq": self.qq,
            "machine_id": self.machine_id,
            "abnormal_count": self.abnormal_count,
            "first_abnormal_at": self.first_abnormal_at,
            "last_abnormal_at": self.last_abnormal_at,
            "last_raw_message": self.last_raw_message,
            "last_abnormal_value": self.last_abnormal_value,
            "status": self.status,
            "ignored_at": self.ignored_at,
            "source_group_id": self.source_group_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AbnormalUser":
        data = data or {}
        return cls(
            arcade_id=_str(data.get("arcade_id")),
            qq=_str(data.get("qq")),
            machine_id=_str(data.get("machine_id")),
            abnormal_count=_int(data.get("abnormal_count")),
            first_abnormal_at=_float(data.get("first_abnormal_at")),
            last_abnormal_at=_float(data.get("last_abnormal_at")),
            last_raw_message=_str(data.get("last_raw_message")),
            last_abnormal_value=_str(data.get("last_abnormal_value")),
            status=_str(data.get("status"), "warning"),
            ignored_at=_float(data.get("ignored_at")),
            source_group_id=_str(data.get("source_group_id")),
        )


@dataclass
class LogEntry:
    """运行日志条目。"""

    id: str = ""
    ts: float = 0.0
    level: str = "info"
    group_id: str = ""
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ts": self.ts,
            "level": self.level,
            "group_id": self.group_id,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LogEntry":
        data = data or {}
        return cls(
            id=_str(data.get("id")),
            ts=_float(data.get("ts")),
            level=_str(data.get("level"), "info"),
            group_id=_str(data.get("group_id")),
            message=_str(data.get("message")),
        )


@dataclass
class PluginState:
    """插件运行状态（版本、开门/闭店语已发送标记、群会话映射）。"""

    version: int = 1
    last_open_notice: dict[str, str] = field(default_factory=dict)
    last_close_notice: dict[str, str] = field(default_factory=dict)
    group_sessions: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "last_open_notice": self.last_open_notice,
            "last_close_notice": self.last_close_notice,
            "group_sessions": self.group_sessions,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PluginState":
        data = data or {}
        return cls(
            version=_int(data.get("version"), 1),
            last_open_notice=_dict(data.get("last_open_notice")),
            last_close_notice=_dict(data.get("last_close_notice")),
            group_sessions=_dict(data.get("group_sessions")),
        )


def new_machine(name: str = "", position_mode: str = DEFAULT_POSITION_MODE) -> Machine:
    from ..utils import new_id

    aliases = DEFAULT_POSITION_ALIASES.get(position_mode, {})
    return Machine(
        id=new_id("m_"),
        name=name,
        position_mode=position_mode,
        position_aliases=dict(aliases),
        position_count=len(aliases),
    )


def new_arcade(name: str = "", expire_hours: float = DEFAULT_EXPIRE_HOURS) -> Arcade:
    from ..utils import new_id

    return Arcade(
        id=new_id("a_"),
        name=name,
        expire_hours=expire_hours,
        created_at=now_ts(),
        updated_at=now_ts(),
    )
"""数据持久化：负责所有 JSON 文件的加载、保存与并发安全读写。"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from ..config import (
    DATA_FILE_ABNORMAL,
    DATA_FILE_ARCADES,
    DATA_FILE_LOGS,
    DATA_FILE_RECORDS,
    DATA_FILE_STATE,
    PLUGIN_NAME,
)
from ..log import logger
from ..utils import new_id, now_ts
from .models import AbnormalUser, Arcade, CardRecord, LogEntry, PluginState


DEFAULT_LOG_LEVEL = "info"
DEFAULT_LOG_MAX_ENTRIES = 1000
LOG_LEVEL_ORDER = {"debug": 10, "info": 20, "warn": 30, "warning": 30, "error": 40}


class PluginStore:
    """插件数据仓库。"""

    def __init__(
        self,
        data_dir: Path,
        log_level: str = DEFAULT_LOG_LEVEL,
        log_max_entries: int = DEFAULT_LOG_MAX_ENTRIES,
    ):
        self.data_dir = Path(data_dir)
        self._lock = threading.RLock()
        self.log_level = self._normalize_level(log_level)
        self.log_max_entries = max(100, int(log_max_entries or DEFAULT_LOG_MAX_ENTRIES))
        self.arcades: dict[str, Arcade] = {}
        self.records: dict[tuple[str, str, str], CardRecord] = {}
        self.abnormal: dict[tuple[str, str], AbnormalUser] = {}
        self.logs: list[LogEntry] = []
        self.state: PluginState = PluginState()
        self._load_all()
        logger.info(
            f"[{PLUGIN_NAME}] 数据加载完成 data_dir={self.data_dir} "
            f"arcades={len(self.arcades)} records={len(self.records)} "
            f"abnormal={len(self.abnormal)} logs={len(self.logs)}"
        )

    # —— 文件读写 ——
    @staticmethod
    def _normalize_level(level: str | None) -> str:
        value = str(level or DEFAULT_LOG_LEVEL).strip().lower()
        return value if value in LOG_LEVEL_ORDER else DEFAULT_LOG_LEVEL

    def set_log_options(
        self, level: str | None = None, max_entries: int | None = None
    ) -> None:
        """运行时调整日志级别与保留条数（面板配置变更后调用）。"""
        with self._lock:
            if level:
                self.log_level = self._normalize_level(level)
            if max_entries:
                self.log_max_entries = max(100, int(max_entries))
            if len(self.logs) > self.log_max_entries:
                self.logs = self.logs[-self.log_max_entries :]
                self.save_logs()

    def _path(self, filename: str) -> Path:
        return self.data_dir / filename

    def _load_json(self, filename: str) -> Any:
        path = self._path(filename)
        if not path.exists():
            return None
        try:
            with path.open(encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            logger.error(
                f"[{PLUGIN_NAME}] 读取 JSON 失败，将按空数据处理 path={path}",
                exc_info=True,
            )
            return None

    def _save_json(self, filename: str, data: Any) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self._path(filename)
        tmp = path.with_suffix(".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception:
            logger.error(
                f"[{PLUGIN_NAME}] 保存 JSON 失败 path={path}",
                exc_info=True,
            )
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise

    def _load_all(self) -> None:
        with self._lock:
            raw_arcades = self._load_json(DATA_FILE_ARCADES) or {}
            if isinstance(raw_arcades, list):  # 兼容旧格式
                raw_arcades = {a.get("id", ""): a for a in raw_arcades if a.get("id")}
            self.arcades = {
                str(k): Arcade.from_dict(v) for k, v in raw_arcades.items()
            }

            raw_records = self._load_json(DATA_FILE_RECORDS) or []
            if isinstance(raw_records, list):
                self.records = {}
                for item in raw_records:
                    rec = CardRecord.from_dict(item)
                    key = (rec.arcade_id, rec.machine_id, rec.position_key)
                    if key[0] and key[1] and key[2]:
                        self.records[key] = rec

            raw_abnormal = self._load_json(DATA_FILE_ABNORMAL) or []
            if isinstance(raw_abnormal, list):
                self.abnormal = {}
                for item in raw_abnormal:
                    u = AbnormalUser.from_dict(item)
                    key = (u.arcade_id, u.qq)
                    if key[0] and key[1]:
                        self.abnormal[key] = u

            raw_logs = self._load_json(DATA_FILE_LOGS) or []
            if isinstance(raw_logs, list):
                self.logs = [LogEntry.from_dict(x) for x in raw_logs][
                    -self.log_max_entries :
                ]

            raw_state = self._load_json(DATA_FILE_STATE) or {}
            self.state = PluginState.from_dict(raw_state)
            self.prune_group_sessions()

    # —— 机厅 ——
    def save_arcades(self) -> None:
        with self._lock:
            self._save_json(
                DATA_FILE_ARCADES, {k: v.to_dict() for k, v in self.arcades.items()}
            )

    def get_arcade(self, arcade_id: str) -> Arcade | None:
        with self._lock:
            return self.arcades.get(arcade_id)

    def list_arcades(self) -> list[Arcade]:
        with self._lock:
            return list(self.arcades.values())

    def upsert_arcade(self, arcade: Arcade) -> None:
        with self._lock:
            self.arcades[arcade.id] = arcade
            self.save_arcades()

    def delete_arcade(self, arcade_id: str) -> None:
        with self._lock:
            self.arcades.pop(arcade_id, None)
            self.save_arcades()
            # 级联清理
            for key in list(self.records.keys()):
                if key[0] == arcade_id:
                    del self.records[key]
            for key in list(self.abnormal.keys()):
                if key[0] == arcade_id:
                    del self.abnormal[key]
            self.save_records()
            self.save_abnormal()

    # —— 报卡记录 ——
    @staticmethod
    def _record_key(arcade_id: str, machine_id: str, position_key: str) -> tuple[str, str, str]:
        return (arcade_id, machine_id, position_key)

    def get_record(self, arcade_id: str, machine_id: str, position_key: str) -> CardRecord | None:
        with self._lock:
            return self.records.get(self._record_key(arcade_id, machine_id, position_key))

    def set_record(self, record: CardRecord) -> None:
        with self._lock:
            self.records[
                self._record_key(record.arcade_id, record.machine_id, record.position_key)
            ] = record

    def save_records(self) -> None:
        with self._lock:
            self._save_json(
                DATA_FILE_RECORDS, [r.to_dict() for r in self.records.values()]
            )

    def machine_records(self, arcade_id: str, machine_id: str) -> list[CardRecord]:
        with self._lock:
            return [
                r
                for (a, m, _), r in self.records.items()
                if a == arcade_id and m == machine_id
            ]

    def clear_machine_records(self, arcade_id: str, machine_id: str) -> None:
        with self._lock:
            for key in list(self.records.keys()):
                if key[0] == arcade_id and key[1] == machine_id:
                    del self.records[key]
            self.save_records()

    # —— 异常 / 黑名单 ——
    def get_abnormal(self, arcade_id: str, qq: str) -> AbnormalUser | None:
        with self._lock:
            return self.abnormal.get((arcade_id, qq))

    def set_abnormal(self, user: AbnormalUser) -> None:
        with self._lock:
            self.abnormal[(user.arcade_id, user.qq)] = user

    def delete_abnormal(self, arcade_id: str, qq: str) -> None:
        with self._lock:
            self.abnormal.pop((arcade_id, qq), None)
            self.save_abnormal()

    def list_abnormal(self) -> list[AbnormalUser]:
        with self._lock:
            return list(self.abnormal.values())

    def clear_machine_abnormal(self, arcade_id: str, machine_id: str) -> None:
        with self._lock:
            removed = False
            for key, u in list(self.abnormal.items()):
                if key[0] == arcade_id and u.machine_id == machine_id:
                    del self.abnormal[key]
                    removed = True
            if removed:
                self.save_abnormal()

    def clear_arcade_abnormal(self, arcade_id: str) -> None:
        with self._lock:
            removed = False
            for key in list(self.abnormal.keys()):
                if key[0] == arcade_id:
                    del self.abnormal[key]
                    removed = True
            if removed:
                self.save_abnormal()

    def save_abnormal(self) -> None:
        with self._lock:
            self._save_json(
                DATA_FILE_ABNORMAL, [u.to_dict() for u in self.abnormal.values()]
            )

    # —— 日志 ——
    def add_log(self, level: str, group_id: str, message: str) -> None:
        level = (level or "info").lower()
        if LOG_LEVEL_ORDER.get(level, 20) < LOG_LEVEL_ORDER.get(self.log_level, 20):
            return
        with self._lock:
            entry = LogEntry(id=new_id("l_"), ts=now_ts(), level=level, group_id=group_id, message=message)
            self.logs.append(entry)
            if len(self.logs) > self.log_max_entries:
                self.logs = self.logs[-self.log_max_entries :]
            self.save_logs()

    def list_logs(self, limit: int = 200) -> list[LogEntry]:
        with self._lock:
            return list(reversed(self.logs[-limit:]))

    def save_logs(self) -> None:
        with self._lock:
            self._save_json(DATA_FILE_LOGS, [x.to_dict() for x in self.logs])

    # —— 状态 ——
    def save_state(self) -> None:
        with self._lock:
            self._save_json(DATA_FILE_STATE, self.state.to_dict())

    def prune_group_sessions(self) -> int:
        """移除已不再绑定任何机厅的群会话映射，返回清理条数。

        群会话只用于开门/闭店语主动发送，解绑后的群保留映射没有意义，
        长期累积会让 state.json 越来越大。
        """
        with self._lock:
            bound = {
                gid
                for arcade in self.arcades.values()
                for gid in arcade.group_ids
                if gid
            }
            stale = [gid for gid in self.state.group_sessions if gid not in bound]
            for gid in stale:
                del self.state.group_sessions[gid]
            if stale:
                self.save_state()
                logger.info(
                    f"[{PLUGIN_NAME}] 清理已解绑群的会话映射 {len(stale)} 条：{stale}"
                )
            return len(stale)
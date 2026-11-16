"""Web API Mixin：为 WebUI 页面注册后端 REST 接口。"""

from __future__ import annotations

import time

from quart import jsonify, request

from ..backend.models import Arcade, CardRecord
from ..backend.parser import (
    first_position_key,
    is_query,
    looks_like_report_attempt,
    match_arcade,
    parse_query,
    parse_report,
)
from ..backend.validation import validate_arcade
from ..config import PLUGIN_NAME
from ..log import logger
from ..utils import new_id, normalize_text, now_ts, strip_mention_prefix

WEBUI_LOG_PREFIX = f"[{PLUGIN_NAME}][WebUI]"


class WebAPIMixin:
    """包含所有 WebUI 仪表盘 API 的注册与处理逻辑。"""

    # ---------- 注册辅助 ----------

    def _register_webui_api(self, route, handler, methods, desc):
        route_path = f"/{PLUGIN_NAME}/{route.strip('/')}"

        async def logged_handler(*args, **kwargs):
            started_at = time.monotonic()
            logger.info(
                f"{WEBUI_LOG_PREFIX} {request.method} {route_path} 开始"
                f" path_params={kwargs if kwargs else None}"
            )
            try:
                response = await handler(*args, **kwargs)
            except Exception:
                elapsed_ms = int((time.monotonic() - started_at) * 1000)
                logger.error(
                    f"{WEBUI_LOG_PREFIX} {request.method} {route_path} 失败 "
                    f"耗时={elapsed_ms}ms",
                    exc_info=True,
                )
                return jsonify({"ok": False, "message": "服务器内部错误"}), 500

            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            status_code = (
                response[1]
                if isinstance(response, tuple) and len(response) > 1
                else getattr(response, "status_code", "unknown")
            )
            log_line = (
                f"{WEBUI_LOG_PREFIX} {request.method} {route_path} 完成 "
                f"状态={status_code} 耗时={elapsed_ms}ms"
            )
            if isinstance(status_code, int) and status_code >= 500:
                logger.error(log_line)
            elif isinstance(status_code, int) and status_code >= 400:
                logger.warning(log_line)
            else:
                logger.info(log_line)
            return response

        logged_handler.__name__ = f"webui_{handler.__name__}"
        self.context.register_web_api(route_path, logged_handler, methods, desc)

    def _register_web_apis(self):
        self._register_webui_api("dashboard", self._api_dashboard, ["GET"], "看板汇总")
        self._register_webui_api("arcades", self._api_list_arcades, ["GET"], "机厅列表")
        self._register_webui_api("arcades", self._api_save_arcade, ["POST"], "新建/更新机厅")
        self._register_webui_api(
            "arcades/delete", self._api_delete_arcade, ["POST"], "删除机厅"
        )
        self._register_webui_api(
            "arcades/<arcade_id>/clear", self._api_clear_arcade, ["POST"], "清零排卡"
        )
        self._register_webui_api(
            "records/<arcade_id>", self._api_arcade_records, ["GET"], "机厅排卡明细"
        )
        self._register_webui_api(
            "records/<arcade_id>/set", self._api_set_record, ["POST"], "面板修改人数"
        )
        self._register_webui_api("parse", self._api_parse, ["POST"], "消息解析测试")
        self._register_webui_api("abnormal", self._api_list_abnormal, ["GET"], "黑名单列表")
        self._register_webui_api(
            "abnormal/remove", self._api_remove_abnormal, ["POST"], "移除黑名单"
        )
        self._register_webui_api("abnormal/clear", self._api_clear_abnormal, ["POST"], "清空黑名单")
        self._register_webui_api("logs", self._api_logs, ["GET"], "运行日志")
        self._register_webui_api("validate", self._api_validate, ["POST"], "校验机厅配置")

    # ---------- 数据构建 ----------

    @staticmethod
    def _arcade_from_payload(payload: dict, existing: Arcade | None = None) -> Arcade:
        data = dict(payload or {})
        machines_data = data.get("machines", {})
        if isinstance(machines_data, list):
            machines: dict[str, dict] = {}
            for m in machines_data:
                m = dict(m)
                mid = str(m.get("id") or "").strip() or new_id("m_")
                m["id"] = mid
                machines[mid] = m
            data["machines"] = machines

        arcade = Arcade.from_dict(data)
        if existing is not None:
            arcade.id = existing.id
            arcade.created_at = existing.created_at
        else:
            if not arcade.id:
                arcade.id = new_id("a_")
            if not arcade.created_at:
                arcade.created_at = now_ts()
        arcade.updated_at = now_ts()

        for machine in arcade.machines.values():
            machine.position_count = len(machine.position_aliases)
        return arcade

    # ---------- 处理器 ----------

    async def _api_dashboard(self):
        data = {
            "arcades": [],
            "abnormal_count": len(self.store.list_abnormal()),
            "log_count": len(self.store.logs),
        }
        for arcade in self.store.list_arcades():
            summary = {
                "id": arcade.id,
                "name": arcade.name,
                "aliases": arcade.aliases,
                "group_ids": arcade.group_ids,
                "expire_hours": arcade.expire_hours,
                "expire_scope": arcade.expire_scope,
                "normal_count_min": arcade.normal_count_min,
                "normal_count_max": arcade.normal_count_max,
                "machines": [],
            }
            for machine in arcade.machines.values():
                self.service.lazy_clear_machine(arcade, machine)
                positions = []
                for pos_key in machine.position_keys:
                    rec = self.store.get_record(arcade.id, machine.id, pos_key)
                    expire_at = self.service.record_expire_at(arcade, machine, rec) if rec else 0
                    positions.append(
                        {
                            "key": pos_key,
                            "label": machine.position_aliases.get(pos_key, pos_key),
                            "count": rec.count if rec else 0,
                            "last_update_at": rec.last_update_at if rec else 0,
                            "last_clear_at": rec.last_clear_at if rec else 0,
                            "expire_at": expire_at,
                        }
                    )
                summary["machines"].append(
                    {
                        "id": machine.id,
                        "name": machine.name,
                        "is_default": machine.is_default,
                        "positions": positions,
                    }
                )
            data["arcades"].append(summary)
        return jsonify({"ok": True, "data": data})

    async def _api_list_arcades(self):
        data = [a.to_dict() for a in self.store.list_arcades()]
        return jsonify({"ok": True, "data": data})

    async def _api_save_arcade(self):
        payload = await request.get_json() or {}
        existing_id = str(payload.get("arcade_id") or "").strip()
        existing = self.store.get_arcade(existing_id) if existing_id else None
        arcade = self._arcade_from_payload(payload, existing)
        err = validate_arcade(arcade, self.store.list_arcades(), exclude_id=existing_id or None)
        if err:
            return jsonify({"ok": False, "message": err})
        self.store.upsert_arcade(arcade)
        # 群绑定可能变化，顺手清理已解绑群的会话映射
        self.store.prune_group_sessions()
        self.store.add_log("info", "", f"保存机厅 {arcade.name}")
        return jsonify({"ok": True, "data": arcade.to_dict()})

    async def _api_delete_arcade(self):
        payload = await request.get_json() or {}
        arcade_id = str(payload.get("arcade_id") or "").strip()
        arcade = self.store.get_arcade(arcade_id)
        if arcade is None:
            return jsonify({"ok": False, "message": "机厅不存在"}), 404
        self.store.delete_arcade(arcade_id)
        self.store.prune_group_sessions()
        self.store.add_log("info", "", f"删除机厅 {arcade.name}")
        return jsonify({"ok": True})

    async def _api_clear_arcade(self, arcade_id):
        arcade = self.store.get_arcade(arcade_id)
        if arcade is None:
            return jsonify({"ok": False, "message": "机厅不存在"}), 404
        payload = await request.get_json() or {}
        machine_id = str(payload.get("machine_id") or "").strip()
        position_key = str(payload.get("position_key") or "").strip()

        now = now_ts()
        if machine_id:
            recs = self.store.machine_records(arcade_id, machine_id)
        else:
            recs = [r for r in self.store.records.values() if r.arcade_id == arcade_id]
        for rec in recs:
            if position_key and rec.position_key != position_key:
                continue
            if rec.count > 0:
                rec.count = 0
                rec.last_clear_at = now
                self.store.set_record(rec)
        self.store.save_records()

        # 清零同时清除相关黑名单 / 异常计数
        if machine_id:
            self.store.clear_machine_abnormal(arcade_id, machine_id)
        else:
            self.store.clear_arcade_abnormal(arcade_id)

        self.store.add_log("info", "", f"手动清零机厅 {arcade.name}")
        return jsonify({"ok": True})

    async def _api_arcade_records(self, arcade_id):
        arcade = self.store.get_arcade(arcade_id)
        if arcade is None:
            return jsonify({"ok": False, "message": "机厅不存在"}), 404
        for machine in arcade.machines.values():
            self.service.lazy_clear_machine(arcade, machine)
        data = []
        for machine in arcade.machines.values():
            positions = []
            for pos_key in machine.position_keys:
                rec = self.store.get_record(arcade_id, machine.id, pos_key)
                positions.append(
                    {
                        "key": pos_key,
                        "label": machine.position_aliases.get(pos_key, pos_key),
                        "count": rec.count if rec else 0,
                        "last_update_at": rec.last_update_at if rec else 0,
                        "last_update_by": rec.last_update_by if rec else "",
                    }
                )
            data.append({"id": machine.id, "name": machine.name, "positions": positions})
        return jsonify({"ok": True, "data": data})

    async def _api_set_record(self, arcade_id):
        arcade = self.store.get_arcade(arcade_id)
        if arcade is None:
            return jsonify({"ok": False, "message": "机厅不存在"}), 404
        payload = await request.get_json() or {}
        machine_id = str(payload.get("machine_id") or "").strip()
        position_key = str(payload.get("position_key") or "").strip()
        machine = arcade.machines.get(machine_id)
        if machine is None:
            return jsonify({"ok": False, "message": "机台不存在"}), 404
        if position_key not in machine.position_aliases:
            return jsonify({"ok": False, "message": "方位不存在"}), 404
        try:
            count = int(payload.get("count"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "message": "人数必须为整数"}), 400
        if count < arcade.normal_count_min or count > arcade.normal_count_max:
            return jsonify(
                {
                    "ok": False,
                    "message": f"人数超出正常范围（{arcade.normal_count_min}-{arcade.normal_count_max}）",
                }
            ), 400

        now = now_ts()
        rec = self.store.get_record(arcade_id, machine_id, position_key)
        if rec is None:
            rec = CardRecord(
                arcade_id=arcade_id, machine_id=machine_id, position_key=position_key
            )
        rec.count = count
        rec.last_update_at = now
        rec.last_update_by = "webui"
        rec.updated_group_id = ""
        self.store.set_record(rec)
        self.store.save_records()
        self.store.add_log(
            "info", "", f"面板修改 {arcade.name}/{machine.name}/{position_key} 人数为 {count}"
        )
        return jsonify({"ok": True, "data": rec.to_dict()})

    async def _api_parse(self):
        payload = await request.get_json() or {}
        text = str(payload.get("text") or "").strip()
        group_id = str(payload.get("group_id") or "").strip()
        if not text:
            return jsonify({"ok": False, "message": "请输入消息文本"}), 400

        normalized = strip_mention_prefix(normalize_text(text))
        result = {
            "normalized": normalized,
            "matched_arcade": None,
            "ambiguous": False,
            "is_query": False,
            "report": None,
            "unparseable_attempt": False,
            "message": "",
        }

        arcades = self.store.list_arcades()
        matched = match_arcade(normalized, arcades)
        arcade: Arcade | None = None
        rest = normalized
        if matched:
            arcade, rest = matched
            result["matched_arcade"] = {"id": arcade.id, "name": arcade.name}
        else:
            bound = [a for a in arcades if group_id and group_id in a.group_ids]
            if len(bound) == 1:
                arcade = bound[0]
            elif len(bound) > 1:
                result["ambiguous"] = True
                result["message"] = "该群绑定多个机厅，请用机厅别名指定"
                return jsonify({"ok": True, "data": result})

        if arcade is None:
            result["message"] = "未匹配到机厅（未绑定群或未指定机厅别名）"
            return jsonify({"ok": True, "data": result})

        if is_query(rest):
            result["is_query"] = True
            q = parse_query(rest, arcade)
            if q is not None:
                machines = list(arcade.machines.values()) if q.machine is None else [q.machine]
                reports = []
                for machine in machines:
                    self.service.lazy_clear_machine(arcade, machine)
                    positions = []
                    for pos_key in machine.position_keys:
                        rec = self.store.get_record(arcade.id, machine.id, pos_key)
                        positions.append(
                            {
                                "key": pos_key,
                                "label": machine.position_aliases.get(pos_key, pos_key),
                                "count": rec.count if rec else 0,
                            }
                        )
                    reports.append(
                        {
                            "machine": machine.name,
                            "machine_id": machine.id,
                            "positions": positions,
                        }
                    )
                result["report"] = {"machines": reports}
            return jsonify({"ok": True, "data": result})

        parsed = parse_report(rest, arcade)
        if parsed is None:
            result["unparseable_attempt"] = looks_like_report_attempt(rest, arcade)
            if result["unparseable_attempt"]:
                result["message"] = "识别为一次失败的报卡尝试（格式异常）"
            else:
                result["message"] = "未识别为报卡"
            return jsonify({"ok": True, "data": result})

        entries = []
        for e in parsed.entries:
            pos_key = e.position_key or first_position_key(parsed.machine)
            entries.append(
                {
                    "position_key": pos_key,
                    "label": parsed.machine.position_aliases.get(pos_key, pos_key)
                    if pos_key
                    else "",
                    "count": e.count,
                    "increment": e.increment,
                    "decrement": e.decrement,
                }
            )
        result["report"] = {
            "machine": parsed.machine.name,
            "machine_id": parsed.machine.id,
            "entries": entries,
        }
        result["message"] = "识别成功"
        return jsonify({"ok": True, "data": result})

    async def _api_list_abnormal(self):
        names = {a.id: a.name for a in self.store.list_arcades()}
        machine_names: dict[tuple[str, str], str] = {}
        for a in self.store.list_arcades():
            for m in a.machines.values():
                machine_names[(a.id, m.id)] = m.name
        data = []
        for u in self.store.list_abnormal():
            data.append(
                {
                    "arcade_id": u.arcade_id,
                    "arcade_name": names.get(u.arcade_id, ""),
                    "qq": u.qq,
                    "machine_id": u.machine_id,
                    "machine_name": machine_names.get((u.arcade_id, u.machine_id), ""),
                    "abnormal_count": u.abnormal_count,
                    "first_abnormal_at": u.first_abnormal_at,
                    "last_abnormal_at": u.last_abnormal_at,
                    "last_raw_message": u.last_raw_message,
                    "last_abnormal_value": u.last_abnormal_value,
                    "status": u.status,
                    "ignored_at": u.ignored_at,
                    "source_group_id": u.source_group_id,
                }
            )
        return jsonify({"ok": True, "data": data})

    async def _api_remove_abnormal(self):
        payload = await request.get_json() or {}
        arcade_id = str(payload.get("arcade_id") or "").strip()
        qq = str(payload.get("qq") or "").strip()
        if not arcade_id or not qq:
            return jsonify({"ok": False, "message": "缺少参数"}), 400
        self.store.delete_abnormal(arcade_id, qq)
        self.store.add_log("info", "", f"移除黑名单 {arcade_id}/{qq}")
        return jsonify({"ok": True})

    async def _api_clear_abnormal(self):
        payload = await request.get_json() or {}
        arcade_id = str(payload.get("arcade_id") or "").strip()
        if arcade_id:
            for key in list(self.store.abnormal.keys()):
                if key[0] == arcade_id:
                    del self.store.abnormal[key]
        else:
            self.store.abnormal.clear()
        self.store.save_abnormal()
        self.store.add_log("info", "", "清空黑名单")
        return jsonify({"ok": True})

    async def _api_logs(self):
        try:
            limit = int(request.args.get("limit", 100))
        except ValueError:
            limit = 100
        data = [x.to_dict() for x in self.store.list_logs(limit)]
        return jsonify({"ok": True, "data": data})

    async def _api_validate(self):
        payload = await request.get_json() or {}
        arcade = self._arcade_from_payload(payload)
        err = validate_arcade(arcade, self.store.list_arcades(), exclude_id=arcade.id or None)
        if err:
            return jsonify({"ok": False, "message": err})
        return jsonify({"ok": True})
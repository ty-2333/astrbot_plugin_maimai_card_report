"""业务逻辑层：报卡更新、查询回复、超时清零、异常过滤、黑名单、开关门语。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from ..config import (
    ABNORMAL_UNPARSEABLE,
    DEFAULT_ERROR_MESSAGE_TEMPLATE,
    DEFAULT_TIMEZONE,
    HELP_CONTAINS,
    HELP_EXACT,
    PLUGIN_NAME,
)
from ..log import logger
from ..utils import format_time, normalize_text, now_ts, strip_mention_prefix
from .models import AbnormalUser, Arcade, CardRecord, Machine
from .parser import (
    default_machine,
    first_position_key,
    is_query,
    looks_like_report_attempt,
    match_arcade,
    parse_query,
    parse_report,
)
from .store import PluginStore

# 开门/闭店语过点后的补发窗口（秒）。定时任务每 30 秒检查一次，
# 5 分钟窗口足以覆盖插件重载、短暂掉线等「错过整分钟」的情况。
NOTICE_CATCHUP_SECONDS = 300


@dataclass
class EventOutcome:
    """处理一次群消息后的结果。"""

    reply: str | None
    should_stop: bool


@dataclass
class ArcadeResolution:
    """机厅匹配结果。"""

    arcade: Arcade | None
    rest: str
    ambiguous: bool = False


class ReportService:
    """报卡核心业务逻辑，不直接依赖 AstrBot 运行时，便于单元测试。"""

    def __init__(self, store: PluginStore, context=None):
        self.store = store
        self.context = context
        logger.info(
            f"[{PLUGIN_NAME}] 业务服务初始化，数据目录={store.data_dir} "
            f"context={'可用' if context is not None else '不可用（仅本地/测试）'}"
        )

    def log_local(self, level: str, group_id: str, message: str) -> None:
        """把诊断日志同时写入 AstrBot 标准通道与本地 logs.json。

        logs.json 是插件自己的持久化日志，便于在面板「日志」之外排查消息链路问题。
        """
        log = getattr(logger, level, logger.info)
        log(f"[{PLUGIN_NAME}] {message} group={group_id}")
        try:
            self.store.add_log(level, group_id or "", message)
        except Exception:
            logger.warning(
                f"[{PLUGIN_NAME}] 写入本地日志失败 level={level} group={group_id} "
                f"message={message!r}",
                exc_info=True,
            )

    async def _resolve_provider(self):
        """安全获取当前对话模型 Provider，不可用时返回 None。

        ``self.context`` 是 AstrBot 注入的 ``Star`` 上下文（main.py 中
        ``ReportService(self.store, context)``），是插件访问 Core 能力的唯一入口：
        ``get_using_provider_async()`` 取当前对话模型、``send_message()`` 主动推送、
        ``register_web_api()`` 注册面板接口都依赖它。

        可能为空 / 不可用的路径：
        - 单元测试或本地回退时直接 ``ReportService(store, context=None)``；
        - 插件被非 AstrBot 环境复用时没有 Context；
        - 旧版 AstrBot 的 Context 没有 ``get_using_provider_async`` 方法；
        - Provider 管理器尚未就绪或调用本身抛错。

        以上情况统一返回 None，由调用方回退到默认文案，避免异常冒泡。
        """
        context = self.context
        if context is None:
            logger.info(
                f"[{PLUGIN_NAME}] context 不可用（未注入 AstrBot Context），跳过 LLM 调用"
            )
            return None
        getter = getattr(context, "get_using_provider_async", None)
        if not callable(getter):
            logger.warning(
                f"[{PLUGIN_NAME}] context 缺少 get_using_provider_async，跳过 LLM 调用"
            )
            return None
        try:
            return await getter()
        except Exception:  # noqa: BLE001
            logger.error(f"[{PLUGIN_NAME}] 获取 LLM Provider 失败", exc_info=True)
            return None

    # ---------- 机厅匹配 ----------

    def resolve_arcade(self, text: str, group_id: str) -> ArcadeResolution:
        """根据文本与群号解析目标机厅。"""
        arcades = self.store.list_arcades()
        matched = match_arcade(text, arcades)
        if matched:
            arcade, rest = matched
            if group_id in arcade.group_ids or arcade.allow_cross_group:
                return ArcadeResolution(arcade, rest)
            return ArcadeResolution(None, text)

        bound = [a for a in arcades if group_id and group_id in a.group_ids]
        if len(bound) == 1:
            return ArcadeResolution(bound[0], text)
        if len(bound) > 1:
            return ArcadeResolution(None, text, ambiguous=True)
        return ArcadeResolution(None, text)

    def is_managed_group(self, group_id: str) -> bool:
        """判断群号是否已被任意机厅绑定（仅处理已在机厅管理添加的群）。"""
        if not group_id:
            return False
        return any(group_id in a.group_ids for a in self.store.list_arcades())

    # ---------- 帮助 ----------

    def is_help_request(self, text: str) -> bool:
        """判断归一化后的文本是否为 help 请求。

        整句命中 ``HELP_EXACT`` 直接返回；包含词里英文按「独立单词」匹配，
        所以 ``help``、``help me`` 会触发，``helped`` / ``helper`` / ``helpful``
        不会；中文没有词边界，仍按子串匹配。
        """
        t = text.strip()
        if not t:
            return False
        if t in HELP_EXACT:
            return True
        for keyword in HELP_CONTAINS:
            if keyword.isascii():
                if re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", t):
                    return True
            elif keyword in t:
                return True
        return False

    @staticmethod
    def help_hint() -> str:
        return "发送「help」或「帮助」查看规范报卡格式与示例。"

    def build_help(self, arcade: Arcade | None = None) -> str:
        """生成规范报卡说明与示例；传入机厅时附加其机台 / 方位 / 别名。"""
        lines = [
            "【舞萌报卡】使用说明",
            "报卡（覆盖人数）：",
            "  z3y5 / 3z5y / 左3右5   左 3 右 5",
            "  5k / 5卡 / 5人          默认方位 5 人（裸数字不算）",
            "  内1外2                  内外机台方位",
            "累加报卡（当前人数上加）：",
            "  z+1y5   左累加 1、右 5",
            "  +1k / 左+2   默认方位 / 指定方位累加",
            "扣减报卡（当前人数上减，最低到 0）：",
            "  z-1 / 左-2   指定方位扣减",
            "  -1k / -2卡   默认方位扣减",
            "指定机台：机台名/别名 + 报卡，例如「中二z1y2」「tg2」",
            "指定机厅：机厅别名 + 报卡，例如「兆阳5k」",
            "查询排卡：zyjk / 兆阳几卡 / zy?k",
            "注意：单独发送数字（如 6、666）不会报卡；",
            "      但机台前缀后可以跟纯数字，如 tg2 = 太鼓 2 人。",
            "      @机器人 再报卡也可以，开头的 @ 会被忽略。",
        ]
        if arcade is not None:
            lines.append("")
            lines.append(f"当前机厅「{arcade.name}」：")
            arcade_alias = "/".join(arcade.aliases) if arcade.aliases else "无"
            lines.append(f"  机厅别名：{arcade_alias}")
            for machine in arcade.machines.values():
                name = machine.name + ("（默认）" if machine.is_default else "")
                alias = "/".join(machine.aliases) if machine.aliases else "无"
                pos = "/".join(machine.position_aliases.values()) or "无"
                lines.append(f"  · 机台 {name}  别名：{alias}  方位：{pos}")
        lines.append("")
        lines.append("帮助：发送「help」或「帮助」查看本说明。")
        return "\n".join(lines)

    # ---------- 事件入口 ----------

    async def handle_event(self, event) -> EventOutcome:
        """处理一条群消息。event 需提供 get_group_id / get_sender_id 等接口。"""
        group_id = event.get_group_id()
        sender_id = event.get_sender_id()
        if not group_id:
            self.log_local("debug", "", f"消息缺少群号，跳过 sender={sender_id}")
            return EventOutcome(None, False)

        origin = getattr(event, "unified_msg_origin", None)
        if origin and self.store.state.group_sessions.get(group_id) != origin:
            self.store.state.group_sessions[group_id] = origin
            self.store.save_state()
            logger.info(f"[{PLUGIN_NAME}] 更新群会话映射 group={group_id} origin={origin}")

        text = normalize_text(event.get_message_str())
        text = strip_mention_prefix(text)
        if not text:
            self.log_local("debug", group_id, f"归一化后文本为空，跳过 sender={sender_id}")
            return EventOutcome(None, False)

        if self.is_help_request(text):
            hint_arcade = self.resolve_arcade(text, group_id).arcade
            self.log_local(
                "info",
                group_id,
                f"命中帮助请求 sender={sender_id} "
                f"hint_arcade={hint_arcade.name if hint_arcade else None}",
            )
            return EventOutcome(self.build_help(hint_arcade), True)

        resolution = self.resolve_arcade(text, group_id)
        if resolution.ambiguous:
            self.log_local(
                "info",
                group_id,
                f"机厅歧义 sender={sender_id} text={text!r}",
            )
            return EventOutcome("检测到多个机厅绑定，请用机厅别名指定，例如：zy5k。", True)

        arcade = resolution.arcade
        if arcade is None:
            self.log_local(
                "debug",
                group_id,
                f"未匹配机厅，跳过 sender={sender_id} text={text!r}",
            )
            return EventOutcome(None, False)

        rest = resolution.rest
        if is_query(rest):
            self.log_local(
                "info",
                group_id,
                f"命中查询 arcade={arcade.name} rest={rest!r}",
            )
            reply = self.handle_query(arcade, rest, event)
            if reply:
                return EventOutcome(reply, True)
            return EventOutcome(None, False)

        return await self.handle_report(arcade, rest, event)

    # ---------- 报卡 ----------

    async def handle_report(self, arcade: Arcade, rest: str, event) -> EventOutcome:
        qq = event.get_sender_id()
        group_id = event.get_group_id()
        parsed = parse_report(rest, arcade)
        is_attempt = parsed is None and looks_like_report_attempt(rest, arcade)

        if parsed is None and not is_attempt:
            self.log_local(
                "debug",
                group_id,
                f"未识别为报卡/查询 arcade={arcade.name} rest={rest!r}",
            )
            return EventOutcome(None, False)

        # 黑名单：无论报卡正常与否，均静默忽略
        user = self.store.get_abnormal(arcade.id, qq)
        if user and user.status == "ignored":
            logger.info(
                f"[{PLUGIN_NAME}] 黑名单静默忽略 arcade={arcade.name} qq={qq} rest={rest!r}"
            )
            return EventOutcome(None, True)

        if parsed is None:
            # 格式异常（无法解析）
            machine = default_machine(arcade)
            if machine is None:
                logger.warning(
                    f"[{PLUGIN_NAME}] 报卡无法解析且无机台 arcade={arcade.name} rest={rest!r}"
                )
                return EventOutcome(None, False)
            return await self.handle_abnormal(arcade, machine, "无法解析", event, "格式异常")

        # 校验并计算目标人数
        updates: list[tuple[str, int]] = []
        for entry in parsed.entries:
            pos_key = entry.position_key
            if pos_key is None:
                pos_key = first_position_key(parsed.machine)
            if pos_key is None:
                continue
            old = self.store.get_record(arcade.id, parsed.machine.id, pos_key)
            old_count = old.count if old else 0
            if entry.decrement:
                # 扣减：在当前人数上减少，最低到 0
                new_count = max(0, old_count - entry.count)
            elif entry.increment:
                new_count = old_count + entry.count
            else:
                new_count = entry.count

            if new_count < arcade.normal_count_min or new_count > arcade.normal_count_max:
                return await self.handle_abnormal(
                    arcade, parsed.machine, new_count, event, "超出正常范围"
                )
            updates.append((pos_key, new_count))

        if not updates:
            logger.warning(
                f"[{PLUGIN_NAME}] 报卡解析成功但无有效更新 arcade={arcade.name} "
                f"machine={parsed.machine.name} rest={rest!r}"
            )
            return EventOutcome(None, False)

        now = now_ts()
        written = 0
        for pos_key, new_count in updates:
            rec = self.store.get_record(arcade.id, parsed.machine.id, pos_key)
            # 数值未变化时不刷新「更新于」时间，避免无意义的扣减/覆盖
            # 把已清零的记录显示成刚更新过。
            if (rec.count if rec else 0) == new_count:
                continue
            if rec is None:
                rec = CardRecord(
                    arcade_id=arcade.id,
                    machine_id=parsed.machine.id,
                    position_key=pos_key,
                )
            rec.count = new_count
            rec.last_update_at = now
            rec.last_update_by = qq
            rec.updated_group_id = group_id
            rec.last_clear_at = 0.0
            self.store.set_record(rec)
            written += 1
        if written:
            self.store.save_records()

        detail = " ".join(f"{parsed.machine.position_aliases.get(k, k)}:{v}" for k, v in updates)
        logger.info(
            f"[{PLUGIN_NAME}] 报卡成功 arcade={arcade.name} machine={parsed.machine.name} "
            f"qq={qq} group={group_id} updates={detail} written={written}"
        )
        self.store.add_log("info", group_id, f"报卡 {arcade.name}/{parsed.machine.name} 由 {qq} 更新")
        return EventOutcome(self.build_confirm(arcade, parsed.machine, updates), True)

    def build_confirm(self, arcade: Arcade, machine: Machine, updates: list[tuple[str, int]]) -> str:
        parts = []
        for pos_key, new_count in updates:
            label = machine.position_aliases.get(pos_key, pos_key)
            parts.append(f"{label}:{new_count}")
        return f"{arcade.name} {machine.name} {' '.join(parts)}"

    # ---------- 异常处理 ----------

    async def handle_abnormal(
        self,
        arcade: Arcade,
        machine: Machine,
        value,
        event,
        reason: str,
    ) -> EventOutcome:
        qq = event.get_sender_id()
        group_id = event.get_group_id()
        raw = event.get_message_str()
        now = now_ts()

        user = self.store.get_abnormal(arcade.id, qq)
        if user is None:
            user = AbnormalUser(
                arcade_id=arcade.id,
                qq=qq,
                machine_id=machine.id,
                first_abnormal_at=now,
            )
        user.abnormal_count += 1
        user.machine_id = machine.id
        user.last_abnormal_at = now
        user.last_raw_message = raw
        user.last_abnormal_value = str(value)
        user.source_group_id = group_id
        user.status = "ignored" if user.abnormal_count >= 5 else "warning"
        if user.status == "ignored":
            user.ignored_at = now
        self.store.set_abnormal(user)
        self.store.save_abnormal()

        logger.info(
            f"[{PLUGIN_NAME}] 异常报卡 arcade={arcade.name} qq={qq} machine={machine.name} "
            f"值={value} 原因={reason} 第{user.abnormal_count}次 status={user.status}"
        )
        self.store.add_log(
            "warn", group_id, f"异常报卡 QQ={qq} 值={value} 原因={reason} 第{user.abnormal_count}次"
        )

        if user.abnormal_count >= 5:
            logger.info(f"[{PLUGIN_NAME}] 异常达 5 次，封禁静默忽略 qq={qq}")
            return EventOutcome(None, True)

        if user.abnormal_count == 4:
            reply = await self.llm_tease(arcade, qq, value, event)
        else:
            reply = self.format_error(arcade, qq, value, machine)
        return EventOutcome(reply, True)

    def format_error(self, arcade: Arcade, qq: str, value, machine: Machine | None = None) -> str:
        limit = f"{arcade.normal_count_min}-{arcade.normal_count_max}"
        # 无法解析（格式异常）与超范围是两类问题，不能共用「超出正常范围」模板，
        # 否则会出现「数值 无法解析 超出正常范围」这种自相矛盾的提示。
        if isinstance(value, str) and value == ABNORMAL_UNPARSEABLE:
            msg = (
                f"{arcade.name} 报卡失败：没能识别出报卡人数，"
                f"请按 z1y2 / 5k / 左3 这样的格式发送。"
            )
            return f"{msg}\n{self.help_hint()}"
        template = arcade.error_message_template or DEFAULT_ERROR_MESSAGE_TEMPLATE
        try:
            msg = template.format(arcade=arcade.name, qq=qq, value=value, limit=limit)
        except (KeyError, IndexError, ValueError):
            msg = f"{arcade.name} 报卡失败：数值 {value} 超出正常范围（{limit}）。"
        return f"{msg}\n{self.help_hint()}"

    async def llm_tease(self, arcade: Arcade, qq: str, value, event) -> str:
        nickname = event.get_sender_name() or qq
        limit = f"{arcade.normal_count_min}-{arcade.normal_count_max}"
        prompt = (
            f"你在一个机厅 QQ 群里。用户「{nickname}」(QQ:{qq}) 在机厅「{arcade.name}」"
            f"已经第 4 次异常报卡了，本次异常值为 {value}，正常范围是 {limit}。"
            f"请用一句轻松、幽默的话调侃并提醒 TA 注意报卡格式，不要严肃，不要 @ 任何人，直接输出调侃内容。"
        )
        fallback = self.format_error(arcade, qq, value)
        try:
            provider = await self._resolve_provider()
            if provider is None:
                logger.info(
                    f"[{PLUGIN_NAME}] LLM 调侃：无可用 Provider，使用默认文案 qq={qq}"
                )
                return fallback
            resp = await provider.text_chat(
                prompt=prompt, system_prompt="你是机厅群里幽默的报卡助手。"
            )
            text = (resp.completion_text or "").strip()
            if not text:
                logger.info(f"[{PLUGIN_NAME}] LLM 调侃返回空文本，使用默认文案 qq={qq}")
                return fallback
            return f"{text}\n{self.help_hint()}"
        except Exception as e:  # noqa: BLE001
            logger.error(
                f"[{PLUGIN_NAME}] LLM 调侃生成失败 arcade={arcade.name} qq={qq}",
                exc_info=True,
            )
            self.store.add_log("error", event.get_group_id(), f"LLM 调侃生成失败：{e}")
            return fallback

    # ---------- 查询 ----------

    def handle_query(self, arcade: Arcade, rest: str, event) -> str | None:
        parsed = parse_query(rest, arcade)
        if parsed is None:
            return None

        if parsed.machine is None:
            machines = list(arcade.machines.values())
            if not machines:
                return None
            lines = [f"{arcade.name} 排卡："]
            for machine in machines:
                lines.append(f"{machine.name}：")
                lines.extend(self._machine_query_lines(arcade, machine))
        else:
            machine = parsed.machine
            lines = [f"{arcade.name} {machine.name} 排卡："]
            lines.extend(self._machine_query_lines(arcade, machine))

        result = "\n".join(lines)
        machine_label = parsed.machine.name if parsed.machine else "全部机台"
        logger.info(
            f"[{PLUGIN_NAME}] 查询结果 arcade={arcade.name} machine={machine_label} "
            f"result={result!r}"
        )
        return result

    def _machine_query_lines(self, arcade: Arcade, machine: Machine) -> list[str]:
        self.lazy_clear_machine(arcade, machine)
        lines: list[str] = []
        now = now_ts()
        for pos_key in machine.position_keys:
            label = machine.position_aliases.get(pos_key, pos_key)
            rec = self.store.get_record(arcade.id, machine.id, pos_key)
            count = rec.count if rec else 0
            cleared_at = rec.last_clear_at if rec else 0
            # 人数为 0 但从未触发过清零、且已超过清零窗口的记录，
            # 同样按“无人报卡清零”展示，避免非默认机台一直显示陈旧的“更新于”时间。
            if count <= 0 and cleared_at <= 0 and rec and rec.last_update_at > 0:
                expire_at = self.record_expire_at(arcade, machine, rec)
                if now >= expire_at:
                    cleared_at = expire_at
            if count <= 0 and cleared_at > 0:
                last = rec.last_update_at if rec else 0
                last_str = format_time(last, arcade.timezone) if last else "-"
                lines.append(f"{label}：0 人（已超时清零，最后报卡 {last_str}）")
                continue
            last = rec.last_update_at if rec else 0
            time_str = format_time(last, arcade.timezone) if last else "-"
            lines.append(f"{label}：{count} 人（更新于 {time_str}）")
        return lines

    # ---------- 超时清零 ----------

    def expire_seconds(self, arcade: Arcade) -> int:
        return max(0, arcade.expire_hours) * 3600

    def machine_last_update(self, arcade_id: str, machine_id: str) -> float:
        recs = self.store.machine_records(arcade_id, machine_id)
        if not recs:
            return 0.0
        return max(r.last_update_at for r in recs)

    def record_expire_at(self, arcade: Arcade, machine: Machine, record: CardRecord) -> float:
        if arcade.expire_scope == "machine":
            base = self.machine_last_update(arcade.id, machine.id)
        else:
            base = record.last_update_at
        return base + self.expire_seconds(arcade)

    def is_expired(self, arcade: Arcade, machine: Machine, record: CardRecord, now=None) -> bool:
        if record.count <= 0:
            return False
        now = now if now is not None else now_ts()
        return now >= self.record_expire_at(arcade, machine, record)

    def lazy_clear_machine(self, arcade: Arcade, machine: Machine) -> bool:
        """惰性清零：仅在查询/报卡访问该机台时触发过期清零。"""
        now = now_ts()
        cleared = False
        for rec in self.store.machine_records(arcade.id, machine.id):
            if rec.count > 0 and self.is_expired(arcade, machine, rec, now):
                rec.count = 0
                rec.last_clear_at = now
                self.store.set_record(rec)
                cleared = True
        if cleared:
            self.store.save_records()
            logger.info(
                f"[{PLUGIN_NAME}] 惰性清零 arcade={arcade.name} machine={machine.name}"
            )
            # 与定时清零保持一致：该机台全部方位都已清零时，顺带解除相关黑名单
            # （需求 §7.2：忽略状态持续到机台超时清零）。
            if self.machine_all_cleared(arcade.id, machine.id):
                self.store.clear_machine_abnormal(arcade.id, machine.id)
                logger.info(
                    f"[{PLUGIN_NAME}] 惰性清零并清除黑名单 arcade={arcade.name} "
                    f"machine={machine.name}"
                )
                self.store.add_log(
                    "info", "", f"{arcade.name} {machine.name} 全部超时清零，已清除相关黑名单"
                )
        return cleared

    def clear_expired(self) -> list[str]:
        """全局过期清零，返回已整体清零的机台键列表。"""
        now = now_ts()
        cleared_machines: set[tuple[str, str]] = set()
        for (arcade_id, machine_id, pos_key), rec in list(self.store.records.items()):
            if rec.count <= 0:
                continue
            arcade = self.store.get_arcade(arcade_id)
            if arcade is None:
                continue
            machine = arcade.machines.get(machine_id)
            if machine is None:
                continue
            if self.is_expired(arcade, machine, rec, now):
                rec.count = 0
                rec.last_clear_at = now
                self.store.set_record(rec)
                cleared_machines.add((arcade_id, machine_id))
        if cleared_machines:
            self.store.save_records()

        result: list[str] = []
        for (arcade_id, machine_id) in cleared_machines:
            if self.machine_all_cleared(arcade_id, machine_id):
                self.store.clear_machine_abnormal(arcade_id, machine_id)
                logger.info(
                    f"[{PLUGIN_NAME}] 机台超时清零并清除黑名单 arcade_id={arcade_id} "
                    f"machine_id={machine_id}"
                )
                self.store.add_log("info", "", f"机台 {machine_id} 全部超时清零，已清除相关黑名单")
                result.append(f"{arcade_id}:{machine_id}")
        return result

    def machine_all_cleared(self, arcade_id: str, machine_id: str) -> bool:
        recs = self.store.machine_records(arcade_id, machine_id)
        return all(r.count <= 0 for r in recs) if recs else True

    # ---------- 开门 / 闭店 ----------

    async def check_notices(self) -> None:
        for arcade in self.store.list_arcades():
            try:
                await self._check_arcade_notices(arcade)
            except Exception as e:  # noqa: BLE001
                logger.error(
                    f"[{PLUGIN_NAME}] 通知检查失败 arcade={arcade.name}",
                    exc_info=True,
                )
                self.store.add_log("error", "", f"机厅 {arcade.name} 通知检查失败：{e}")

    @staticmethod
    def _notice_delay_seconds(now_local: datetime, time_str: str | None) -> int | None:
        """返回「当前时间 - 目标时间」的秒数；不在补发窗口内返回 None。

        窗口为 ``[0, NOTICE_CATCHUP_SECONDS]``：还没到点（负数）或已超过
        5 分钟都返回 None，避免凌晨启动时把白天的开门语补发出去。
        """
        if not time_str:
            return None
        try:
            hour, minute = (int(part) for part in str(time_str).split(":"))
            target = now_local.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
        except (ValueError, TypeError):
            return None
        delay = int((now_local - target).total_seconds())
        if 0 <= delay <= NOTICE_CATCHUP_SECONDS:
            return delay
        return None

    async def _check_arcade_notices(self, arcade: Arcade) -> None:
        try:
            tz = ZoneInfo(arcade.timezone or DEFAULT_TIMEZONE)
        except Exception:  # noqa: BLE001
            tz = ZoneInfo(DEFAULT_TIMEZONE)
        now_local = datetime.now(tz)
        today = now_local.strftime("%Y-%m-%d")

        open_delay = self._notice_delay_seconds(now_local, arcade.open_time)
        if (
            arcade.open_message_enabled
            and open_delay is not None
            and self.store.state.last_open_notice.get(arcade.id) != today
        ):
            if open_delay >= 60:
                logger.info(
                    f"[{PLUGIN_NAME}] {arcade.name} 开门语补发，已过点 {open_delay} 秒"
                )
                self.store.add_log(
                    "info", "", f"{arcade.name} 开门语补发（已过点 {open_delay} 秒，仍在 5 分钟窗口内）"
                )
            if await self._send_notice(arcade, "open"):
                self.store.state.last_open_notice[arcade.id] = today
                self.store.save_state()

        close_delay = self._notice_delay_seconds(now_local, arcade.close_time)
        if (
            arcade.close_message_enabled
            and close_delay is not None
            and self.store.state.last_close_notice.get(arcade.id) != today
        ):
            if close_delay >= 60:
                logger.info(
                    f"[{PLUGIN_NAME}] {arcade.name} 闭店语补发，已过点 {close_delay} 秒"
                )
                self.store.add_log(
                    "info", "", f"{arcade.name} 闭店语补发（已过点 {close_delay} 秒，仍在 5 分钟窗口内）"
                )
            if await self._send_notice(arcade, "close"):
                self.store.state.last_close_notice[arcade.id] = today
                self.store.save_state()

    async def _send_notice(self, arcade: Arcade, kind: str) -> bool:
        """生成并发送开门/闭店语；返回是否至少有一个群发送成功。

        调用方只在返回 True 时把当天标记为「已发送」，失败（无群会话、
        context 不可用、发送异常）留待定时任务在 5 分钟补发窗口内重试。
        只有确认存在可发送的群和通道后才生成文案，避免重试时反复调用大模型。
        """
        scene = "开门" if kind == "open" else "闭店"
        prompt_ref = arcade.open_prompt_ref if kind == "open" else arcade.close_prompt_ref

        bound_groups = [gid for gid in arcade.group_ids if gid]
        sessions: list[tuple[str, str]] = []
        missing_groups: list[str] = []
        for gid in bound_groups:
            session = self.store.state.group_sessions.get(gid)
            if session:
                sessions.append((gid, session))
            else:
                missing_groups.append(gid)

        if not sessions:
            detail = (
                f"机厅绑定的群均无会话记录 groups={bound_groups or '无'}；"
                f"需要对应群先发送过一条消息才能主动推送"
            )
            logger.warning(f"[{PLUGIN_NAME}] {arcade.name} {scene}语未发送：{detail}")
            self.store.add_log("warn", "", f"{arcade.name} {scene}语未发送：{detail}")
            return False

        # context 为空时无法主动发消息（仅测试/本地回退会出现），直接记录并返回
        if self.context is None:
            logger.warning(
                f"[{PLUGIN_NAME}] {arcade.name} {scene}语无法发送：context 不可用"
            )
            self.store.add_log("warn", "", f"{arcade.name} {scene}语无法发送：context 不可用")
            return False
        send_message = getattr(self.context, "send_message", None)
        if not callable(send_message):
            logger.warning(
                f"[{PLUGIN_NAME}] {arcade.name} {scene}语无法发送：context 缺少 send_message"
            )
            self.store.add_log("warn", "", f"{arcade.name} {scene}语无法发送：context 缺少 send_message")
            return False

        try:
            from astrbot.api.event import MessageChain  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            logger.error(
                f"[{PLUGIN_NAME}] {arcade.name} {scene}语发送失败：无法加载 MessageChain",
                exc_info=True,
            )
            self.store.add_log("error", "", f"{arcade.name} {scene}语发送失败：无法加载 MessageChain")
            return False

        # 确认有可发送的群与通道后再生成文案，避免补发重试时反复调用大模型
        text = await self._generate_notice_text(arcade, scene, prompt_ref)

        success_count = 0
        for gid, session in sessions:
            try:
                await send_message(session, MessageChain().message(text))
                success_count += 1
                logger.info(
                    f"[{PLUGIN_NAME}] {arcade.name} {scene}语发送成功 group={gid} session={session}"
                )
                self.store.add_log("info", gid, f"{arcade.name} {scene}语发送成功 group={gid}")
            except Exception as e:  # noqa: BLE001
                logger.error(
                    f"[{PLUGIN_NAME}] {arcade.name} {scene}语发送失败 "
                    f"group={gid} session={session}",
                    exc_info=True,
                )
                self.store.add_log(
                    "error",
                    gid,
                    f"{arcade.name} {scene}语发送失败 group={gid} "
                    f"session={session}：{type(e).__name__}: {e}",
                )

        if success_count == 0:
            logger.warning(
                f"[{PLUGIN_NAME}] {arcade.name} {scene}语全部发送失败"
                f"（{len(sessions)} 个群），将在补发窗口内重试"
            )
            self.store.add_log(
                "error",
                "",
                f"{arcade.name} {scene}语全部发送失败（{len(sessions)} 个群），"
                f"将在 5 分钟窗口内重试",
            )
            return False

        logger.info(
            f"[{PLUGIN_NAME}] {arcade.name} 已发送{scene}语 "
            f"sessions={success_count}/{len(sessions)}"
        )
        self.store.add_log(
            "info", "", f"{arcade.name} 已发送{scene}语：成功 {success_count}/{len(sessions)} 个群"
        )
        if missing_groups:
            self.store.add_log(
                "warn",
                "",
                f"{arcade.name} {scene}语跳过无会话的群：{missing_groups}",
            )
        return True

    async def _generate_notice_text(self, arcade: Arcade, scene: str, prompt_ref: str | None) -> str:
        prompt = (
            f"机厅「{arcade.name}」现在{scene}。"
            f"参考风格/要点：{prompt_ref or '无'}。"
            f"请生成一句简短、友好、有活力、不 @ 任何人的{scene}语，直接输出正文。"
        )
        if scene == "开门":
            fallback = f"【{arcade.name}】开门啦！欢迎来玩~"
        else:
            fallback = f"【{arcade.name}】今天闭店了，明天见！"
        try:
            provider = await self._resolve_provider()
            if provider is None:
                logger.info(f"[{PLUGIN_NAME}] {arcade.name} {scene}语：无 Provider，使用默认文案")
                return fallback
            resp = await provider.text_chat(
                prompt=prompt, system_prompt="你是机厅群公告助手。"
            )
            text = (resp.completion_text or "").strip()
            return text or fallback
        except Exception:  # noqa: BLE001
            logger.error(
                f"[{PLUGIN_NAME}] {arcade.name} {scene}语生成失败，使用默认文案",
                exc_info=True,
            )
            return fallback
"""事件处理 Mixin：监听群消息，解析报卡/查询并回复。"""

from __future__ import annotations

from astrbot.api.event import AstrMessageEvent, filter

from ..config import PLUGIN_NAME
from ..log import logger


class EventHandlerMixin:
    """负责把群消息路由到 ReportService，并输出回复。"""

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_group_message(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        # 仅处理已在机厅管理中添加（绑定）的群，其余群的消息直接静默返回，
        # 避免无差别接收所有群消息导致日志繁杂。
        service = getattr(self, "service", None)
        if service is None or not service.is_managed_group(group_id):
            return
        sender_id = event.get_sender_id()
        raw_text = event.get_message_str()
        logger.info(
            f"[{PLUGIN_NAME}] 收到群消息 group={group_id} sender={sender_id} "
            f"text={raw_text!r}"
        )
        store = getattr(self, "store", None)
        if store is not None:
            try:
                store.add_log(
                    "debug",
                    group_id or "",
                    f"收到群消息 sender={sender_id} text={raw_text!r}",
                )
            except Exception:
                logger.warning(
                    f"[{PLUGIN_NAME}] 写入本地日志失败（收到群消息）", exc_info=True
                )
        try:
            outcome = await self.service.handle_event(event)
        except Exception:
            logger.error(
                f"[{PLUGIN_NAME}] 处理群消息异常 group={group_id} sender={sender_id} "
                f"text={raw_text!r}",
                exc_info=True,
            )
            if store is not None:
                try:
                    store.add_log(
                        "error",
                        group_id or "",
                        f"处理群消息异常 sender={sender_id} text={raw_text!r}",
                    )
                except Exception:
                    pass
            raise
        logger.info(
            f"[{PLUGIN_NAME}] 处理结果 group={group_id} sender={sender_id} "
            f"should_stop={outcome.should_stop} reply={outcome.reply!r}"
        )
        if store is not None:
            try:
                store.add_log(
                    "debug",
                    group_id or "",
                    f"处理结果 sender={sender_id} should_stop={outcome.should_stop} "
                    f"reply={outcome.reply!r}",
                )
            except Exception:
                logger.warning(
                    f"[{PLUGIN_NAME}] 写入本地日志失败（处理结果）", exc_info=True
                )
        if outcome.should_stop:
            event.stop_event()
        if outcome.reply:
            yield event.plain_result(outcome.reply)
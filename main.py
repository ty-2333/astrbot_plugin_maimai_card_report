"""舞萌报卡插件入口。

组合 WebAPI / 事件处理 Mixin，并启动超时清零与开门/闭店语定时任务。
"""

from __future__ import annotations

import asyncio

from astrbot.api.event import filter
from astrbot.api.star import Context, Star

from .astrbot_compat import get_star_handlers_registry
from .backend.service import ReportService
from .backend.store import PluginStore
from .config import PLUGIN_NAME, get_plugin_data_dir
from .log import logger
from .mixins.event_handlers import EventHandlerMixin
from .mixins.web_api import WebAPIMixin

SCHEDULER_INTERVAL_SECONDS = 30


class MaiMaiCardReport(Star, WebAPIMixin, EventHandlerMixin):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self._normalize_mixin_handler_module_paths()
        self.config = config if config is not None else {}
        self._data_dir = get_plugin_data_dir()
        logger.info(f"[{PLUGIN_NAME}] 插件初始化，数据目录：{self._data_dir}")
        self.store = PluginStore(self._data_dir)
        self.service = ReportService(self.store, context)
        self._scheduler_task: asyncio.Task | None = None

    @classmethod
    def _normalize_mixin_handler_module_paths(cls) -> None:
        """将 Mixin 中注册的指令处理器重新绑定到插件主模块路径。

        AstrBot 的处理器注册表以 ``handler.__module__`` 作为模块路径，
        而 ``star_map`` 以插件主类所在模块（main）为 key 判断激活状态。
        直接写在 Mixin 中的 ``@filter`` 处理器会因路径不匹配而被
        ``get_handlers_by_event_type(only_activated=True)`` 过滤掉，
        导致事件监听（如群消息报卡）完全不触发。

        这里在插件实例化时，把 ``{plugin_package}.mixins.*`` 的处理器
        全部改写到 ``{plugin_package}.main``，与参考实现保持一致。
        """
        try:
            registry = get_star_handlers_registry()
        except Exception:
            logger.debug(f"[{PLUGIN_NAME}] 无法获取 Handler 注册表，跳过 Mixin 路径归一化")
            return

        plugin_package = cls.__module__.rsplit(".", 1)[0]
        mixin_module_prefix = f"{plugin_package}.mixins."
        adjusted_count = 0
        for handler_metadata in registry:
            if not handler_metadata.handler_module_path.startswith(
                mixin_module_prefix
            ):
                continue
            handler_metadata.handler_module_path = cls.__module__
            adjusted_count += 1

        if adjusted_count:
            logger.info(
                f"[{PLUGIN_NAME}] 已将 {adjusted_count} 个 Mixin 指令处理器绑定到插件主模块"
            )

    async def initialize(self) -> None:
        logger.info(f"[{PLUGIN_NAME}] 注册 WebUI API ...")
        try:
            self._register_web_apis()
            logger.info(f"[{PLUGIN_NAME}] WebUI API 注册完成")
        except Exception:
            logger.error(f"[{PLUGIN_NAME}] WebUI API 注册失败", exc_info=True)
            raise
        # 在 initialize() 中启动定时任务，保证插件通过面板安装/重载后也能运行，
        # 而不依赖只在 AstrBot 核心启动时触发一次的 on_astrbot_loaded。
        self._ensure_scheduler_started()

    def _ensure_scheduler_started(self) -> None:
        if self._scheduler_task is None or self._scheduler_task.done():
            self._scheduler_task = asyncio.create_task(self._scheduler_loop())
            logger.info(f"[{PLUGIN_NAME}] 定时任务已启动")

    @filter.on_astrbot_loaded()
    async def _start_scheduler(self) -> None:
        # 保留 on_astrbot_loaded 作为兜底（核心启动时也会触发 initialize，
        # 此处仅做幂等保护，避免重复创建任务）。
        self._ensure_scheduler_started()

    @filter.on_plugin_unloaded()
    async def _stop_scheduler(self, *args, **kwargs) -> None:
        task = self._scheduler_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        logger.info(f"[{PLUGIN_NAME}] 定时任务已停止")

    async def _scheduler_loop(self) -> None:
        logger.info(f"[{PLUGIN_NAME}] 定时任务循环已启动，间隔 {SCHEDULER_INTERVAL_SECONDS}s")
        while True:
            try:
                await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)
                cleared = self.service.clear_expired()
                if cleared:
                    logger.info(f"[{PLUGIN_NAME}] 定时清零完成，清零机台数={len(cleared)}：{cleared}")
                await self.service.check_notices()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.error(f"[{PLUGIN_NAME}] 定时任务执行异常", exc_info=True)
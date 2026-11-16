"""AstrBot 兼容层：统一封装可能随版本变动的内部导入，避免其他模块直接依赖内部路径。"""

from __future__ import annotations

from pathlib import Path


def get_astrbot_plugin_data_path() -> Path | None:
    """返回 AstrBot 插件数据根目录（Path）；AstrBot 不可用时返回 None。"""
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

        return get_astrbot_plugin_data_path()
    except Exception:
        return None


def get_star_handlers_registry():
    """返回 AstrBot 共享的 Handler 注册表（延迟导入，避免循环依赖）。

    用于将 Mixin 中定义的指令处理器重新绑定到插件主模块路径，
    以兼容尚未原生支持 Mixin 指令处理器的 AstrBot 版本。
    """
    from astrbot.core.star.star_handler import star_handlers_registry

    return star_handlers_registry
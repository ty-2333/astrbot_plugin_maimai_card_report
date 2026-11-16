"""日志工具：统一提供 AstrBot 标准 logger，独立运行 / 单元测试时回退到标准 logging。

其它模块通过 ``from ..log import logger`` 复用同一个 logger 实例。
诊断日志会输出到 AstrBot 标准日志通道（面板「日志」与 AstrBot 主日志文件），
便于在不依赖插件自身的 logs.json 的情况下排查问题。
"""

from __future__ import annotations

import logging as _logging

try:
    from astrbot.api import logger as logger  # type: ignore[no-redef]
except Exception:  # noqa: BLE001
    logger = _logging.getLogger("maimai_card_report")
    if not logger.handlers:
        _handler = _logging.StreamHandler()
        _handler.setFormatter(
            _logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(_handler)
    logger.setLevel(_logging.INFO)
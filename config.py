"""全局常量与数据目录定义。"""

from __future__ import annotations

from pathlib import Path

from .astrbot_compat import get_astrbot_plugin_data_path

PLUGIN_NAME = "maimai_card_report"
PLUGIN_DISPLAY_NAME = "舞萌报卡"

PLUGIN_DIR = Path(__file__).resolve().parent

# —— 默认值 ——
DEFAULT_EXPIRE_HOURS = 4
DEFAULT_NORMAL_COUNT_MIN = 0
DEFAULT_NORMAL_COUNT_MAX = 20
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_EXPIRE_SCOPE = "slot"  # slot | machine
DEFAULT_ERROR_MESSAGE_TEMPLATE = "{arcade} 报卡失败：数值 {value} 超出正常范围（{limit}）。"

POSITION_MODES = ("left_right", "inside_outside", "custom")
DEFAULT_POSITION_MODE = "left_right"
DEFAULT_POSITION_ALIASES: dict[str, dict[str, str]] = {
    "left_right": {"z": "左", "y": "右"},
    "inside_outside": {"n": "内", "w": "外"},
    "custom": {},
}

# 异常判定类型
ABNORMAL_OUT_OF_RANGE = "超范围"
ABNORMAL_NEGATIVE = "负数"
ABNORMAL_UNPARSEABLE = "无法解析"
ABNORMAL_NON_INTEGER = "非整数"

# 数据文件名
DATA_FILE_ARCADES = "arcades.json"
DATA_FILE_RECORDS = "records.json"
DATA_FILE_ABNORMAL = "abnormal.json"
DATA_FILE_LOGS = "logs.json"
DATA_FILE_STATE = "state.json"

# 查询标记
QUERY_MARKERS = ("jk", "几", "?")

# help 指令触发词（精确匹配；normalize_text 后已小写）
HELP_EXACT = ("help", "帮助", "用法", "说明", "报卡说明", "报卡格式", "怎么报卡", "如何报卡", "使用说明")
# help 指令包含匹配关键词（消息中包含即触发）
HELP_CONTAINS = ("help", "帮助", "报卡说明", "报卡格式", "怎么报卡", "如何报卡", "使用说明")


def get_plugin_data_dir() -> Path:
    """返回插件数据根目录；AstrBot 不可用时回退到本地 data 目录。"""
    root = get_astrbot_plugin_data_path()
    if root is not None:
        return Path(root) / PLUGIN_NAME
    return PLUGIN_DIR / "data" / "plugin_data" / PLUGIN_NAME
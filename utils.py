"""通用工具函数：文本归一化、中文数字转换、时间与 ID 生成等。"""

from __future__ import annotations

import re
import time
import uuid
from datetime import datetime

# 中文数字
_CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}
_CN_NUM_RE = re.compile(r"[零一二两三四五六七八九十百千]+")

# @ 提及前缀：QQ 客户端会把「@昵称」渲染成 @昵称(QQ号)，昵称里可能还有括号
_MENTION_WITH_ID_RE = re.compile(r"^@[^\s@]+\(\d{4,12}\)\s*")
_MENTION_PLAIN_RE = re.compile(r"^@[^\s@]+\s+")


def to_halfwidth(text: str) -> str:
    """全角字符转半角，全角空格转普通空格。"""
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def cn_num_to_int(text: str) -> int | None:
    """将中文数字串转换为整数，无法识别返回 None。"""
    text = text.strip()
    if not text:
        return None
    total = 0
    section = 0
    number = 0
    for ch in text:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            if number == 0:
                number = 1
            section += number * unit
            number = 0
            if unit >= 100:
                total += section
                section = 0
        else:
            return None
    return total + section + number


def _cn_to_arabic(match: re.Match) -> str:
    value = cn_num_to_int(match.group(0))
    return str(value) if value is not None else match.group(0)


def normalize_text(text: str | None) -> str:
    """归一化消息文本：去空白、全角转半角、中文数字转阿拉伯、统一小写。"""
    if not text:
        return ""
    text = text.strip()
    text = " ".join(text.split())
    text = to_halfwidth(text)
    text = _CN_NUM_RE.sub(_cn_to_arabic, text)
    return text.lower()


def strip_mention_prefix(text: str | None) -> str:
    """去掉文本开头的一个或多个 @ 提及，返回剩余内容。

    只处理「句首」的提及，避免误伤正文中间的内容：
    - ``@机器人(123456) 5k`` → ``5k``
    - ``@机器人 左5`` → ``左5``
    - ``@小明 @机器人 5k`` → ``5k``

    没有 QQ 号后缀时要求 @昵称后必须跟空白，避免把 ``@某人z1y2``
    这种没有空格的整段文字误当成提及而删掉。
    """
    if not text:
        return ""
    result = text.strip()
    for _ in range(3):  # 最多连续剥离 3 个提及
        stripped = _MENTION_WITH_ID_RE.sub("", result, count=1)
        if stripped == result:
            stripped = _MENTION_PLAIN_RE.sub("", result, count=1)
        if stripped == result:
            break
        result = stripped.lstrip()
    return result.strip()


def now_ts() -> float:
    return time.time()


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def format_time(ts: float | None, timezone: str = "Asia/Shanghai") -> str:
    """将时间戳格式化为可读字符串；为空返回 '-'。"""
    if not ts:
        return "-"
    try:
        from zoneinfo import ZoneInfo

        return datetime.fromtimestamp(ts, ZoneInfo(timezone)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def valid_hm(value: str | None) -> bool:
    """校验 HH:MM 时间格式。"""
    if not value:
        return False
    return bool(re.fullmatch(r"(?:[01]?\d|2[0-3]):[0-5]\d", value.strip()))


def valid_group_id(value: str | None) -> bool:
    """校验群号格式（3-32 位数字/字母/下划线/连字符）。"""
    if not value:
        return False
    return bool(re.fullmatch(r"[0-9A-Za-z_\-]{3,32}", value.strip()))
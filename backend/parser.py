"""文本解析：机厅/机台/方位别名匹配、报卡与查询解析、正负号与累加识别。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..utils import normalize_text
from .models import Arcade, Machine


def _search_tokens(*parts: str) -> list[str]:
    """把名称与别名列表归一化，去空，用于子串匹配。"""
    tokens: list[str] = []
    for p in parts:
        if p:
            n = normalize_text(p)
            if n:
                tokens.append(n)
    return tokens


# —— 机厅 ——
def arcade_search_tokens(arcade: Arcade) -> list[str]:
    return _search_tokens(arcade.name, *arcade.aliases)


def match_arcade(text: str, arcades: list[Arcade]) -> tuple[Arcade, str] | None:
    """从归一化文本中匹配机厅，返回 (arcade, 去除机厅别名后的剩余文本)。"""
    candidates: list[tuple[int, str, Arcade]] = []
    for arcade in arcades:
        for token in arcade_search_tokens(arcade):
            candidates.append((len(token), token, arcade))
    candidates.sort(key=lambda x: -x[0])
    for _, token, arcade in candidates:
        if token in text:
            return arcade, text.replace(token, "", 1)
    return None


# —— 机台 ——
def machine_search_tokens(machine: Machine) -> list[str]:
    return _search_tokens(machine.name, *machine.aliases)


def default_machine(arcade: Arcade) -> Machine | None:
    for machine in arcade.machines.values():
        if machine.is_default:
            return machine
    if arcade.machines:
        return next(iter(arcade.machines.values()))
    return None


def match_machine(text: str, arcade: Arcade) -> tuple[Machine, str] | None:
    """从剩余文本中匹配机台，返回 (machine, 去除机台别名后的剩余文本)。"""
    candidates: list[tuple[int, str, Machine]] = []
    for machine in arcade.machines.values():
        for token in machine_search_tokens(machine):
            candidates.append((len(token), token, machine))
    candidates.sort(key=lambda x: -x[0])
    for _, token, machine in candidates:
        if token in text:
            return machine, text.replace(token, "", 1)
    return None


# —— 方位 ——
def machine_position_tokens(machine: Machine) -> list[tuple[str, str]]:
    """返回 [(归一化 token, position_key)]，按 token 长度降序。"""
    result: list[tuple[str, str]] = []
    for key, label in machine.position_aliases.items():
        kn = normalize_text(key)
        if kn:
            result.append((kn, key))
        ln = normalize_text(label)
        if ln and ln != kn:
            result.append((ln, key))
    seen: dict[str, str] = {}
    for token, key in result:
        if token not in seen:
            seen[token] = key
    result = [(t, k) for t, k in seen.items()]
    result.sort(key=lambda x: -len(x[0]))
    return result


def _lookup_pos_key(tokens: list[tuple[str, str]], alias: str) -> str | None:
    for token, key in tokens:
        if token == alias:
            return key
    return None


@dataclass
class ParsedEntry:
    position_key: str | None  # None 表示「仅数量」：默认机台首个方位
    count: int  # 覆盖值或变动量，恒为非负数
    increment: bool  # 带 + 累加
    decrement: bool = False  # 带 - 扣减（在当前人数上减少，最低到 0）


@dataclass
class ParsedReport:
    machine: Machine
    entries: list[ParsedEntry]


@dataclass
class ParsedQuery:
    machine: Machine | None  # None 表示查询机厅内所有机台


def _position_pattern(machine: Machine) -> re.Pattern | None:
    tokens = machine_position_tokens(machine)
    if not tokens:
        return None
    alias_alt = "|".join(re.escape(t) for t, _ in tokens)
    return re.compile(
        rf"(?:(?P<sign1>[+-]?)(?P<n1>\d+)\s*(?P<a1>{alias_alt}))"
        rf"|(?:(?P<a2>{alias_alt})\s*(?P<sign2>[+-]?)\s*(?P<n2>\d+))"
    )


def parse_position_entries(text: str, machine: Machine) -> list[ParsedEntry]:
    """解析 'z1y2'、'内1k外2k'、'z+1y2'、'z-1'、'1p' 等方位报卡。

    ``+`` 表示累加、``-`` 表示扣减、无符号表示覆盖；扣减量始终以
    非负数的形式保存在 ``count`` 中，由 ``decrement`` 标记方向。
    """
    pattern = _position_pattern(machine)
    if pattern is None:
        return []
    tokens = machine_position_tokens(machine)
    entries: list[ParsedEntry] = []
    for m in pattern.finditer(text):
        if m.group("n1") is not None:
            count = int(m.group("n1"))
            sign = m.group("sign1") or ""
            pos_key = _lookup_pos_key(tokens, m.group("a1"))
            if pos_key:
                entries.append(
                    ParsedEntry(pos_key, count, sign == "+", sign == "-")
                )
        else:
            count = int(m.group("n2"))
            sign = m.group("sign2") or ""
            pos_key = _lookup_pos_key(tokens, m.group("a2"))
            if pos_key:
                entries.append(
                    ParsedEntry(pos_key, count, sign == "+", sign == "-")
                )
    return entries


_COUNT_ONLY_RE = re.compile(
    r"^(?:(?P<sign>[+-])(?P<signed>\d+)|(?P<plain>\d+))(?P<unit>[k卡人])?$"
)


def extract_signed_count(text: str) -> tuple[str, int] | None:
    """提取纯数量报卡文本，返回 (模式, 数量)，模式为 set / add / sub。

    必须带卡数单位（k / 卡 / 人）或显式正负号，例如 '5k'、'+1'、'-2卡'；
    裸数字（如 '6'、'666'、'2026'）属于普通聊天内容，不再视为报卡，
    以免群里的数字消息被误记成排卡或异常。
    """
    m = _COUNT_ONLY_RE.match(text.strip())
    if not m:
        return None
    sign = m.group("sign") or ""
    unit = m.group("unit") or ""
    if not sign and not unit:
        return None
    raw = m.group("signed") if sign else m.group("plain")
    if raw is None:
        return None
    mode = "add" if sign == "+" else "sub" if sign == "-" else "set"
    return mode, int(raw)


def first_position_key(machine: Machine) -> str | None:
    keys = machine.position_keys
    return keys[0] if keys else None


def parse_report(rest: str, arcade: Arcade) -> ParsedReport | None:
    """解析报卡文本。rest 为去除机厅别名后的归一化文本。"""
    matched = match_machine(rest, arcade)
    if matched:
        machine, remainder = matched
    else:
        machine = default_machine(arcade)
        remainder = rest
    if machine is None:
        return None

    entries = parse_position_entries(remainder, machine)
    if entries:
        return ParsedReport(machine=machine, entries=entries)

    # 仅数量：如 "5k"、"5卡"、"+1"、"-2k"（裸数字不算，见 extract_signed_count）
    signed = extract_signed_count(remainder)
    if signed is None:
        return None
    mode, count = signed
    pos_key = first_position_key(machine)
    if pos_key is None:
        return None
    return ParsedReport(
        machine=machine,
        entries=[ParsedEntry(pos_key, count, mode == "add", mode == "sub")],
    )


def is_query(text: str) -> bool:
    """判断文本是否为查询意图。

    仅接受明确的查询关键词，避免把普通句末问号或口语里的“几”误判为查询：
    - 「jk」＝几卡缩写；
    - 「几」后紧跟卡数单位（几卡 / 几k / 几人）；
    - 「?」后紧跟卡数单位（?k / ?卡 / ?人）。

    单独的「?」「??」以及「现在?」「不是?」等疑问语气不会命中。
    """
    t = text.strip()
    if not t:
        return False
    if "jk" in t:
        return True
    if re.search(r"几[k卡人]", t):
        return True
    if re.search(r"\?[k卡人]", t):
        return True
    return False


def parse_query(rest: str, arcade: Arcade) -> ParsedQuery | None:
    """解析查询文本。机台缺省时 machine 为 None，表示查询机厅内所有机台。"""
    matched = match_machine(rest, arcade)
    if matched:
        machine, _ = matched
        return ParsedQuery(machine=machine)
    if not arcade.machines:
        return None
    return ParsedQuery(machine=None)


_REPORT_UNIT_TOKENS = ("k", "卡", "人")
_REPORT_NON_SIGNAL_RE = re.compile(r"[0-9+\-]")


def _report_residue(rest: str, arcade: Arcade) -> str:
    """去掉报卡相关原子后返回剩余文本。

    原子包括：卡数单位（k/卡/人）、所有机台的方位别名、数字与正负号。
    剩余非空说明文本里还夹杂普通聊天内容，不应判定为报卡尝试。
    """
    tokens: set[str] = set(_REPORT_UNIT_TOKENS)
    for machine in arcade.machines.values():
        for token, _ in machine_position_tokens(machine):
            if token:
                tokens.add(token)
    for token in sorted(tokens, key=len, reverse=True):
        rest = rest.replace(token, "")
    return _REPORT_NON_SIGNAL_RE.sub("", rest).strip()


def _contains_position_token(rest: str, arcade: Arcade) -> bool:
    for machine in arcade.machines.values():
        for token, _ in machine_position_tokens(machine):
            if token in rest:
                return True
    return False


def _has_report_signal(rest: str, arcade: Arcade) -> bool:
    """判断文本是否含明确的报卡信号。

    只认三类：卡数单位（k/卡/人）、行首正负号 + 数字、机台方位别名。
    单独的数字（如「6」「666」「2026」）不构成报卡信号，避免把群里的
    普通数字消息计入异常次数。
    """
    if re.search(r"[k卡人]", rest):
        return True
    if re.match(r"^[+-]\d", rest):
        return True
    return _contains_position_token(rest, arcade)


def looks_like_report_attempt(rest: str, arcade: Arcade) -> bool:
    """判断去除机厅别名后、但未能解析成功的内容是否为一次失败的报卡尝试。

    为避免普通群聊误触发，仅当内容足够短、只由报卡相关符号组成
    （卡数单位 / 方位别名 / 数字 / 正负号），且含明确报卡信号时，
    才视为报卡尝试。裸数字不算尝试，会被当作普通聊天静默忽略。
    """
    rest = rest.strip()
    if not rest:
        return False
    if len(rest) > 12:
        return False
    if _report_residue(rest, arcade):
        return False
    return _has_report_signal(rest, arcade)
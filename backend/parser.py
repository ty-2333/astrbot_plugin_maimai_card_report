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


def _entry_from_match(m: re.Match, tokens: list[tuple[str, str]]) -> ParsedEntry | None:
    """把单个正则匹配转换为报卡条目。"""
    if m.group("n1") is not None:
        count = int(m.group("n1"))
        sign = m.group("sign1") or ""
        pos_key = _lookup_pos_key(tokens, m.group("a1"))
    else:
        count = int(m.group("n2"))
        sign = m.group("sign2") or ""
        pos_key = _lookup_pos_key(tokens, m.group("a2"))
    if not pos_key:
        return None
    return ParsedEntry(pos_key, count, sign == "+", sign == "-")


def _scan_entries(
    text: str,
    pattern: re.Pattern,
    tokens: list[tuple[str, str]],
    strict: bool,
) -> list[ParsedEntry] | None:
    """扫描方位报卡；strict 模式要求匹配从开头连续覆盖到结尾。"""
    entries: list[ParsedEntry] = []
    pos = 0
    for m in pattern.finditer(text):
        if strict and m.start() != pos:
            return None
        entry = _entry_from_match(m, tokens)
        if entry is not None:
            entries.append(entry)
        pos = m.end()
    if strict and (not entries or pos != len(text)):
        return None
    return entries


def parse_position_entries(text: str, machine: Machine) -> list[ParsedEntry]:
    """解析 'z1y2'、'内1k外2k'、'z+1y2'、'z-1'、'1p' 等方位报卡。

    ``+`` 表示累加、``-`` 表示扣减、无符号表示覆盖；扣减量始终以
    非负数的形式保存在 ``count`` 中，由 ``decrement`` 标记方向。

    解析时优先找「能完整消耗到结尾」的后缀，再把它前面的内容按宽松
    模式补扫一遍。这样 ``中二z1y2`` 经归一化变成 ``中2z1y2`` 后，前缀
    机器名里的数字不会被当成方位人数（正确结果是左 1、右 2），而
    ``左5 z1y2`` 这类多段报卡也不会丢。
    """
    pattern = _position_pattern(machine)
    if pattern is None:
        return []
    tokens = machine_position_tokens(machine)

    if len(text) <= 64:
        for start in range(len(text)):
            suffix = _scan_entries(text[start:], pattern, tokens, strict=True)
            if not suffix:
                continue
            prefix = _scan_entries(text[:start], pattern, tokens, strict=False) or []
            return prefix + suffix

    entries = _scan_entries(text, pattern, tokens, strict=False)
    return entries or []


_COUNT_ONLY_RE = re.compile(
    r"^(?:(?P<sign>[+-])(?P<signed>\d+)|(?P<plain>\d+))(?P<unit>[k卡人])?$"
)
# 纯数字（仅允许跟在显式机台别名后面，如 tg2 / 太鼓2）
_BARE_COUNT_RE = re.compile(r"^\d+$")


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


def _starts_with_machine(text: str, machine: Machine) -> bool:
    """机台别名是否出现在文本开头（允许前导空白）。"""
    stripped = text.strip()
    return any(stripped.startswith(token) for token in machine_search_tokens(machine))


def parse_report(rest: str, arcade: Arcade) -> ParsedReport | None:
    """解析报卡文本。rest 为去除机厅别名后的归一化文本。

    裸数字只有在「显式机台前缀」出现在句首时才被当作人数，例如
    ``tg2``、``太鼓2``、``wm3``；群聊里单独一个 ``6`` 仍然不是报卡。
    """
    matched = match_machine(rest, arcade)
    explicit_machine = False
    if matched:
        machine, remainder = matched
        explicit_machine = _starts_with_machine(rest, machine)
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
    if signed is None and explicit_machine:
        # 机台别名明确写在句首时，允许跟一个纯数字：tg2 / 太鼓2 / wm3
        bare = remainder.strip()
        if _BARE_COUNT_RE.match(bare):
            signed = ("set", int(bare))
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

    为避免普通群聊误触发，只把「短、无杂散字符、且带明确报卡信号」的文本
    视为尝试。两类内容会被排除：

    - 裸数字（``6``、``666``）：没有单位或符号，是普通聊天；
    - 只含方位名 / 单位、但没有任何数字或正负号的短词（``卡``、``左``、
      ``左右``、``z``）：同样只是聊天，不构成报卡尝试。
    """
    rest = rest.strip()
    if not rest:
        return False
    if len(rest) > 12:
        return False
    if _report_residue(rest, arcade):
        return False
    # 没有任何数字或正负号 → 不可能是在报人数
    if not re.search(r"[0-9+\-]", rest):
        return False
    return _has_report_signal(rest, arcade)
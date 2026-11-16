"""配置校验：机厅 / 机台 / 方位 / 群号 / 时间范围等。"""

from __future__ import annotations

from ..utils import normalize_text, valid_group_id, valid_hm
from .models import Arcade, Machine


def _normalize_token(token: str) -> str:
    return normalize_text(token).strip()


def validate_arcade(
    arcade: Arcade,
    all_arcades: list[Arcade],
    exclude_id: str | None = None,
) -> str | None:
    """校验机厅配置，返回错误信息；通过则返回 None。"""
    if not arcade.name.strip():
        return "机厅名不能为空"

    # 名称 / 别名全局冲突
    my_name = _normalize_token(arcade.name)
    my_aliases = {_normalize_token(a) for a in arcade.aliases if a.strip()}
    for other in all_arcades:
        if exclude_id and other.id == exclude_id:
            continue
        other_name = _normalize_token(other.name)
        other_aliases = {_normalize_token(a) for a in other.aliases if a.strip()}
        if my_name and my_name in other_aliases:
            return f"机厅名「{arcade.name}」已被机厅「{other.name}」用作别名"
        for alias in my_aliases:
            if alias == other_name:
                return f"别名「{alias}」已被机厅「{other.name}」用作机厅名"
            if alias in other_aliases:
                return f"别名「{alias}」已被机厅「{other.name}」使用"
        # 自身机厅名被别的机厅别名占用
        if other_name and other_name in my_aliases:
            return f"别名「{other.name}」与机厅「{other.name}」冲突"

    # 群号格式
    for gid in arcade.group_ids:
        if not valid_group_id(gid):
            return f"群号格式无效：{gid}"

    # 正常范围
    if arcade.normal_count_min < 0:
        return "正常卡数下限不能小于 0"
    if arcade.normal_count_min > arcade.normal_count_max:
        return "正常卡数下限不能大于上限"

    # 过期小时数
    if arcade.expire_hours <= 0:
        return "过期小时数必须大于 0"

    # 开门 / 闭店时间
    if arcade.open_time or arcade.close_time:
        if not valid_hm(arcade.open_time) or not valid_hm(arcade.close_time):
            return "开门/闭店时间格式应为 HH:MM"
        if arcade.open_time >= arcade.close_time:
            return "开门时间必须早于闭店时间"

    # 机台
    return validate_machines(arcade)


def validate_machines(arcade: Arcade) -> str | None:
    machine_names: dict[str, str] = {}
    default_count = 0
    for machine in arcade.machines.values():
        if not machine.name.strip():
            return "机台名不能为空"
        if machine.is_default:
            default_count += 1
        for token in [machine.name, *machine.aliases]:
            t = _normalize_token(token)
            if not t:
                continue
            if t in machine_names:
                return f"机台别名「{token}」在机厅「{arcade.name}」内与「{machine_names[t]}」冲突"
            machine_names[t] = machine.name
        # 方位别名
        err = validate_position_aliases(machine)
        if err:
            return err
    if default_count > 1:
        return "默认机台必须唯一"
    return None


def validate_position_aliases(machine: Machine) -> str | None:
    keys: set[str] = set()
    labels: set[str] = set()
    for key, label in machine.position_aliases.items():
        k = _normalize_token(key)
        l = _normalize_token(label)
        if not k:
            return f"机台「{machine.name}」存在空方位键"
        if not l:
            return f"机台「{machine.name}」方位键「{key}」的显示名不能为空"
        if k in keys:
            return f"机台「{machine.name}」方位键「{key}」重复"
        if l in labels:
            return f"机台「{machine.name}」方位显示名「{label}」重复"
        keys.add(k)
        labels.add(l)
    if not machine.position_aliases:
        return f"机台「{machine.name}」至少需要一个方位"
    return None
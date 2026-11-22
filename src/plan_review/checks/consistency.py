"""检查 T5：前后数据矛盾（全是规则，不用大模型）。

同一份预案里，人员、电话、人数、面积会在很多地方重复出现（指挥部表、各专项的职责表、
物资表、处置卡、备忘录……）。套改时只改了一部分，就会前后对不上。真实例子：
- 案例B v2：甲当总指挥时是 158 开头的号码，当副指挥时是 135 开头的；135 那个号码同时又是乙的
- 案例A v1：人员表多出一列旧号码，一行里出现两个手机号（专家第一轮第 7 条："错位"）
- "应急联系方式：158……或"——"或"后面的号码没填
- 员工 4 人（或 6 人），却写"各岗位员工 8 人组成应急救援队伍"

子检查：
  R1 同一个人出现了不同的手机号      R2 同一个手机号属于不同的人
  R3 表格同一行里有两个不同手机号    R4 总指挥和副总指挥是同一个人
  R5 号码位数不对、号码没填完        R6 员工人数、建筑面积、注册资本、成立日期前后不一致；救援队伍人数超过员工人数
"""
from __future__ import annotations

import re
from collections import defaultdict

from plan_review.docx_reader import Paragraph
from plan_review.desensitize import _looks_like_name
from plan_review.checks.table_numbering import Issue

MOBILE = r'1[3-9]\d{9}'
MOBILE_RE = re.compile(rf'(?<!\d)({MOBILE})(?!\d)')
BAD_MOBILE_RE = re.compile(r'(?<![\d\-])(1[3-9]\d{8}|1[3-9]\d{10})(?![\d\-])')       # 10 位或 12 位
UNFINISHED_RE = re.compile(rf'(?<!\d)((?:{MOBILE})|0\d{{2,3}}-\d{{7,8}})\s*(?:或|/|、)\s*(?=$|[）)。；;，,\s])')
NAME_PHONE_RE = re.compile(rf'([一-龥]{{2,4}})\s*[（(：:，,]?\s*(?:电话|手机|联系电话)?\s*[：:]?\s*({MOBILE})(?!\d)')
ROLE_RE = re.compile(r'^(总指挥|副总指挥|副指挥|现场总执行|现场指挥)$')

NUMBER_FACTS = [
    ('员工人数', re.compile(r'(?:现有|共有)?(?:员工|职工|从业人员|在职人员)(?:共|总数|人数)?(?:为|约|有)?\s*(\d+)\s*(?:人|名)(?!组成)')),
    ('建筑面积', re.compile(r'(?:建筑面积|租用面积|承租建筑面积|使用面积)(?:约|为|共)?\s*(\d+(?:\.\d+)?)\s*(?:㎡|平方米|m2|m²)')),
    ('注册资本', re.compile(r'注册资本[：:]?\s*((?:（人民币）)?[壹贰貳叁叄參肆伍陆陸柒捌玖拾佰仟万萬亿億元整零\d.]+)')),
    ('成立日期', re.compile(r'成立(?:于|日期[：:]?)\s*(\d{4}年\d{1,2}月\d{1,2}日)')),
]
TEAM_RE = re.compile(r'(\d+)\s*人组成(?:的)?(?:应急)?(?:救援|抢险)?队伍')


CAPITAL_VARIANTS = str.maketrans({'叄': '叁', '參': '叁', '貳': '贰', '陸': '陆', '萬': '万', '億': '亿'})

# 基本情况表里"标签 | 值"形式的格子：同一个信息往往表格里一份、正文里一份
CELL_FACTS = {'成立日期': '成立日期', '注册资本': '注册资本', '员工人数': '员工人数', '职工人数': '员工人数', '从业人数': '员工人数'}


def _norm_date(s: str) -> str:
    y, m, d = re.findall(r'\d+', s)[:3]
    return f'{int(y)}年{int(m)}月{int(d)}日'


def normalize_fact(label: str, v: str) -> str:
    if label == '成立日期':
        return _norm_date(v)
    if label == '注册资本':
        v = v.translate(CAPITAL_VARIANTS)          # "叄"和"叁"都是三，底本 C里两种写法都有
        return re.sub(r'[（(]?人民币[）)]?|元|整|\s', '', v)
    if label == '员工人数':
        return re.sub(r'\D', '', v)
    return v


def fact_occurrences(paragraphs: list[Paragraph]) -> dict[str, dict[str, list[int]]]:
    """每个关键信息 -> {规范化后的值: [出现的段落]}，正文和表格都算。"""
    facts: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for p in paragraphs:
        if p.in_toc:
            continue
        for label, regex in NUMBER_FACTS:
            for v in regex.findall(p.text):
                facts[label][normalize_fact(label, v)].append(p.index)
    for i, p in enumerate(paragraphs):
        label = CELL_FACTS.get(re.sub(r'\s+', '', p.text)) if p.in_table else None
        if not label:
            continue
        right = [q for q in paragraphs[i + 1:i + 20] if q.table_id == p.table_id and q.row == p.row and q.text.strip()]
        if right and re.search(r'\d|[壹贰叁肆伍陆柒捌玖拾佰仟万]', right[0].text):
            try:
                facts[label][normalize_fact(label, right[0].text.strip())].append(right[0].index)
            except ValueError:
                pass
    return facts


def _where(idxs) -> str:
    idxs = sorted(set(idxs))
    shown = '、'.join(str(i) for i in idxs[:5])
    return f'段落 {shown}' + (f' 等 {len(idxs)} 处' if len(idxs) > 5 else '')


def check_consistency(paragraphs: list[Paragraph]) -> list[Issue]:
    by_index = {p.index: p for p in paragraphs}
    issues: list[Issue] = []

    def add(idx: int, problem: str):
        p = by_index[idx]
        issues.append(Issue('T5 前后矛盾', idx, p.section, p.text, problem))

    name_phone: dict[tuple[str, str], list[int]] = defaultdict(list)   # (姓名, 手机) -> 出现的段落
    role_name: dict[tuple[str, str], list[int]] = defaultdict(list)    # (职务, 姓名) -> 出现的段落

    # ---------- 表格：按行收集 ----------
    rows: dict[tuple, list[Paragraph]] = defaultdict(list)
    extra_phone_rows: dict[int, list] = defaultdict(list)             # 表格号 -> [(段落, 姓名, [号码…])]
    for p in paragraphs:
        if p.in_table and not p.in_toc and p.text.strip():
            rows[(p.table_id, p.row)].append(p)
    for cells in rows.values():
        cells.sort(key=lambda c: (c.col, c.index))
        names = [(c, c.text.strip()) for c in cells if _looks_like_name(c.text.strip())]
        for c in cells:                                    # "张三 13800000000" 写在同一格里
            m = re.fullmatch(rf'([一-龥]{{2,4}})\s*({MOBILE})', c.text.strip())
            if m and _looks_like_name(m.group(1)):
                name_phone[(m.group(1), m.group(2))].append(c.index)
        if len({n for _, n in names}) != 1:
            continue                                       # 一行里没有人名或有好几个人名，不配对
        name_cell, name = names[0]
        phones = []
        for c in cells:
            if c is name_cell:
                continue
            for ph in MOBILE_RE.findall(c.text):
                if ph not in phones:
                    phones.append(ph)
        if phones:
            name_phone[(name, phones[0])].append(name_cell.index)
        if len(phones) >= 2:
            extra_phone_rows[name_cell.table_id].append((name_cell.index, name, phones))
        for c in cells:
            if c.col < name_cell.col and ROLE_RE.match(c.text.strip()):
                role_name[(c.text.strip(), name)].append(name_cell.index)

    # R3 一张表报一条，列出有问题的行
    for items in extra_phone_rows.values():
        detail = '；'.join(f'{name}：{"、".join(phs)}' for _, name, phs in items)
        add(items[0][0], f'R3 这张表有 {len(items)} 行同时出现了两个不同手机号（{detail}），'
                         f'可能有一列是旧数据没删干净，导致后面的列错位')

    # ---------- 正文：姓名后面紧跟手机号 ----------
    known = {n for n, _ in name_phone}
    for p in paragraphs:
        if p.in_table or p.in_toc:
            continue
        for name, ph in NAME_PHONE_RE.findall(p.text):
            for k in known:                                # "由总指挥张三" 只取末尾的已知姓名
                if name.endswith(k):
                    name_phone[(k, ph)].append(p.index)
                    break

    # R1 / R2
    phones_of: dict[str, dict[str, list[int]]] = defaultdict(dict)
    names_of: dict[str, dict[str, list[int]]] = defaultdict(dict)
    for (name, ph), idxs in name_phone.items():
        phones_of[name][ph] = idxs
        names_of[ph][name] = idxs
    for name, phs in phones_of.items():
        if len(phs) >= 2:
            detail = '；'.join(f'{ph}（{_where(ix)}）' for ph, ix in phs.items())
            add(min(min(ix) for ix in phs.values()), f'R1 {name} 在不同地方的手机号不一样：{detail}')
    for ph, ns in names_of.items():
        if len(ns) >= 2:
            detail = '；'.join(f'{n}（{_where(ix)}）' for n, ix in ns.items())
            add(min(min(ix) for ix in ns.values()), f'R2 同一个号码 {ph} 对应了不同的人：{detail}')

    # R4 总指挥和副总指挥是同一个人
    holders: dict[str, dict[str, list[int]]] = defaultdict(dict)
    for (role, name), idxs in role_name.items():
        holders['副总指挥' if role in ('副指挥', '副总指挥') else role][name] = idxs
    for name in set(holders.get('总指挥', {})) & set(holders.get('副总指挥', {})):
        idx = min(holders['副总指挥'][name])
        add(idx, f'R4 {name} 同时是总指挥和副总指挥：总指挥不在时没有人接替')

    # R5 号码格式（同一个号码的同一种问题合并成一条）
    bad_len: dict[str, list[int]] = defaultdict(list)
    unfinished: dict[str, list[int]] = defaultdict(list)
    for p in paragraphs:
        if p.in_toc:
            continue
        for bad in BAD_MOBILE_RE.findall(p.text):
            bad_len[bad].append(p.index)
        for num in UNFINISHED_RE.findall(p.text):
            unfinished[num].append(p.index)
    for bad, idxs in bad_len.items():
        add(idxs[0], f'R5 号码 {bad} 是 {len(bad)} 位，手机号应为 11 位（{_where(idxs)}）')
    for num, idxs in unfinished.items():
        add(idxs[0], f'R5 号码 {num} 后面跟着"或""/"，但没有写第二个号码（{_where(idxs)}）')

    # R6 关键数字（正文和基本情况表都算）
    facts = fact_occurrences(paragraphs)
    for label, _ in NUMBER_FACTS:
        values = facts.get(label, {})
        if len(values) >= 2:
            detail = '；'.join(f'{v}（{_where(ix)}）' for v, ix in values.items())
            add(min(min(ix) for ix in values.values()), f'R6 {label}前后不一致：{detail}')
        if label == '员工人数' and values:
            staff = max(int(v) for v in values)
            for p in paragraphs:
                for team in TEAM_RE.findall(p.text):
                    if int(team) > staff:
                        add(p.index, f'R6 应急救援队伍 {team} 人，比员工人数 {staff} 人还多')
    return issues

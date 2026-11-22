"""检查 T3：同一组方案在不同地方列出来时，是否一致。

背景（案例A第二轮评审第 2 条）：现场处置方案的名单会出现在好几个地方——
  ① 目录  ② 综合预案正文里的列表"1）火灾事故现场处置方案；…"  ③ 附表6 预案体系表  ④ 实际章节标题
专家要求这几处名称、数量、顺序完全对齐。套改时只改了其中一处，其他地方就会对不上。

做法：
1. 以"实际章节标题"为准（文档里真正有哪些章节）
2. 把目录、正文列表、表格里的名单分别抽出来，逐个和章节对照：
   - 名字完全一样 → 对上了
   - 名字很像但不一样（比如"触电伤害事故" vs "触电事故"）→ 叫法不一致
   - 章节里根本没有 → 多出来的（常见原因：套改残留、目录没刷新）
   - 章节里有、这里没有 → 缺少
   - 都对上了但先后次序不同 → 顺序不一致
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from plan_review.docx_reader import Paragraph
from plan_review.checks.table_numbering import Issue

TAIL = r'\s*[；;。.，,]?\s*(?:-\s*\d+\s*-|\d+)?$'      # 句末标点、目录页码 "- 66 -"


@dataclass
class NameList:
    place: str                       # 目录 / 正文列表 / 表格 / 章节
    items: list[tuple[str, Paragraph]]


def _numbered_re(suffix: str) -> re.Pattern:
    return re.compile(r'^(?P<num>\d+)\s*(?P<sep>[.．、）)]?)\s*(?P<name>\S.{1,30}?' + suffix + ')' + TAIL)


def _runs(items: list[tuple[str, Paragraph]], max_gap: int = 1) -> list[list[tuple[str, Paragraph]]]:
    """把段落号挨在一起的条目切成一段一段（一段 = 一个列表）。"""
    runs: list[list] = []
    for it in items:
        if runs and it[1].index - runs[-1][-1][1].index <= max_gap:
            runs[-1].append(it)
        else:
            runs.append([it])
    return runs


def extract_lists(paragraphs: list[Paragraph], suffix: str) -> list[NameList]:
    num_re = _numbered_re(suffix)
    cell_re = re.compile(r'^(?P<name>\S.{1,28}' + suffix + ')$')
    toc, headings, body_items = [], [], []
    tables: dict[int, list] = {}

    for p in paragraphs:
        text = re.sub(r'\s+', '', p.text)
        if p.in_toc:
            m = num_re.match(text)
            if m:
                toc.append((m.group('name'), p))
        elif p.in_table:
            m = cell_re.match(text)
            if m:
                tables.setdefault(p.table_id, []).append((m.group('name'), p))
        else:
            m = num_re.match(text)
            if not m:
                continue
            if m.group('sep') in '.．' and m.group('sep'):
                headings.append((m.group('name'), p))     # "1.火灾事故现场处置方案" 是章节标题
            else:
                body_items.append((m.group('name'), p))   # "1）火灾事故现场处置方案；" 是正文列表

    lists = []
    if headings:
        lists.append(NameList('章节', headings))
    if toc:
        lists.append(NameList('目录', toc))
    for run in _runs(body_items):
        if len(run) >= 3:
            lists.append(NameList('正文列表', run))
    for items in tables.values():
        if len(items) >= 3:          # 是不是名单表，要等知道章节有多少项后再判断（见下面）
            lists.append(NameList('表格', items))
    return lists


def _short(name: str, suffix: str) -> str:
    return name.removesuffix(suffix).removesuffix('事故') or name


def check_list_consistency(paragraphs: list[Paragraph], suffix: str = '现场处置方案') -> tuple[list[NameList], list[Issue]]:
    lists = extract_lists(paragraphs, suffix)
    ref = next((l for l in lists if l.place == '章节'), None)
    if ref is None:
        return lists, []
    ref_names = [n for n, _ in ref.items]
    # 处置卡表格里也会出现方案名（如火灾章的"可燃固体/可燃液体/电气火灾"三张卡），
    # 名单表应该列出大部分方案，所以至少要有章节数的一半
    lists = [l for l in lists if l.place != '表格' or len(l.items) >= max(3, len(ref_names) // 2 + 1)]
    issues = []

    def add(p: Paragraph, problem: str):
        issues.append(Issue('T3 清单一致性', p.index, p.section, p.text, problem))

    for lst in lists:
        if lst is ref:
            continue
        where = lst.place if lst.place == '目录' else f'{lst.place}（{lst.items[0][1].section}）'
        matched: dict[int, int] = {}            # 本列表第 i 项 -> 章节第 j 项
        # 第一轮：名字完全一样的先配上
        for i, (name, _) in enumerate(lst.items):
            if name in ref_names and ref_names.index(name) not in matched.values():
                matched[i] = ref_names.index(name)
        # 第二轮：剩下的，在还没被配走的章节里找最像的（每次挑全场最像的一对，避免先到先得配错）
        while True:
            pairs = [(SequenceMatcher(None, lst.items[i][0], ref_names[j]).ratio(), i, j)
                     for i in range(len(lst.items)) if i not in matched
                     for j in range(len(ref_names)) if j not in matched.values()]
            if not pairs:
                break
            score, i, j = max(pairs)
            if score < 0.6:
                break
            matched[i] = j
            add(lst.items[i][1], f'叫法不一致：{where}写"{lst.items[i][0]}"，章节标题是"{ref_names[j]}"')
        for i, (name, p) in enumerate(lst.items):
            if i not in matched:
                add(p, f'多出来的：{where}有"{name}"，但文档里没有这个章节（可能是套改残留或目录没刷新）')
        for j, r in enumerate(ref_names):
            if j not in matched.values():
                add(lst.items[0][1], f'缺少：章节里有"{r}"，{where}里没有')
        order = [matched[i] for i in sorted(matched)]
        if order != sorted(order):
            mine = '、'.join(_short(ref_names[j], suffix) for j in order)
            theirs = '、'.join(_short(ref_names[j], suffix) for j in sorted(order))
            add(lst.items[0][1], f'顺序不一致：{where}的顺序是 {mine}；章节顺序是 {theirs}')
    return lists, issues

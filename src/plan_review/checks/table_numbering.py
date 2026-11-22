"""检查 T1：表格编号是否连续、是否重复、格式是否统一。

思路（全是确定性规则，不用 AI）：
1. 找出所有表题段落，比如"表1-2 应急职能小组组成及职责""附表3 …""附录A表6 …"
2. 把它们按"编号体系"分组：附录A表N 一组、附表N 一组、第 C 章的表C-N 一组……
3. 每组按出现顺序检查：应该是 1, 2, 3 …；出现跳号、重复、倒序就报出来
4. 分章编号（表C-N）的章号只能往后走，突然从 5 跳回 1 说明是从别的章复制过来没改
5. 同一个分部（如附件1）里，大家都用"附表N"，偏偏有一个写成"表2.7-2"，说明编号格式不统一
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from plan_review.docx_reader import Paragraph

CAPTION_RE = re.compile(
    r'^(?P<prefix>附录\s*(?P<appx>[A-Z])\s*表|附表|表)\s*'
    r'(?P<num>\d+(?:\s*[.\-－—]\s*\d+)*)\s*(?P<title>.*)$'
)
# 兜底：以"表"开头、但编号不是上面任何一种格式的表题，比如"表附A-1 …"
ODD_CAPTION_RE = re.compile(r'^表\s*(?P<code>附[A-Z0-9][A-Z0-9.\-－]*)\s*(?P<title>\S.*)$')


@dataclass
class Caption:
    para: Paragraph
    label: str      # 规范化后的编号，如 "附录A表6"、"表1-2"
    kind: str       # 编号格式：附录表 / 附表 / 分章表 / 节号表 / 简单表
    series: str     # 编号体系，同一体系内应连续，如 "附录A表"、"表1-"
    number: int     # 体系内的序号
    chapter: int | None = None   # 分章表的章号


@dataclass
class Issue:
    check: str
    para_index: int
    section: str
    text: str
    problem: str


def find_captions(paragraphs: list[Paragraph]) -> list[Caption]:
    caps = []
    for p in paragraphs:
        if p.in_table or p.in_toc or len(p.text) > 60:
            continue
        m = CAPTION_RE.match(p.text)
        if not m:
            odd = ODD_CAPTION_RE.match(p.text)
            if odd:   # 编号格式认不出来：单独成一个体系，不参与连续性检查，但参与格式统一检查
                code = odd.group('code')
                caps.append(Caption(p, f'表{code}', '其他格式', f'其他:{p.index}', 1))
            continue
        if not m.group('title'):   # 没有标题文字的多半是正文里的"表1"引用
            continue
        num = re.sub(r'\s+', '', m.group('num'))
        num = re.sub(r'[－—]', '-', num)
        prefix = m.group('prefix')
        if m.group('appx'):
            a = m.group('appx')
            caps.append(Caption(p, f'附录{a}表{num}', '附录表', f'附录{a}表', int(num)))
        elif prefix == '附表':
            caps.append(Caption(p, f'附表{num}', '附表', '附表', int(num)))
        elif re.fullmatch(r'\d+-\d+', num):
            c, n = map(int, num.split('-'))
            caps.append(Caption(p, f'表{num}', '分章表', f'表{c}-', n, chapter=c))
        elif '-' in num:            # 2.7-2 这种带节号的
            head, n = num.rsplit('-', 1)
            caps.append(Caption(p, f'表{num}', '节号表', f'表{head}-', int(n)))
        else:
            caps.append(Caption(p, f'表{num}', '简单表', '表', int(num)))
    return caps


def check_table_numbering(paragraphs: list[Paragraph]) -> tuple[list[Caption], list[Issue]]:
    caps = find_captions(paragraphs)
    problems: dict[int, list[str]] = defaultdict(list)   # 段落号 -> 问题描述

    # 规则 1：每个编号体系内连续、不重复、不倒序，并且从 1 开始
    by_series: dict[str, list[Caption]] = defaultdict(list)
    for c in caps:
        by_series[c.series].append(c)
    for series, items in by_series.items():
        prev = 0
        for c in items:
            n = c.number
            if n == prev + 1:
                pass
            elif n == prev:
                problems[c.para.index].append(f'编号重复：前面已经有{c.label}')
            elif n > prev + 1:
                missing = '、'.join(f'{series}{k}' for k in range(prev + 1, n))
                problems[c.para.index].append(f'跳号：缺少 {missing}')
            else:
                problems[c.para.index].append(f'倒序：{series}{prev} 之后出现 {c.label}')
            prev = max(prev, n)

    # 规则 2：分章编号的章号只能往后走（从 5 跳回 1 多半是复制别的章没改）
    max_chapter = 0
    for c in caps:
        if c.chapter is None:
            continue
        if c.chapter < max_chapter:
            problems[c.para.index].append(
                f'章号倒退：前面已经到第{max_chapter}章，这里又出现第{c.chapter}章的编号')
        max_chapter = max(max_chapter, c.chapter)

    # 规则 3：同一分部里编号格式应统一（少数派就是可疑的）
    by_section: dict[str, list[Caption]] = defaultdict(list)
    for c in caps:
        by_section[c.para.section].append(c)
    for section, items in by_section.items():
        kinds = Counter(c.kind for c in items)
        if len(kinds) < 2:
            continue
        major, major_n = kinds.most_common(1)[0]
        for c in items:
            if c.kind != major and kinds[c.kind] < major_n:
                example = next(x.label for x in items if x.kind == major)
                problems[c.para.index].append(
                    f'格式不统一：{section}里其他表都用"{example}"这种编号，这里却是"{c.label}"')

    issues = [
        Issue('T1 表格编号', c.para.index, c.para.section, c.para.text, '；'.join(problems[c.para.index]))
        for c in caps if problems.get(c.para.index)
    ]
    return caps, issues

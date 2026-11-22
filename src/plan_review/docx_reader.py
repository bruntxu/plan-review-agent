"""把 .docx 读成按文档顺序排列的段落列表。

只用标准库（zipfile + xml），不依赖 python-docx。
.docx 本质是一个 zip 包，正文在 word/document.xml 里：
  <w:body> 下面依次是段落 <w:p>、表格 <w:tbl>、内容控件 <w:sdt>（自动目录通常放在这里），
  段落里的文字在 <w:t> 中。
"""
from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

# 识别"附件1 生产经营单位概况""附录A 风险评估报告"这类分部标题（后面紧跟"表"的不算，那是表题）
SECTION_RE = re.compile(r'^(附件\s*\d+|附录\s*[A-Z])(?!\s*表)')


@dataclass
class Paragraph:
    index: int                  # 在文档中的顺序号，用于定位
    text: str                   # 段落纯文本
    in_table: bool              # 是否在表格单元格里
    section: str                # 所在分部：正文 / 附件1 / 附录A ...
    in_toc: bool = False        # 是否在自动目录里
    table_id: int | None = None  # 在第几个表格里（同一表格的单元格编号相同）
    row: int | None = None      # 表格里的第几行（从 0 开始）
    col: int | None = None      # 表格里的第几列（从 0 开始）


def _text(p: ET.Element) -> str:
    return ''.join(t.text or '' for t in p.iter(W + 't')).strip()


def _walk(container: ET.Element, in_toc: bool, counter: list[int]):
    """按顺序产出 (段落元素, 是否在目录里, 表格编号, 行, 列)。"""
    for el in container:
        if el.tag == W + 'p':
            yield el, in_toc, None, None, None
        elif el.tag == W + 'tbl':
            counter[0] += 1
            tid = counter[0]
            for r, tr in enumerate(el.findall(W + 'tr')):
                for c, tc in enumerate(tr.findall(W + 'tc')):
                    for p in tc.iter(W + 'p'):      # 单元格里嵌套的表格也算在这一格
                        yield p, in_toc, tid, r, c
        elif el.tag == W + 'sdt':
            content = el.find(W + 'sdtContent')
            if content is not None:
                yield from _walk(content, True, counter)


def paragraph_elements(root: ET.Element) -> list[ET.Element]:
    """和 read_paragraphs 完全相同的顺序返回段落元素，注入错误时用来按段落号找到要改的那一段。"""
    return [p for p, *_ in _walk(root.find(W + 'body'), False, [0])]


def read_paragraphs(path: str) -> list[Paragraph]:
    xml = zipfile.ZipFile(path).read('word/document.xml')
    body = ET.fromstring(xml).find(W + 'body')

    paragraphs = []
    section = '正文'
    for i, (p, in_toc, table_id, row, col) in enumerate(_walk(body, False, [0])):
        text = _text(p)
        if table_id is None and not in_toc:
            m = SECTION_RE.match(text)
            if m and len(text) < 40:
                section = re.sub(r'\s+', '', m.group(1))
        paragraphs.append(Paragraph(i, text, table_id is not None, section, in_toc, table_id, row, col))
    return paragraphs


def cell_value(paragraphs: list[Paragraph], label: str) -> str | None:
    """在表格里找"标签 | 值"这样的格子，比如 cell_value(ps, '经营范围') 返回右边那一格的文字。"""
    for i, p in enumerate(paragraphs):
        if p.in_table and re.sub(r'\s+', '', p.text) == label:
            same_row = [q for q in paragraphs[i + 1:i + 40]
                        if q.table_id == p.table_id and q.row == p.row and q.col > p.col and q.text]
            if same_row:
                return ''.join(q.text for q in same_row if q.col == same_row[0].col)
    return None

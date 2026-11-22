"""检查 T9：Word 域（目录、页码引用等）是否完整。

背景（2026-07 案例B预案踩过的坑）：
Word 里的"域"由三个标记组成：begin → separate → end，常常分散在好几个文字片段里。
改文档时如果删掉了其中一部分，就会留下没闭合的域，WPS/Word 打开后从那里开始不再显示，
181 页的文档只显示 7 页。python-docx 照样能读写，所以光靠"能打开"发现不了。

做法：按文档顺序扫一遍所有域标记，用栈配对 begin/end（域可以嵌套，也可以跨段落）。
- end 前面没有 begin → 多余的 end
- 扫完还有没闭合的 begin → 报告它在哪个段落开始
"""
from __future__ import annotations

import zipfile
import xml.etree.ElementTree as ET

from plan_review.checks.table_numbering import Issue

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def check_fields_xml(xml: bytes) -> tuple[dict, list[Issue]]:
    body = ET.fromstring(xml).find(W + 'body')
    stack: list[tuple[int, str]] = []        # 未闭合的 begin：(段落号, 段落文字预览)
    counts = {'begin': 0, 'separate': 0, 'end': 0}
    issues: list[Issue] = []

    par_no, preview = -1, ''
    for el in body.iter():                   # iter() 按文档顺序遍历所有元素
        if el.tag == W + 'p':
            par_no += 1
            preview = ''.join(t.text or '' for t in el.iter(W + 't')).strip()[:40]
        elif el.tag == W + 'fldChar':
            kind = el.get(W + 'fldCharType')
            counts[kind] = counts.get(kind, 0) + 1
            if kind == 'begin':
                stack.append((par_no, preview))
            elif kind == 'end':
                if stack:
                    stack.pop()
                else:
                    issues.append(Issue('T9 域完整性', par_no, '', preview,
                                        '多余的域结束标记（前面没有对应的开始）'))
    for no, text in stack:
        issues.append(Issue('T9 域完整性', no, '', text,
                            '域没有闭合：Word/WPS 打开后可能从这里开始不再显示后面的内容'))
    return counts, issues


def check_field_integrity(path: str) -> tuple[dict, list[Issue]]:
    return check_fields_xml(zipfile.ZipFile(path).read('word/document.xml'))

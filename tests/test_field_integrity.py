"""直接运行：python tests/test_field_integrity.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from plan_review.checks.field_integrity import check_fields_xml  # noqa: E402

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def doc(*paragraphs):
    return f'<w:document {NS}><w:body>{"".join(paragraphs)}</w:body></w:document>'.encode()


def p(text='', *marks):
    runs = ''.join(f'<w:r><w:fldChar w:fldCharType="{m}"/></w:r>' for m in marks)
    return f'<w:p><w:r><w:t>{text}</w:t></w:r>{runs}</w:p>'


def test_complete_field_spanning_paragraphs():
    # 目录域：第一段 begin+separate，最后一段 end
    counts, issues = check_fields_xml(doc(p('目录', 'begin', 'separate'), p('1 总则'), p('2 组织', 'end')))
    assert issues == [] and counts['begin'] == counts['end'] == 1


def test_nested_fields():
    _, issues = check_fields_xml(doc(p('目录', 'begin', 'separate'), p('4.1 适用范围', 'begin', 'separate', 'end'), p('', 'end')))
    assert issues == []


def test_broken_field_is_located():
    # 案例B的真实情况：目录条目里的 PAGEREF 域被删掉了后半段
    _, issues = check_fields_xml(doc(p('第一篇'), p('4.1适用范围- 57 -', 'begin', 'separate'), p('正文')))
    assert len(issues) == 1 and issues[0].text.startswith('4.1适用范围') and '没有闭合' in issues[0].problem


def test_stray_end():
    _, issues = check_fields_xml(doc(p('正文', 'end')))
    assert len(issues) == 1 and '多余' in issues[0].problem


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('通过', name)

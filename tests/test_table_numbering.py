"""用手写的小例子测试规则，不依赖真实文档。直接运行：python tests/test_table_numbering.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from plan_review.docx_reader import Paragraph                       # noqa: E402
from plan_review.checks.table_numbering import check_table_numbering  # noqa: E402


def make(lines):
    """lines: [(所在部分, 文本)]"""
    return [Paragraph(i, t, False, s) for i, (s, t) in enumerate(lines)]


def problems(lines):
    return [i.problem for i in check_table_numbering(make(lines))[1]]


def test_clean_document_has_no_issue():
    assert problems([
        ('正文', '表1-1 火灾事故类型一览表'),
        ('正文', '表1-2 应急职能小组'),
        ('正文', '表2-1 应急职能小组'),
        ('附录A', '附录A表1 人的不安全行为'),
        ('附录A', '附录A表2 隐患表'),
    ]) == []


def test_gap_is_reported():
    p = problems([('附录A', '附录A表1 人的不安全行为'),
                  ('附录A', '附录A表2 隐患表'),
                  ('附录A', '附录A表4 汇总表')])
    assert len(p) == 1 and '缺少 附录A表3' in p[0]


def test_chapter_copied_from_earlier_chapter():
    p = problems([('正文', '表5-1 危化品事故类型'), ('正文', '表1-2 应急职能小组'),
                  ('正文', '表1-1 火灾'), ])
    assert any('章号倒退' in x for x in p)


def test_mixed_format_in_same_section():
    p = problems([('附件1', '表 2.7-2本项目的主要建（构）筑物'),
                  ('附件1', '附表2周边环境情况'),
                  ('附件1', '附表3原料一览表')])
    assert any('格式不统一' in x for x in p)
    assert any('缺少 附表1' in x for x in p)


def test_unrecognised_format_is_flagged():
    # 案例A v3 的真实情况：附录A里其他表都是"附录A表N"，有一张写成了"表附A-1"
    p = problems([('附录A', '表附A-1主要危险、有害因素及采取的安全措施一览表'),
                  ('附录A', '附录A表1 人的不安全行为'),
                  ('附录A', '附录A表2 隐患表')])
    assert len(p) == 1 and '格式不统一' in p[0]


def test_reference_in_text_is_not_a_caption():
    # 正文里的"见表1-2所示"不应被当成表题
    assert problems([('正文', '表1-1 火灾'), ('正文', '详见表1-2所示，各小组职责如下')]) == []


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('通过', name)

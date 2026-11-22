"""直接运行：python tests/test_desensitize.py
注意：测试里全部用虚构的公司、人名和号码，不能出现真实客户信息（这些文件以后会公开）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from plan_review.docx_reader import Paragraph   # noqa: E402
from plan_review.desensitize import Masker      # noqa: E402


def para(i, text, table=None, row=None, col=None):
    return Paragraph(i, text, table is not None, '正文', False, table, row, col)


DOC = [
    para(0, '成都甲乙科技有限公司生产安全事故应急预案'),
    para(1, '根据成都甲乙科技有限公司实际情况，与成都丙丁企业管理有限公司签订互救协议。'),
    para(2, '成都甲乙科技有限公司法定代表人：王小明，统一社会信用代码：91510100MA6ABCDE1X。'),
    para(3, '地址：四川省成都市高新区天府大道北段1700号A栋5楼。'),
    para(4, '总指挥', 1, 0, 0), para(5, '王小明', 1, 0, 1), para(6, '13800001111', 1, 0, 2),
    para(7, '通讯组组长', 1, 1, 0), para(8, '李二', 1, 1, 1), para(9, '13900002222', 1, 1, 2),
    para(10, '应急管理局电话 028-12345678；火警 119。'),
]


def test_mask_and_unmask_roundtrip():
    m = Masker(DOC)
    for p in DOC:
        masked = m.mask(p.text)
        assert m.unmask(masked) == p.text
        assert m.leaks(masked) == []


def test_main_company_is_most_frequent():
    m = Masker(DOC)
    assert m.forward['成都甲乙科技有限公司'] == '【公司1】'
    assert m.forward['成都丙丁企业管理有限公司'] == '【公司2】'   # 前面粘着的"与"被截掉


def test_what_gets_sent():
    m = Masker(DOC)
    assert m.mask(DOC[2].text) == '【公司1】法定代表人：【人名2】，统一社会信用代码：【信用代码1】。'
    assert m.mask('总指挥王小明，手机13800001111') == '总指挥【人名2】，手机【手机1】'
    assert '119' in m.mask(DOC[10].text) and '【电话1】' in m.mask(DOC[10].text)
    assert '天府大道' not in m.mask(DOC[3].text)


def test_roles_are_not_names():
    m = Masker(DOC)
    assert '总指挥' not in m.forward and '通讯组组长' not in m.forward


def test_ordinary_words_after_role_are_not_names():
    # 真实踩坑：之前"总指挥批准""事故报告"里的"批准""报告"被当成人名，替换后文字乱了
    doc = DOC + [para(11, '由总指挥批准后发布，并向总指挥报告。'), para(12, '水枪头', 3, 0, 0), para(13, '13800001111', 3, 0, 1)]
    m = Masker(doc)
    assert m.mask('由总指挥批准后发布，并向总指挥报告。') == '由总指挥批准后发布，并向总指挥报告。'
    assert '水枪头' not in m.forward


def test_short_name_and_brand():
    doc = DOC + [para(11, '甲乙科技司发[2026]1号'), para(12, '公司租用甲乙产业园5楼')]
    m = Masker(doc)
    assert m.mask('甲乙科技司发[2026]1号') == '【公司1简称】司发[2026]1号'
    assert m.mask('公司租用甲乙产业园5楼') == '公司租用【公司1字号】产业园5楼'
    assert m.unmask(m.mask('公司租用甲乙产业园5楼')) == '公司租用甲乙产业园5楼'


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('通过', name)

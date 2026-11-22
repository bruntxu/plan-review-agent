"""用假的大模型测试 T4 的流程（不联网、不花钱）。直接运行：python tests/test_template_residue.py
测试数据全部虚构。"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from plan_review.docx_reader import Paragraph                        # noqa: E402
from plan_review.llm import FakeLLM                                   # noqa: E402
from plan_review.checks.template_residue import check_template_residue  # noqa: E402


def para(i, text, table=None, row=None, col=None):
    return Paragraph(i, text, table is not None, '附件1', False, table, row, col)


DOC = [
    para(0, '成都甲乙科技有限公司生产安全事故应急预案'),
    para(1, '所属行业', 1, 0, 0), para(2, '研究和试验发展', 1, 0, 1),
    para(3, '经营范围', 1, 1, 0), para(4, '医药中间体技术研发', 1, 1, 1),
    para(5, '总指挥', 2, 0, 0), para(6, '王小明', 2, 0, 1), para(7, '13800001111', 2, 0, 2),
    para(8, '本公司主要从事智能配电设备的研发等，厂房火灾类别设计为戊类。'),
    para(9, '总指挥王小明（13800001111）负责全面指挥，成都甲乙科技有限公司各部门配合。'),
]


def fake_reply(user: str) -> dict:
    """假模型：看到"配电设备"就报那一行；另外故意编一个不存在的段落号 999、
    一条原文里没有的引用、一条把握为"中"的结果。"""
    m = re.search(r'\[(\d+)\] [^\n]*配电设备', user)
    n = re.search(r'\[(\d+)\] 总指挥', user)
    findings = [{'id': 999, 'quote': '配电', 'reason': '瞎编的段落号', 'confidence': '高'}]
    if m:
        findings.append({'id': int(m.group(1)), 'quote': '主要从事智能配电设备的研发',
                         'reason': '【公司1】做医药研发，不做配电设备', 'confidence': '高'})
        findings.append({'id': int(m.group(1)), 'quote': '锅炉房位于厂区东侧', 'reason': '编造的引用', 'confidence': '高'})
    if n:
        findings.append({'id': int(n.group(1)), 'quote': '负责全面指挥', 'reason': '不太确定', 'confidence': '中'})
    return {'findings': findings}


def test_finds_residue_and_maps_back():
    llm = FakeLLM(fake_reply)
    issues = check_template_residue(DOC, llm)
    sure = [i for i in issues if i.check == 'T4 套改残留']
    unsure = [i for i in issues if i.check == 'T4 待确认']
    assert len(sure) == 1 and len(unsure) == 1        # 999 和编造的引用都被丢弃
    assert sure[0].para_index == 8
    assert sure[0].problem == '"主要从事智能配电设备的研发"：成都甲乙科技有限公司做医药研发，不做配电设备'   # 占位符换回了真名
    assert unsure[0].para_index == 9


def test_profile_has_region_and_extra():
    llm = FakeLLM(lambda u: {'findings': []})
    doc = DOC + [para(10, '公司地址：四川省成都市高新区天府大道北段1700号。')]
    check_template_residue(doc, llm, extra_profile='实验室研发，无生产车间')
    assert '所在地区：四川省成都市高新区' in llm.received[0]
    assert '补充情况：实验室研发，无生产车间' in llm.received[0]


def test_nothing_sensitive_is_sent():
    llm = FakeLLM(fake_reply)
    check_template_residue(DOC, llm)
    sent = '\n'.join(llm.received)
    for secret in ('成都甲乙科技有限公司', '王小明', '13800001111'):
        assert secret not in sent
    assert '医药中间体技术研发' in sent and '研究和试验发展' in sent   # 画像发出去了


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('通过', name)

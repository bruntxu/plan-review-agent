"""直接运行：python tests/test_consistency.py
测试数据全部虚构（人名、号码都是编的），场景照着真实文档里遇到的问题来。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from plan_review.docx_reader import Paragraph                  # noqa: E402
from plan_review.checks.consistency import check_consistency   # noqa: E402


class Doc:
    def __init__(self):
        self.ps, self.table = [], 0

    def text(self, t):
        self.ps.append(Paragraph(len(self.ps), t, False, '正文'))
        return self

    def table_rows(self, *rows):
        self.table += 1
        for r, cells in enumerate(rows):
            for c, t in enumerate(cells):
                self.ps.append(Paragraph(len(self.ps), t, True, '正文', False, self.table, r, c))
        return self


def problems(doc):
    return [i.problem for i in check_consistency(doc.ps)]


HEADER = ('应急岗位', '职位', '姓名', '职务', '手机')


def test_clean():
    d = (Doc().text('公司现有员工6人。建筑面积160平方米。')
         .table_rows(HEADER, ('应急指挥部', '总指挥', '王小明', '总经理', '13800001111'),
                     ('应急指挥部', '副指挥', '李二', '经理', '13900002222'))
         .text('总指挥王小明（13800001111）负责全面指挥。'))
    assert problems(d) == []


def test_same_person_two_phones_and_shared_phone():
    # 照着案例B v2：总指挥、副指挥是同一个人但号码不同，副指挥的号码又是另一个人的
    d = Doc().table_rows(HEADER, ('应急指挥部', '总指挥', '王小明', '董事长', '13800001111'),
                         ('应急指挥部', '副指挥', '王小明', '总经理', '13900002222'),
                         ('应急指挥部', '现场总执行', '赵六', '副总经理', '13900002222'))
    p = problems(d)
    assert any(x.startswith('R1 王小明') for x in p)
    assert any(x.startswith('R2 同一个号码 13900002222') for x in p)
    assert any(x.startswith('R4 王小明 同时是总指挥和副总指挥') for x in p)


def test_extra_old_phone_column():
    # 照着案例A v1：人员表多出一列旧号码
    d = Doc().table_rows(HEADER, ('应急救援小组', '通讯联络组组员', '钱七', '员工', '13700003333', '15000004444'))
    p = problems(d)
    assert len(p) == 1 and p[0].startswith('R3 这张表有 1 行同时出现了两个不同手机号')


def test_unfinished_and_bad_length():
    d = Doc().text('应急联系方式：13800001111或').text('24小时值班电话：13800001111/。').text('联系人电话1380000111。')
    p = problems(d)
    assert sum('没有写第二个号码' in x for x in p) == 1     # 同一个号码的两处合并成一条
    assert any('没有写第二个号码（段落 0、1）' in x for x in p)
    assert any('是 10 位' in x for x in p)


def test_numbers_disagree_and_team_too_big():
    d = (Doc().text('公司现有员工4人，均为研发人员。').text('公司现有员工5人。')
         .text('成立于2020年04月22日。').text('本公司成立于2020年4月22日')     # 写法不同但是同一天，不算矛盾
         .text('公司建立了由总经理以及各岗位员工8人组成应急救援队伍。'))
    p = problems(d)
    assert any(x.startswith('R6 员工人数前后不一致') for x in p)
    assert not any('成立日期' in x for x in p)
    assert any('8 人，比员工人数 5 人还多' in x for x in p)


def test_table_cell_vs_text():
    # 营业执照信息常常表格里抄一遍、正文里再写一遍；写法不同（09 日 / 9 日、带"（人民币）"）不算矛盾
    d = (Doc().text('本公司成立于2020年12月9日，注册资本：壹佰万元整。')
         .table_rows(('成立日期', '2020年12月09日'), ('注册资本', '壹佰万元整（人民币）')))
    assert problems(d) == []
    d = (Doc().text('本公司成立于2020年12月9日，注册资本：壹佰万元整。')
         .table_rows(('成立日期', '2020年12月19日'), ('注册资本', '贰佰万元整（人民币）')))
    p = problems(d)
    assert any(x.startswith('R6 成立日期前后不一致') for x in p)
    assert any(x.startswith('R6 注册资本前后不一致') for x in p)
    # 真实踩坑：底本 C里正文写"叄"、表格写"叁"，是同一个数
    d = Doc().text('注册资本：壹亿零叄佰万元整，地址：某市。').table_rows(('注册资本', '壹亿零叁佰万元整（人民币）'))
    assert problems(d) == []


def test_name_phone_in_text():
    d = (Doc().table_rows(HEADER, ('应急指挥部', '总指挥', '王小明', '总经理', '13800001111'))
         .text('由总指挥王小明（13800009999）宣布启动预案。'))
    p = problems(d)
    assert len(p) == 1 and p[0].startswith('R1 王小明')


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('通过', name)

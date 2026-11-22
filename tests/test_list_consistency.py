"""直接运行：python tests/test_list_consistency.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from plan_review.docx_reader import Paragraph                        # noqa: E402
from plan_review.checks.list_consistency import check_list_consistency  # noqa: E402

S = '现场处置方案'


def build(toc=(), body=(), heads=(), table=()):
    """按 目录 → 正文列表 → 章节 → 表格 的顺序拼一份假文档。"""
    ps, i = [], 0
    for t in toc:
        ps.append(Paragraph(i, t, False, '正文', in_toc=True)); i += 1
    i += 5
    for t in body:
        ps.append(Paragraph(i, t, False, '正文')); i += 1
    for t in heads:
        i += 20
        ps.append(Paragraph(i, t, False, '正文'))
    i += 50
    for t in table:
        i += 3
        ps.append(Paragraph(i, t, True, '附件3', table_id=7))
    return ps


HEADS = [f'{k}.{n}事故{S}' for k, n in enumerate(['火灾', '触电', '坍塌', '灼烫', '危险化学品泄漏'], 1)]


def problems(**kw):
    return [i.problem for i in check_list_consistency(build(heads=HEADS, **kw))[1]]


def test_all_consistent():
    toc = [h + '- 66 -' for h in HEADS]
    body = [f'{k}）{h.split(".", 1)[1]}；' for k, h in enumerate(HEADS, 1)]
    table = [h.split('.', 1)[1] for h in HEADS]
    assert problems(toc=toc, body=body, table=table) == []


def test_variant_name():
    body = [f'1）火灾事故{S}；', f'2）触电伤害事故{S}；', f'3）坍塌事故{S}；', f'4）灼烫事故{S}；', f'5）危险化学品泄漏事故{S}。']
    p = problems(body=body)
    assert len(p) == 1 and '叫法不一致' in p[0] and '触电伤害' in p[0]


def test_stale_toc_extra_and_missing():
    # 案例A v2 的真实情况：目录第 12 项还是"起重伤害"，没有"危险化学品泄漏"
    toc = [f'1.火灾事故{S}- 66 -', f'2.触电事故{S}- 70 -', f'3.坍塌事故{S}- 80 -', f'4.灼烫事故{S}- 90 -', f'5起重伤害事故{S}- 99 -']
    p = problems(toc=toc)
    assert any('多出来的' in x and '起重伤害' in x for x in p)
    assert any('缺少' in x and '危险化学品泄漏' in x for x in p)


def test_exact_match_wins_over_fuzzy():
    # 案例B v3 的真实情况：目录里的"车辆伤害"不能抢走"其它伤害"，后者目录里另有一项完全一样的
    heads = [f'1.火灾事故{S}', f'2.厂（场）内车辆致害事故{S}', f'3.其它伤害事故{S}']
    toc = [f'1.火灾事故{S}- 66 -', f'2.车辆伤害事故{S}- 87 -', f'3.其它伤害事故{S}- 96 -']
    p = [i.problem for i in check_list_consistency(build(heads=heads, toc=toc))[1]]
    assert len(p) == 1 and '车辆伤害' in p[0] and '厂（场）内车辆致害' in p[0]


def test_order_mismatch():
    body = [f'1）火灾事故{S}；', f'2）危险化学品泄漏事故{S}；', f'3）触电事故{S}；', f'4）坍塌事故{S}；', f'5）灼烫事故{S}。']
    p = problems(body=body)
    assert len(p) == 1 and '顺序不一致' in p[0]


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('通过', name)

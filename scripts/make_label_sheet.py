"""把 T4 的结果做成一张标注表：每条附上我的初判，留一列给人工确认。
标注结果就是评测用的"标准答案"，用来算准确率。输出在 output/（含真实客户内容，不公开）。

用法：python scripts/make_label_sheet.py 审查报告.md 标注表.md
"""
import sys

# 2026-11-22 对案例A v2（加补充画像）结果的初判
#   真残留：具体的事实与本单位矛盾（部门、设备、设施、物料、人数……）
#   模板措辞："厂区""班组长""生产区"这类通用字眼，严格说不贴切，但评审一般不追究
#   误报：评审要求保留的模板章节内容（如粉尘爆炸专项），或说的就是本单位
LABELS = {
    '真残留': {267, 581, 847, 857, 895, 905, 908, 917, 1084, 1115, 1132, 1151, 1295, 1797, 1922, 1952, 2048,
             2163, 2198, 2410, 2417, 2609, 2761, 2791, 2870, 2847, 3317, 3237, 3241, 4109, 4543, 4594, 4986,
             4990, 4989, 5003, 5066, 5422},
    '模板措辞': {1011, 1230, 1231, 1232, 1410, 1411, 1412, 1612, 1692, 1821, 2744, 2787, 2930, 4941, 4985, 5064},
    '误报': {347, 1238, 1240, 1242, 1246, 1268},
}


def label_of(idx: int) -> str:
    return next((k for k, v in LABELS.items() if idx in v), '未标注')


rows = []
for line in open(sys.argv[1], encoding='utf-8'):
    if line.startswith('| T4 '):
        c = [x.strip() for x in line.split('|')]
        rows.append((c[1], int(c[2]), c[3], c[4], c[5]))

with open(sys.argv[2], 'w', encoding='utf-8') as out:
    print('# T4 套改残留标注表\n', file=out)
    print('"我的初判"是我先标的。你只需要在"你的判断"一列里改掉你不同意的那些，同意的可以留空。\n', file=out)
    print('| 把握 | 段落 | 部分 | 原文 | 模型理由 | 我的初判 | 你的判断 |\n|---|---|---|---|---|---|---|', file=out)
    for check, idx, sec, text, reason in rows:
        sure = '高' if check == 'T4 套改残留' else '中'
        print(f'| {sure} | {idx} | {sec} | {text} | {reason} | {label_of(idx)} | |', file=out)
    sure_rows = [r for r in rows if r[0] == 'T4 套改残留']
    counts = {k: sum(label_of(r[1]) == k for r in sure_rows) for k in ('真残留', '模板措辞', '误报', '未标注')}
    print(f'\n把握为"高"的 {len(sure_rows)} 条，初判：{counts}', file=out)
print('rows', len(rows))

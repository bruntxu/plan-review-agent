"""命令行入口：检查一份预案的表格编号。

用法：
    python scripts/check_tables.py 预案.docx [输出报告.md]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from plan_review.docx_reader import read_paragraphs              # noqa: E402
from plan_review.checks.table_numbering import check_table_numbering  # noqa: E402


def main() -> None:
    doc = sys.argv[1]
    out = open(sys.argv[2], 'w', encoding='utf-8') if len(sys.argv) > 2 else sys.stdout

    paragraphs = read_paragraphs(doc)
    caps, issues = check_table_numbering(paragraphs)

    print(f'# 表格编号检查：{Path(doc).name}\n', file=out)
    print(f'共读取 {len(paragraphs)} 个段落，识别出 {len(caps)} 个表题，发现 **{len(issues)}** 处问题。\n', file=out)
    if issues:
        print('| 段落号 | 所在部分 | 表题 | 问题 |\n|---|---|---|---|', file=out)
        for i in issues:
            print(f'| {i.para_index} | {i.section} | {i.text} | {i.problem} |', file=out)
    print('\n<details><summary>识别出的全部表题</summary>\n', file=out)
    for c in caps:
        print(f'- [{c.para.section}] {c.para.text}', file=out)
    print('\n</details>', file=out)


if __name__ == '__main__':
    main()

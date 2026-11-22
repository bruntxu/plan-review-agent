"""命令行入口：对一份预案跑全部已实现的检查，输出一份审查报告。

用法：
    python scripts/review.py 预案.docx [输出报告.md] [--llm]
不加 --llm 只跑规则检查（免费）；加了才会脱敏后调用 DeepSeek 跑 T4。
"""
import argparse
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from plan_review.pipeline import run_all                                  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('doc')
    ap.add_argument('out', nargs='?')
    ap.add_argument('--llm', action='store_true')
    ap.add_argument('--profile', help='补充画像文本文件（只在本机），例如按环评写的业务和场所情况')
    args = ap.parse_args()
    doc = args.doc
    out = open(args.out, 'w', encoding='utf-8') if args.out else sys.stdout
    extra = Path(args.profile).read_text(encoding='utf-8') if args.profile else ''
    t0 = time.perf_counter()
    paragraphs, issues, notes = run_all(doc, args.llm, extra)
    secs = time.perf_counter() - t0

    print(f'# 审查报告：{Path(doc).name}\n', file=out)
    print(f'共 {len(paragraphs)} 个段落，用时 {secs:.1f} 秒，发现 **{len(issues)}** 处问题。\n', file=out)
    for n in notes:
        print(f'- {n}', file=out)
    if issues:
        print('\n| 检查项 | 段落号 | 所在部分 | 原文 | 问题 |\n|---|---|---|---|---|', file=out)
        for i in issues:
            text = i.text if len(i.text) <= 40 else i.text[:40] + '…'
            print(f'| {i.check} | {i.para_index} | {i.section} | {text} | {i.problem} |', file=out)


if __name__ == '__main__':
    main()

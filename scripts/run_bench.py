"""注入式评测：对一份或几份"底稿"各生成若干个埋了错的版本，跑检查，统计召回率。

用法：
    python scripts/run_bench.py 输出目录 底稿1.docx 底稿2.docx --variants 5
    python scripts/run_bench.py 输出目录 底稿1.docx --variants 3 --llm --profile 补充画像.txt   # 加测 T4（花钱）

输出目录里会有埋错后的文档和评测报告。底稿是真实客户文件，所以输出目录要放在 tmp/ 或 output/（不公开）。
"""
import argparse
import sys
import time
import zlib
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from plan_review.pipeline import run_rules, run_all                     # noqa: E402
from plan_review.bench.inject import Mutator, RESIDUE_POOL, HARD_POOL, matches     # noqa: E402
from plan_review.llm import DeepSeek                                    # noqa: E402

RULE_STEPS = ['t1_gap', 't3_rename', 't3_stale', 't5_phone', 't5_fact', 't5_badlen', 't9_field']


def key_of(i):
    return (i.check, i.para_index, i.problem)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out_dir')
    ap.add_argument('bases', nargs='+')
    ap.add_argument('--variants', type=int, default=5)
    ap.add_argument('--llm', action='store_true', help='同时埋 T4 残留句并调用 DeepSeek 检查')
    ap.add_argument('--residues', type=int, default=3, help='每个版本埋几句残留（只在 --llm 时）')
    ap.add_argument('--profile', default='')
    ap.add_argument('--hard', action='store_true', help='T4 用难题句子（同为研发，但细节对不上）')
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    extra = Path(args.profile).read_text(encoding='utf-8') if args.profile else ''
    llm = DeepSeek() if args.llm else None

    per_kind = defaultdict(lambda: [0, 0])          # 类型 -> [埋入, 抓到]
    misses, extras = [], []
    t0 = time.perf_counter()
    for base in args.bases:
        _, base_issues, _ = run_rules(base)
        base_keys = {key_of(i) for i in base_issues}
        for v in range(args.variants):
            seed = zlib.crc32(f'{Path(base).name}-{v}'.encode())      # 固定种子：每次生成的版本都一样，结果可复现
            m = Mutator(base, seed=seed)
            for step in RULE_STEPS:
                getattr(m, step)() if step != 't3_stale' else m.t3_rename(stale=True)
            if args.llm:
                pool = HARD_POOL if args.hard else RESIDUE_POOL
                for s in m.rng.sample(pool, args.residues):
                    m.t4_residue(s)
            path = out / f'{Path(base).stem[:12]}_v{v}.docx'
            m.save(str(path))

            if args.llm:
                t4_idx = {i.para_index for i in m.injections if i.check == 'T4'}
                _, issues, _ = run_all(str(path), True, extra, llm=llm, only_indices=t4_idx)
            else:
                _, issues, _ = run_rules(str(path))
            new = [i for i in issues if key_of(i) not in base_keys]
            used = set()
            for inj in m.injections:
                hit = [i for i in new if matches(inj, i)]
                if inj.check == 'T4':     # T4 区分高把握 / 待确认；另外统计"规则和模型合起来"能不能抓到
                    sure = [i for i in hit if i.check == 'T4 套改残留']
                    per_kind['T4 插入别的行业的句子（高把握）'][0] += 1
                    per_kind['T4 插入别的行业的句子（高把握）'][1] += bool(sure)
                    anyhit = [i for i in new if i.para_index == inj.para_index or f'（段落 {inj.para_index}' in i.problem
                              or f'、{inj.para_index}' in i.problem]
                    per_kind['T4 插入别的行业的句子（任一检查抓到）'][0] += 1
                    per_kind['T4 插入别的行业的句子（任一检查抓到）'][1] += bool(anyhit)
                per_kind[inj.kind][0] += 1
                per_kind[inj.kind][1] += bool(hit)
                used |= {key_of(i) for i in hit}
                if not hit:
                    misses.append((path.name, inj))
            extras += [(path.name, i) for i in new if key_of(i) not in used and not i.check.startswith('T4')]
    secs = time.perf_counter() - t0

    report = out / '评测报告.md'
    with open(report, 'w', encoding='utf-8') as f:
        total_in = sum(v[0] for k, v in per_kind.items() if '（' not in k)
        total_hit = sum(v[1] for k, v in per_kind.items() if '（' not in k)
        print(f'# 注入式评测报告\n\n底稿 {len(args.bases)} 份 × 每份 {args.variants} 个版本，用时 {secs:.0f} 秒。\n', file=f)
        print('| 错误类型 | 埋入 | 抓到 | 召回率 |\n|---|---|---|---|', file=f)
        for k, (n, h) in sorted(per_kind.items()):
            print(f'| {k} | {n} | {h} | {h / n:.0%} |', file=f)
        print(f'| **合计** | {total_in} | {total_hit} | {total_hit / max(total_in, 1):.0%} |\n', file=f)
        if llm:
            u = llm.usage
            print(f'DeepSeek：{u.calls} 次调用，{u.prompt_tokens}+{u.completion_tokens} tokens，约 {u.cost_yuan:.2f} 元\n', file=f)
        print(f'## 漏掉的（{len(misses)}）\n', file=f)
        for name, inj in misses:
            print(f'- {name}：{inj.kind}，段落 {inj.para_index}，{inj.detail}', file=f)
        print(f'\n## 新增、但不对应任何埋入错误的报告（{len(extras)}）\n', file=f)
        print('多数是同一个错误引起的连带报告（比如改了一个表号，下一个表号也会报"重复"）。\n', file=f)
        for name, i in extras[:60]:
            print(f'- {name}：{i.check} 段落 {i.para_index}：{i.problem[:100]}', file=f)
    print(f'done: {total_hit}/{total_in}, misses={len(misses)}, extras={len(extras)}, report={report}')


if __name__ == '__main__':
    main()

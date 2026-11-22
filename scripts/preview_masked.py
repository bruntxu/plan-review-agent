"""预演：把一份预案脱敏、切块，写出"将要发给大模型的内容"，但不真的发送。
用来在花钱、发数据之前，人工检查脱敏是否干净。输出只存在本机的 tmp/ 目录。

用法：python scripts/preview_masked.py 预案.docx tmp/preview.txt
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from plan_review.docx_reader import read_paragraphs                     # noqa: E402
from plan_review.desensitize import Masker                              # noqa: E402
from plan_review.checks.template_residue import SYSTEM, build_chunks, company_profile, make_prompt  # noqa: E402

doc, out_path = sys.argv[1], sys.argv[2]
ps = read_paragraphs(doc)
m = Masker(ps)
profile = company_profile(ps, m)
chunks = build_chunks(ps, m)
prompts = [make_prompt(profile, c) for c in chunks]
leaks = [x for pr in prompts for x in m.leaks(pr)]
chars = sum(len(SYSTEM) + len(pr) for pr in prompts)

with open(out_path, 'w', encoding='utf-8') as out:
    kinds = {}
    for v in m.forward.values():
        k = v.strip('【】').rstrip('0123456789')
        kinds[k] = kinds.get(k, 0) + 1
    print(f'替换项统计：{kinds}', file=out)
    print(f'切成 {len(chunks)} 块，共约 {chars} 字（约 {int(chars / 1.4)} tokens）；安全网检出遗漏：{len(leaks)} 处\n', file=out)
    print('===== 替换表（只在本机）=====', file=out)
    for k, v in sorted(m.forward.items(), key=lambda kv: kv[1]):
        print(f'{v}  <-  {k}', file=out)
    print('\n===== 第 1 块将发送的内容 =====\n' + prompts[0], file=out)
    for i, pr in enumerate(prompts[1:], 2):
        print(f'\n===== 第 {i} 块 =====\n{pr}', file=out)
print(f'chunks={len(chunks)} chars={chars} leaks={len(leaks)} entries={len(m.forward)}')

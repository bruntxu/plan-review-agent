"""把所有检查串起来跑一遍。scripts/review.py（审查）和 scripts/run_bench.py（评测）都用它。"""
from __future__ import annotations

from plan_review.docx_reader import read_paragraphs
from plan_review.checks.table_numbering import check_table_numbering
from plan_review.checks.list_consistency import check_list_consistency
from plan_review.checks.field_integrity import check_field_integrity
from plan_review.checks.consistency import check_consistency
from plan_review.checks.template_residue import check_template_residue
from plan_review.llm import DeepSeek, NoApiKey

LIST_KINDS = ['现场处置方案', '专项应急预案']


def run_rules(doc: str, paragraphs=None):
    """只跑规则检查（免费、确定）。"""
    paragraphs = paragraphs or read_paragraphs(doc)
    issues, notes = [], []

    caps, found = check_table_numbering(paragraphs)
    issues += found
    notes.append(f'T1 表格编号：识别出 {len(caps)} 个表题')

    for suffix in LIST_KINDS:
        lists, found = check_list_consistency(paragraphs, suffix)
        issues += found
        desc = '、'.join(f'{l.place}{len(l.items)}项' for l in lists) or '未找到'
        notes.append(f'T3 清单一致性（{suffix}）：{desc}')

    found = check_consistency(paragraphs)
    issues += found
    notes.append(f'T5 前后矛盾：{len(found)} 处')

    counts, found = check_field_integrity(doc)
    issues += found
    notes.append(f'T9 域完整性：begin {counts["begin"]} / end {counts["end"]}')
    return paragraphs, issues, notes


def run_all(doc: str, use_llm: bool = False, extra_profile: str = '', llm=None, only_indices=None):
    paragraphs, issues, notes = run_rules(doc)
    if not use_llm:
        notes.append('T4 套改残留：未启用（加 --llm 开启）')
        return paragraphs, issues, notes
    try:
        llm = llm or DeepSeek()
    except NoApiKey as e:
        notes.append(f'T4 套改残留：跳过（{e}）')
        return paragraphs, issues, notes
    found = check_template_residue(paragraphs, llm, extra_profile=extra_profile, only_indices=only_indices)
    issues += found
    u = llm.usage
    sure = sum(i.check == 'T4 套改残留' for i in found)
    notes.append(f'T4 套改残留（DeepSeek {llm.model}，{"有" if extra_profile else "无"}补充画像）：'
                 f'确定 {sure} 处、待确认 {len(found) - sure} 处；调用 {u.calls} 次，'
                 f'{u.prompt_tokens}+{u.completion_tokens} tokens，约 {u.cost_yuan:.2f} 元，{u.seconds:.0f} 秒'
                 + (f'；⚠ {u.parse_errors} 块返回格式错误未能检查' if u.parse_errors else ''))
    return paragraphs, issues, notes

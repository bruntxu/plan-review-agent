"""用 LangGraph 把各个检查编排成一张"审查流程图"。

    解析文档 → 制定计划 → 规则检查 ──→ 汇总定级 → 写审查结论
                                └→ 大模型检查（计划里有才走）┘

各节点的分工：
- 解析：读 docx，看文档里有哪些东西（名单、人员表、表题、域……）
- 计划：根据文档内容和是否有 API Key，决定这次跑哪些检查，并写下理由
        （目前是确定性规则；需要时可以换成让大模型来规划）
- 规则检查：T1 / T3 / T5 / T9，免费、结果确定
- 大模型检查：T4 套改残留，脱敏后调用 DeepSeek
- 汇总定级：去重，按严重程度排序，统计
- 审查结论：用一段话总结，像专家意见表的开头

每个节点都会往 trace 里记一条"做了什么、用了多久"，网页上可以看到 Agent 的执行过程（可观测性）。
"""
from __future__ import annotations

import operator
import os
import time
from collections import Counter
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from plan_review.docx_reader import read_paragraphs
from plan_review.checks.table_numbering import check_table_numbering, find_captions
from plan_review.checks.list_consistency import check_list_consistency, extract_lists
from plan_review.checks.consistency import MOBILE_RE, check_consistency
from plan_review.checks.field_integrity import check_field_integrity
from plan_review.checks.template_residue import check_template_residue
from plan_review.llm import DeepSeek

CHECK_NAMES = {
    'T1': '表格编号', 'T3': '清单一致性', 'T4': '套改残留（大模型）', 'T5': '前后矛盾', 'T9': '域完整性',
}


class ReviewState(TypedDict, total=False):
    doc_path: str
    use_llm: bool
    extra_profile: str
    paragraphs: list
    features: dict
    plan: list[str]
    issues: Annotated[list, operator.add]       # 各节点各自往里加，LangGraph 负责合并
    trace: Annotated[list, operator.add]
    findings: list[dict]
    stats: dict
    summary: str
    llm_usage: dict


def _trace(node: str, t0: float, msg: str) -> list[dict]:
    return [{'node': node, 'seconds': round(time.perf_counter() - t0, 2), 'message': msg}]


# ---------------- 节点 ----------------
def parse(state: ReviewState) -> dict:
    t0 = time.perf_counter()
    ps = read_paragraphs(state['doc_path'])
    features = {
        'paragraphs': len(ps),
        'tables': len({p.table_id for p in ps if p.table_id}),
        'captions': len(find_captions(ps)),
        'name_lists': sum(len(extract_lists(ps, s)) for s in ('现场处置方案', '专项应急预案')),
        'phones': sum(bool(MOBILE_RE.search(p.text)) for p in ps),
        'has_toc': any(p.in_toc for p in ps),
    }
    msg = (f'读取 {features["paragraphs"]} 个段落、{features["tables"]} 张表格；'
           f'识别出 {features["captions"]} 个表题、{features["name_lists"]} 组方案名单、{features["phones"]} 段含手机号')
    return {'paragraphs': ps, 'features': features, 'trace': _trace('解析文档', t0, msg)}


def plan(state: ReviewState) -> dict:
    t0 = time.perf_counter()
    f, steps, why = state['features'], ['T9'], ['T9 域完整性：每份都查']
    if f['captions']:
        steps.append('T1'); why.append(f'T1 表格编号：有 {f["captions"]} 个表题')
    if f['name_lists']:
        steps.append('T3'); why.append(f'T3 清单一致性：有 {f["name_lists"]} 组名单')
    steps.append('T5'); why.append('T5 前后矛盾：每份都查')
    if state.get('use_llm'):
        if os.environ.get('DEEPSEEK_API_KEY'):
            steps.append('T4'); why.append('T4 套改残留：已开启大模型，先脱敏再发送')
        else:
            why.append('T4 套改残留：跳过，服务器没有配置 DEEPSEEK_API_KEY')
    else:
        why.append('T4 套改残留：未开启')
    return {'plan': steps, 'trace': _trace('制定计划', t0, '；'.join(why))}


def rules(state: ReviewState) -> dict:
    t0 = time.perf_counter()
    ps, steps, found = state['paragraphs'], state['plan'], []
    if 'T1' in steps:
        found += check_table_numbering(ps)[1]
    if 'T3' in steps:
        for suffix in ('现场处置方案', '专项应急预案'):
            found += check_list_consistency(ps, suffix)[1]
    if 'T5' in steps:
        found += check_consistency(ps)
    if 'T9' in steps:
        found += check_field_integrity(state['doc_path'])[1]
    by = Counter(i.check.split()[0] for i in found)
    msg = '、'.join(f'{k} {v} 处' for k, v in sorted(by.items())) or '没有发现问题'
    return {'issues': found, 'trace': _trace('规则检查', t0, msg)}


def llm_residue(state: ReviewState) -> dict:
    t0 = time.perf_counter()
    llm = DeepSeek()
    found = check_template_residue(state['paragraphs'], llm, extra_profile=state.get('extra_profile', ''))
    u = llm.usage
    sure = sum(i.check == 'T4 套改残留' for i in found)
    msg = (f'确定 {sure} 处、待确认 {len(found) - sure} 处；调用 {u.calls} 次，'
           f'{u.prompt_tokens + u.completion_tokens} tokens，约 {u.cost_yuan:.2f} 元')
    if u.parse_errors:
        msg += f'；{u.parse_errors} 块返回格式错误，未能检查'
    usage = {'calls': u.calls, 'tokens': u.prompt_tokens + u.completion_tokens, 'cost_yuan': round(u.cost_yuan, 3)}
    return {'issues': found, 'llm_usage': usage, 'trace': _trace('大模型检查', t0, msg)}


def severity(check: str, problem: str) -> str:
    if check.startswith('T9'):
        return '严重'
    if check == 'T4 套改残留' or (check.startswith('T5') and problem[:2] in ('R1', 'R2', 'R3', 'R4')):
        return '高'
    if check == 'T4 待确认':
        return '低'
    return '中'


ORDER = {'严重': 0, '高': 1, '中': 2, '低': 3}


def aggregate(state: ReviewState) -> dict:
    t0 = time.perf_counter()
    seen, findings = set(), []
    ps = state.get('paragraphs', [])
    for i in state.get('issues', []):
        key = (i.check, i.para_index, i.problem)
        if key in seen:
            continue
        seen.add(key)
        section = i.section or (ps[i.para_index].section if 0 <= i.para_index < len(ps) else '')   # T9 自己不记分部
        findings.append({'severity': severity(i.check, i.problem), 'check': i.check, 'code': i.check.split()[0],
                         'para_index': i.para_index, 'section': section, 'text': i.text, 'problem': i.problem})
    findings.sort(key=lambda f: (ORDER[f['severity']], f['code'], f['para_index']))
    stats = {'total': len(findings),
             'by_severity': dict(Counter(f['severity'] for f in findings)),
             'by_check': dict(Counter(f['code'] for f in findings))}
    msg = f'共 {len(findings)} 条：' + '、'.join(f'{k} {v}' for k, v in sorted(stats['by_severity'].items(), key=lambda x: ORDER[x[0]]))
    return {'findings': findings, 'stats': stats, 'trace': _trace('汇总定级', t0, msg)}


def summarize(state: ReviewState) -> dict:
    """用固定模板写结论（不额外调用大模型，结果可复现）。"""
    t0 = time.perf_counter()
    s, f = state['stats'], state['findings']
    if not f:
        text = '本次检查范围内未发现问题。'
    else:
        parts = [f'本次共发现 {s["total"]} 处问题']
        sev = s['by_severity']
        if sev.get('严重'):
            parts.append(f'其中 {sev["严重"]} 处为文档结构损坏，可能导致 Word/WPS 打开后部分内容不显示，应优先处理')
        top = Counter(x['code'] for x in f if x['severity'] in ('严重', '高'))
        if top:
            parts.append('高优先级问题集中在' + '、'.join(f'{CHECK_NAMES.get(k, k)}（{v} 处）' for k, v in top.most_common(3)))
        if 'T4' not in state.get('plan', []):
            parts.append('本次未启用大模型，套改残留类问题未检查')
        text = '；'.join(parts) + '。'
    return {'summary': text, 'trace': _trace('写审查结论', t0, text)}


def after_rules(state: ReviewState) -> str:
    return 'llm_residue' if 'T4' in state['plan'] else 'aggregate'


# ---------------- 组装 ----------------
def build_graph():
    g = StateGraph(ReviewState)
    g.add_node('parse', parse)
    g.add_node('plan', plan)
    g.add_node('rules', rules)
    g.add_node('llm_residue', llm_residue)
    g.add_node('aggregate', aggregate)
    g.add_node('summarize', summarize)
    g.add_edge(START, 'parse')
    g.add_edge('parse', 'plan')
    g.add_edge('plan', 'rules')
    g.add_conditional_edges('rules', after_rules, {'llm_residue': 'llm_residue', 'aggregate': 'aggregate'})
    g.add_edge('llm_residue', 'aggregate')
    g.add_edge('aggregate', 'summarize')
    g.add_edge('summarize', END)
    return g.compile()


GRAPH = build_graph()


def review(doc_path: str, use_llm: bool = False, extra_profile: str = '', on_step=None) -> dict[str, Any]:
    """跑完整个流程，返回可以直接转成 JSON 的结果。on_step(节点名, trace) 用来实时汇报进度。"""
    state: dict = {'doc_path': doc_path, 'use_llm': use_llm, 'extra_profile': extra_profile, 'issues': [], 'trace': []}
    final: dict = dict(state)
    for update in GRAPH.stream(state, stream_mode='updates'):
        for node, delta in update.items():
            for k, v in (delta or {}).items():
                final[k] = final.get(k, []) + v if k in ('issues', 'trace') else v
            if on_step:
                on_step(node, final.get('trace', []))
    return {k: final.get(k) for k in ('features', 'plan', 'findings', 'stats', 'summary', 'trace', 'llm_usage')}


def to_markdown(result: dict, title: str) -> str:
    lines = [f'# 审查报告：{title}', '', f'**结论**：{result["summary"]}', '', '## 执行过程', '']
    lines += [f'- {t["node"]}（{t["seconds"]} 秒）：{t["message"]}' for t in result['trace']]
    lines += ['', '## 问题清单', '', '| 严重程度 | 检查项 | 位置 | 原文 | 问题 |', '|---|---|---|---|---|']
    for f in result['findings']:
        text = f['text'] if len(f['text']) <= 40 else f['text'][:40] + '…'
        lines.append(f'| {f["severity"]} | {f["check"]} | {f["section"]} 第 {f["para_index"]} 段 | {text} | {f["problem"]} |')
    return '\n'.join(lines) + '\n'

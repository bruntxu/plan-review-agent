"""检查 T4：套改残留——文档里还留着上一家公司的内容。

真实例子（案例A v2，专家标红）：
  "本公司主要从事智能配电设备的研发等，厂房火灾类别设计为戊类"
  ——案例A是做医药中间体实验室研发的，这句是底本（一家电气公司）的原话。
这种句子每个字都没错，规则查不出来，要"读懂意思"才知道它说的不是本单位，所以交给大模型。

流程：
1. 本单位画像：所属行业、经营范围（基本情况表）、所在地区（地址里路名之前的部分），
   可再附一份补充画像（比如按环评写的"实验室研发、无生产车间"）
2. 全文脱敏后切成若干块（每块约 3500 字），每行带上段落号
3. 每块发给大模型：对照画像找出明显不属于本单位的内容，要求给出原文证据和把握程度
4. 过滤：段落号必须在这一块里、引用的原话必须真的出现在那一段里（防止模型编造）
5. 段落号对回原文，理由里的占位符换回真实名称

第一版的教训（案例A v2 报了 156 处，大多是误报）：
- 地址被脱敏后，模型不知道本单位就在当地，把"向当地应急管理局报告"当成别家的 → 画像里加所在地区
- 评审要求保留的通用专项预案、处置方案（机械伤害、坍塌、粉尘……）被当成残留 → 提示词里写明不算
- 隐患判定标准的逐条摘录（食品、白酒、造纸企业……）被当成残留 → 提示词里写明不算
"""
from __future__ import annotations

import re

from plan_review.docx_reader import Paragraph, cell_value
from plan_review.desensitize import Masker
from plan_review.checks.table_numbering import Issue

SYSTEM = """你是生产安全事故应急预案的评审专家。
这份预案是拿另一家公司的旧预案"套改"出来的，编写人员可能没改干净。你的任务是找出【套改残留】：本该属于上一家公司、却留在了本单位预案里的具体内容。

只有当某一段出现了【具体的、与本单位画像矛盾的事实】时才报告，例如：
- 别的业务或产品（如"本公司主要从事智能配电设备的研发"，而本单位是医药研发）；
- 本单位不可能有的具体物料、设备、设施、场所（如羽毛、筒仓、鱼塘、锅炉房、喷漆线、叉车作业规程）；
- 本单位没有的部门名称（如"制造部门""生产供应部门"，而本单位只是小型研发实验室）；
- 与本单位矛盾的数字、火灾危险性类别、建筑描述；
- 把别的公司当作本单位来写。

以下都【不要】报告：
1. 本单位所在地区的政府、园区、应急管理局、医院、消防等单位，以及周边单位、同楼租户、互救协议单位；
2. 评审要求保留的模板章节：全部专项应急预案和现场处置方案（火灾、特种设备、粉尘爆炸、有限空间、危化品泄漏、机械伤害、触电、中毒窒息、高处坠落、物体打击、车辆伤害、坍塌、灼烫、自然灾害、其他伤害等），这些章节的标题、事故类型列表、事故征兆、通用处置步骤、应急物资清单；
3. 法规、标准的名称和条文，尤其是隐患判定标准的逐条摘录（其中列举各行业的条款是标准原文）；
4. 通用的、模板化的应急管理表述，即使与本单位关系不大；
5. 只是说法不准确，但没有具体证据表明来自别的单位的内容。

文中【公司1】【人名3】【手机2】这类是脱敏后的占位符，同一占位符代表同一对象，【公司1】是本单位。
输出 JSON：{"findings": [{"id": 段落号, "quote": "该段中能证明问题的原话，原样摘抄，不超过30字", "reason": "一句话说明与画像哪一点矛盾", "confidence": "高 或 中"}]}
没有就输出 {"findings": []}。宁可少报，不要多报。"""

ADDRESS_LABEL_RE = re.compile(r'(?:地址|住所|所在地|位于)[：:]?\s*([一-龥]{4,40}?(?:路|街|大道))')
REGION_RE = re.compile(r'^(.*(?:省|市|县|区|开发区|园区|新区))')


def company_region(paragraphs: list[Paragraph]) -> str:
    """从"地址：四川省某某市某某开发区某某路……"中取出路名之前的地区部分。"""
    for p in paragraphs:
        m = ADDRESS_LABEL_RE.search(p.text)
        if m:
            r = REGION_RE.match(m.group(1))
            if r:
                return r.group(1)
    return '（未找到）'


def company_profile(paragraphs: list[Paragraph], masker: Masker, extra: str = '') -> str:
    industry = cell_value(paragraphs, '所属行业') or '（未找到）'
    scope = cell_value(paragraphs, '经营范围') or '（未找到）'
    text = (f'本单位：{masker.main_company}\n所在地区：{company_region(paragraphs)}\n'
            f'所属行业：{industry}\n经营范围：{scope}')
    if extra.strip():
        text += f'\n补充情况：{extra.strip()}'
    return masker.mask(text)


def build_chunks(paragraphs: list[Paragraph], masker: Masker, chunk_chars: int = 3500) -> list[list[tuple[int, str]]]:
    lines = []
    for p in paragraphs:
        t = p.text.strip()
        if p.in_toc or len(t) < 6:
            continue
        lines.append((p.index, masker.mask(t[:300])))
    chunks, cur, size = [], [], 0
    for idx, t in lines:
        if cur and size + len(t) > chunk_chars:
            chunks.append(cur)
            cur, size = [], 0
        cur.append((idx, t))
        size += len(t) + 8
    if cur:
        chunks.append(cur)
    return chunks


def make_prompt(profile: str, chunk: list[tuple[int, str]]) -> str:
    body = '\n'.join(f'[{i}] {t}' for i, t in chunk)
    return f'【本单位画像】\n{profile}\n\n【待检查的预案片段】（方括号里是段落号）\n{body}'


def _norm(s: str) -> str:
    return re.sub(r'[\s，,。.；;：:、“”"\'（）()]', '', s)


def check_template_residue(paragraphs: list[Paragraph], llm, masker: Masker | None = None,
                           chunk_chars: int = 3500, extra_profile: str = '', only_indices=None) -> list[Issue]:
    """返回问题列表。把握为"高"的记为 T4 套改残留，"中"的记为 T4 待确认。
    only_indices：评测时只发送包含这些段落的块，省钱（切块方式不变，所以模型看到的上下文和正常审查一样）。"""
    masker = masker or Masker(paragraphs)
    profile = company_profile(paragraphs, masker, extra_profile)
    by_index = {p.index: p for p in paragraphs}
    issues = []
    for chunk in build_chunks(paragraphs, masker, chunk_chars):
        sent = dict(chunk)
        if only_indices is not None and not (set(sent) & set(only_indices)):
            continue
        result = llm.chat_json(SYSTEM, make_prompt(profile, chunk))
        for f in result.get('findings', []):
            try:
                idx = int(f.get('id'))
            except (TypeError, ValueError):
                continue
            if idx not in sent:                                   # 模型编了一个这块里没有的段落号
                continue
            quote = str(f.get('quote', ''))
            if quote and _norm(quote) not in _norm(sent[idx]):    # 引用的原话在那一段里找不到
                continue
            sure = str(f.get('confidence', '中')).strip().startswith('高')
            p = by_index[idx]
            reason = masker.unmask(str(f.get('reason', '')))
            if quote:
                reason = f'"{masker.unmask(quote)}"：{reason}'
            issues.append(Issue('T4 套改残留' if sure else 'T4 待确认', idx, p.section, p.text, reason))
    return issues

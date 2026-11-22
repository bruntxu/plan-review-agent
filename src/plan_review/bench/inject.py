"""注入式评测：往一份预案里故意埋进已知的错误，再看检查能抓回来几个。

为什么要做：拿真实文档跑，只能知道"查出了多少"，不知道"漏了多少"。
自己埋的错，位置和类型都确切知道，就能算召回率 = 抓回来的 / 埋进去的。

做法：
- 直接改 docx 里的文字（只改字，不增删段落），所以段落号前后不变，方便对答案
- 每种错误都有一个"怎么算抓到了"的规则：在哪个检查项、哪一段、或者问题描述里包含什么
- 原文档本来就有的问题先跑一遍记下来，打分时排除，只看新增的
"""
from __future__ import annotations

import io
import random
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from plan_review.docx_reader import W, Paragraph, paragraph_elements, read_paragraphs
from plan_review.checks.table_numbering import find_captions
from plan_review.checks.list_consistency import extract_lists
from plan_review.checks.consistency import MOBILE_RE, fact_occurrences, normalize_fact


@dataclass
class Injection:
    kind: str                 # 错误类型，比如 "T1 表号跳号"
    check: str                # 应该由哪个检查抓到，比如 "T1"
    para_index: int | None    # 改的是哪一段
    key: str | None = None    # 问题描述里应该出现的关键字（用于汇总型的问题，比如 R1 列出了所有段落）
    detail: str = ''          # 改了什么，给人看的


@dataclass
class Mutator:
    """持有一份 docx 的 XML，提供各种"埋错"操作。"""
    path: str
    seed: int = 0
    injections: list[Injection] = field(default_factory=list)

    def __post_init__(self):
        raw = zipfile.ZipFile(self.path).read('word/document.xml').decode('utf-8')
        for prefix, uri in re.findall(r'xmlns:(\w+)="([^"]+)"', raw[:5000]):
            ET.register_namespace(prefix, uri)
        self.root = ET.fromstring(raw)
        self.elements = paragraph_elements(self.root)
        self.paragraphs = read_paragraphs(self.path)
        self.rng = random.Random(self.seed)
        self.used: set[int] = set()          # 同一段只改一次，避免两种错误互相干扰

    # ---------- 底层：在一段里把 old 换成 new，按字符改，不拆不删 run ----------
    def replace(self, idx: int, old: str, new: str) -> bool:
        ts = list(self.elements[idx].iter(W + 't'))
        full = ''.join(t.text or '' for t in ts)
        pos = full.find(old)
        if pos < 0:
            return False
        end, offset, placed = pos + len(old), 0, False
        for t in ts:
            s = t.text or ''
            a, b = offset, offset + len(s)
            offset = b
            if b <= pos or a >= end:
                continue
            keep_head = s[:max(0, pos - a)]
            keep_tail = s[max(0, end - a):] if end < b else ''
            t.text = keep_head + ('' if placed else new) + keep_tail
            placed = True
        self.used.add(idx)
        return True

    def _free(self, candidates):
        c = [x for x in candidates if x.index not in self.used]
        return self.rng.choice(c) if c else None

    # ---------- 各种错误 ----------
    def t1_gap(self):
        """把某个表题的序号 +1，造成跳号。"""
        caps = find_captions(self.paragraphs)
        series = {}
        for c in caps:
            series.setdefault(c.series, []).append(c)
        pool = [c for items in series.values() if len(items) >= 3 for c in items[:-1] if c.kind != '其他格式']
        c = self._free([x.para for x in pool])
        if not c:
            return
        cap = next(x for x in pool if x.para is c)
        old = re.search(r'\d+(?:\s*[.\-－—]\s*\d+)*', c.text).group(0)
        nums = re.findall(r'\d+', old)
        new = old[: old.rfind(nums[-1])] + str(int(nums[-1]) + 1)
        if self.replace(c.index, old, new):
            self.injections.append(Injection('T1 表号跳号', 'T1', c.index, detail=f'{cap.label} 改成序号 {int(nums[-1]) + 1}'))

    def t3_rename(self, stale: bool = False):
        """把目录/正文列表/表格里的某个处置方案改个叫法（stale=True 时换成一个根本不存在的方案）。"""
        lists = [l for l in extract_lists(self.paragraphs, '现场处置方案') if l.place != '章节']
        items = [(n, p) for l in lists for n, p in l.items]
        p = self._free([p for _, p in items])
        if not p:
            return
        name = next(n for n, q in items if q is p)
        if stale:
            new = '起重伤害事故现场处置方案'
            kind = 'T3 名单里多出不存在的方案'
        else:
            core = name.removesuffix('现场处置方案')
            new = (core.removesuffix('事故') + '伤害事故' if '伤害' not in core else core + '类') + '现场处置方案'
            kind = 'T3 方案叫法不一致'
        raw = re.sub(r'\s+', '', p.text)
        if new in raw:
            return
        if self.replace(p.index, name, new):
            self.injections.append(Injection(kind, 'T3', p.index, detail=f'"{name}" 改成 "{new}"'))

    def t5_phone(self):
        """把人员表里某个人的手机号改掉一处。"""
        pool = [p for p in self.paragraphs if p.in_table and MOBILE_RE.fullmatch(p.text.strip())]
        p = self._free(pool)
        if not p:
            return
        new = '1' + self.rng.choice('3578') + ''.join(self.rng.choice('0123456789') for _ in range(9))
        if self.replace(p.index, p.text.strip(), new):
            self.injections.append(Injection('T5 同一人号码不一致', 'T5', p.index, key=new, detail=f'{p.text.strip()} 改成 {new}'))

    def t5_fact(self):
        """营业执照信息（成立日期、注册资本）在文中出现两次以上时，改掉其中一处。
        （第一版是改"员工人数"，但它在文中只出现一次，改了也没有第二处可以对照，是个测不出来的埋法，已换掉。）"""
        occ = fact_occurrences(self.paragraphs)
        pool = [(label, idx) for label in ('成立日期', '注册资本')
                for idxs in occ.get(label, {}).values() for idx in idxs
                if sum(len(v) for v in occ[label].values()) >= 2]
        pool = [x for x in pool if x[1] not in self.used]
        if not pool:
            return
        label, idx = self.rng.choice(pool)
        text = self.paragraphs[idx].text
        if label == '成立日期':
            m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)
            if not m:
                return
            day = int(m.group(3)) % 27 + 1
            old, new = m.group(0), f'{m.group(1)}年{m.group(2)}月{day:0{len(m.group(3))}d}日'
        else:
            m = re.search(r'[壹贰叁肆伍陆柒捌玖]', text)
            if not m:
                return
            digits = '壹贰叁肆伍陆柒捌玖'
            old, new = m.group(0), digits[(digits.index(m.group(0)) + 1) % 9]
        if self.replace(idx, old, new):
            new_text = text.replace(old, new, 1)
            value = None
            for v, ix in fact_occurrences([Paragraph(idx, new_text, False, '', False)]).get(label, {}).items():
                value = v
            if value is None:      # 表格里的格子单独拿出来时识别不到标签，直接按格子内容规范化
                value = normalize_fact(label, new_text.strip())
            self.injections.append(Injection(f'T5 {label}不一致', 'T5', idx, key=f'{value}（段落 {idx}',
                                             detail=f'"{old}" 改成 "{new}"'))

    def t5_badlen(self):
        """手机号删掉最后一位。"""
        pool = [p for p in self.paragraphs if not p.in_toc and not p.in_table and MOBILE_RE.search(p.text)]
        p = self._free(pool)
        if not p:
            return
        ph = MOBILE_RE.search(p.text).group(1)
        if self.replace(p.index, ph, ph[:-1]):
            self.injections.append(Injection('T5 号码少一位', 'T5', p.index, key=ph[:-1], detail=f'{ph} 改成 {ph[:-1]}'))

    def t9_field(self):
        """删掉某个域的结束标记（模拟案例B那次 181 页变 7 页的事故）。"""
        candidates = []
        for i, el in enumerate(self.elements):
            if i in self.used:
                continue
            for r in el.iter(W + 'r'):
                f = r.find(W + 'fldChar')
                if f is not None and f.get(W + 'fldCharType') == 'end':
                    candidates.append((i, el, r))
        if not candidates:
            return
        i, el, r = self.rng.choice(candidates)
        for parent in el.iter():
            if r in list(parent):
                parent.remove(r)
                break
        self.used.add(i)
        self.injections.append(Injection('T9 域没闭合', 'T9', i, detail=f'删掉第 {i} 段里的一个域结束标记'))

    def t4_residue(self, sentence: str):
        """在一段正文末尾接上一句别的行业的话。"""
        pool = [p for p in self.paragraphs
                if not p.in_table and not p.in_toc and p.section == '正文' and 40 <= len(p.text) <= 200]
        p = self._free(pool)
        if not p:
            return
        tail = p.text.strip()[-6:]
        if self.replace(p.index, tail, tail + sentence):
            self.injections.append(Injection('T4 插入别的行业的句子', 'T4', p.index, detail=sentence))

    # ---------- 输出 ----------
    def save(self, out_path: str):
        xml = ET.tostring(self.root, encoding='utf-8', xml_declaration=True)
        with zipfile.ZipFile(self.path) as zin, zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = xml if item.filename == 'word/document.xml' else zin.read(item.filename)
                zout.writestr(item, data)


RESIDUE_POOL = [
    '公司喷漆车间位于厂区东北角，日常存放稀释剂约2吨。',
    '公司现有叉车3台，主要用于原料和成品的装卸。',
    '锅炉房设置1台2t/h燃气蒸汽锅炉，由专职司炉工操作。',
    '成品仓库主要存放电线电缆及低压配电柜成品。',
    '木工车间每日下班前清扫木屑粉尘，集中送往除尘间。',
    '公司冲压车间共有冲床12台，操作人员须持证上岗。',
    '面粉仓储区设有4座立筒仓，装卸作业由仓储部负责。',
    '本公司主要从事家具板材的生产加工，厂房火灾危险性为丙类。',
]


# 难题：同样是"研发实验室"，但具体细节和本单位对不上；或者是数字矛盾。比 RESIDUE_POOL 隐蔽得多
HARD_POOL = [
    '实验室主要开展锂电池正极材料的合成研究。',
    '公司现有员工45人，分为研发部、质检部和销售部。',
    '实验室位于厂区2号楼一层，建筑面积约1200平方米。',
    '公司设有中试车间一座，配备500L反应釜4台。',
    '本单位主要产品为工业级氢氟酸，年产量约5000吨。',
    '应急物资统一存放在一楼门卫室旁的消防器材间。',
]


def matches(inj: Injection, issue) -> bool:
    if not issue.check.startswith(inj.check):
        return False
    if inj.key:
        return inj.key in issue.problem
    return inj.check == 'T9' or issue.para_index == inj.para_index

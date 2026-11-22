"""脱敏：发给大模型之前，把公司名、人名、电话、信用代码、地址换成占位符；结果回来后再换回去。

为什么要做：预案是客户企业的文件，里面有真实的公司、人名和手机号。
发给第三方 API 之前必须先替换掉。替换表只保存在本机，不会发出去。

例子：
  原文   成都某某科技有限公司总指挥张三，电话 13800000000
  发出去 【公司1】总指挥【人名1】，电话 【手机1】
同一个原文永远对应同一个占位符，所以大模型仍然能看出"前后是不是同一个人、同一家公司"。
"""
from __future__ import annotations

import re
from collections import Counter

from plan_review.docx_reader import Paragraph

MOBILE_RE = re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)')
LANDLINE_RE = re.compile(r'(?<!\d)0\d{2,3}[-－]\d{7,8}(?!\d)')
CREDIT_RE = re.compile(r'(?<![0-9A-Z])[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}(?![0-9A-Z])')
COMPANY_RE = re.compile(r'[一-龥（）()]{2,30}?(?:有限责任公司|股份有限公司|有限公司)')
ADDRESS_RE = re.compile(r'[一-龥]{1,20}(?:路|街|大道)[一-龥]{0,6}\d+号(?:[一-龥A-Za-z\d\-—]{0,12}?(?:栋|楼|层|室|号))*')

# 公司名前面常粘着别的字（"根据成都某某有限公司"），从第一个地名处截断
REGIONS = tuple(('中国 北京 天津 上海 重庆 河北 山西 内蒙古 辽宁 吉林 黑龙江 江苏 浙江 安徽 福建 江西 山东 河南 湖北 湖南 '
           '广东 广西 海南 四川 贵州 云南 西藏 陕西 甘肃 青海 宁夏 新疆 成都 彭州 绵阳 德阳 深圳 杭州 广州 武汉 西安 '
           '南京 苏州 郑州 长沙 昆明 贵阳 兰州 宜宾 泸州 南充 乐山 眉山 自贡 遂宁 内江 资阳 雅安').split())
LEAD_STOP = ('我公司', '本公司', '根据', '楼为', '与', '由', '向', '经', '对', '为')

# 常见姓氏（去掉了"水、同、和、于"这类容易和普通词混淆的）。人名必须以这些字开头，
# 否则"总指挥批准""事故报告"里的"批准""报告"会被误当成人名
SURNAMES = set('王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘蒋蔡余杜叶程苏魏吕丁任'
               '沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫'
               '孔向汤冷傅')
COMPANY_SUFFIX = ('有限责任公司', '股份有限公司', '有限公司')
INDUSTRY_WORDS = ('科技', '技术', '实业', '投资', '企业管理', '环境监测', '医药', '药业', '电气', '化工', '材料',
                  '生物', '工程', '设备', '制造', '贸易', '发展', '信息', '咨询', '服务', '集团', '家具', '物流')

ROLE_HINT = re.compile(r'指挥|组|长|员|部|科|室|处|局|院|队|站|所|中心|办|司机|厂|公司|经理|主任|主管|'
                       r'通讯|抢险|后勤|医疗|警戒|疏散|技术|安全|保卫|救援|职务|姓名|序号|电话|手机|备注|联系|负责|单位|名称|地址')
NAME_AFTER_ROLE = re.compile(r'(?:法定代表人|总指挥|副总指挥|联系人|负责人|组长)\s*[：:]\s*([一-龥]{2,3})(?=[\s，,。；;（(]|$|\d)')


def _looks_like_name(s: str) -> bool:
    return bool(re.fullmatch(r'[一-龥]{2,4}', s)) and s[0] in SURNAMES and not ROLE_HINT.search(s)


def _short_names(full: str) -> tuple[str, str]:
    """成都某某科技有限公司 -> 简称"某某科技"、字号"某某"。"""
    s = full
    while s.startswith(REGIONS):
        s = s[next(len(r) for r in REGIONS if s.startswith(r)):]
        s = s.lstrip('省市')
    for suf in COMPANY_SUFFIX:
        s = s.removesuffix(suf)
    brand = s
    changed = True
    while changed:
        changed = False
        for w in INDUSTRY_WORDS:
            if brand.endswith(w) and len(brand) - len(w) >= 2:
                brand, changed = brand[:-len(w)], True
    return s, brand


def _trim_company(name: str) -> str:
    for i in range(1, len(name)):
        if name[i:].startswith(REGIONS):
            return name[i:]
    for stop in LEAD_STOP:
        if name.startswith(stop) and len(name) - len(stop) >= 6:
            return name[len(stop):]
    return name


class Masker:
    def __init__(self, paragraphs: list[Paragraph], extra_names: tuple[str, ...] = ()):
        self.forward: dict[str, str] = {}      # 原文 -> 占位符
        texts = [p.text for p in paragraphs]

        companies = Counter(_trim_company(m) for t in texts for m in COMPANY_RE.findall(t))
        for k, (name, _) in enumerate(companies.most_common(), 1):   # 出现最多的是本单位 = 公司1
            self.forward[name] = f'【公司{k}】'
            short, brand = _short_names(name)          # 文中还会出现"某某科技司发[2026]1号""某某产业园"
            if len(short) >= 2 and short != name:
                self.forward.setdefault(short, f'【公司{k}简称】')
            if len(brand) >= 2 and brand != short:
                self.forward.setdefault(brand, f'【公司{k}字号】')

        names = Counter(extra_names)
        names.update(self._names_from_tables(paragraphs))
        for t in texts:
            names.update(NAME_AFTER_ROLE.findall(t))
        for k, name in enumerate(sorted(n for n in names if n in extra_names or _looks_like_name(n)), 1):
            self.forward[name] = f'【人名{k}】'

        for regex, label in ((MOBILE_RE, '手机'), (LANDLINE_RE, '电话'), (CREDIT_RE, '信用代码'), (ADDRESS_RE, '地址')):
            found = sorted({m for t in texts for m in regex.findall(t)})
            for k, v in enumerate(found, 1):
                self.forward[v] = f'【{label}{k}】'

        self.backward = {v: k for k, v in self.forward.items()}
        # 先替换长的，避免"成都某某有限公司"被拆成先替换里面的短词
        self._order = sorted(self.forward, key=len, reverse=True)

    @staticmethod
    def _names_from_tables(paragraphs: list[Paragraph]) -> list[str]:
        """人员表里，跟手机号在同一行、2~4 个汉字、又不像职务的格子，当作人名。"""
        rows: dict[tuple, list[str]] = {}
        for p in paragraphs:
            if p.in_table:
                rows.setdefault((p.table_id, p.row), []).append(p.text.strip())
        out = []
        for cells in rows.values():
            if any(MOBILE_RE.search(c) for c in cells):
                out += [c for c in cells if _looks_like_name(c)]
        return out

    def mask(self, text: str) -> str:
        for k in self._order:
            if k in text:
                text = text.replace(k, self.forward[k])
        return text

    def unmask(self, text: str) -> str:
        return re.sub(r'【[^】]{1,12}】', lambda m: self.backward.get(m.group(0), m.group(0)), text)

    def leaks(self, text: str) -> list[str]:
        """安全网：检查一段要发出去的文字里，是否还残留手机号或信用代码。"""
        return MOBILE_RE.findall(text) + CREDIT_RE.findall(text)

    @property
    def main_company(self) -> str:
        return '【公司1】'

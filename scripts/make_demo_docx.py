"""生成一份【完全虚构】的示例预案，用于演示和公开仓库（不含任何真实客户信息）。

里面故意埋了真实文档中遇到过的各类问题：
  T1 表号重复（危化品章里出现了第 1 章的"表1-2"）、附表跳号（缺附表3）
  T3 目录没刷新（还有"起重伤害"、缺"危险化学品泄漏"）、正文列表叫法不一致（"触电伤害"）
  T4 套改残留（"智能配电设备…戊类"、叉车"放下叉脚"）
  T5 同一人两个号码、两人共用一个号码、总指挥兼副总指挥、一行两个号码、号码没写完、
     成立日期表格与正文不一致、8 人救援队伍对 6 名员工
  T9 一个没闭合的域（会导致 Word 打开后后面的内容不显示）

用法：python scripts/make_demo_docx.py data/demo/示例预案_虚构.docx
"""
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def p(text, style=None, fields=()):
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ''
    runs = ''.join(f'<w:r><w:fldChar w:fldCharType="{f}"/></w:r>' for f in fields)
    return f'<w:p>{ppr}<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r>{runs}</w:p>'


def table(rows):
    body = ''.join('<w:tr>' + ''.join(f'<w:tc>{p(c)}</w:tc>' for c in row) + '</w:tr>' for row in rows)
    return f'<w:tbl><w:tblPr><w:tblBorders><w:top w:val="single"/><w:bottom w:val="single"/><w:insideH w:val="single"/>' \
           f'<w:insideV w:val="single"/><w:left w:val="single"/><w:right w:val="single"/></w:tblBorders></w:tblPr>{body}</w:tbl>'


def toc(lines):
    first = p(lines[0], 'TOC1', fields=('begin', 'separate'))
    middle = ''.join(p(x, 'TOC2') for x in lines[1:-1])
    last = p(lines[-1], 'TOC2', fields=('end',))
    return f'<w:sdt><w:sdtContent>{first}{middle}{last}</w:sdtContent></w:sdt>'


S = '现场处置方案'
CO = '星河示例新材料科技有限公司'       # 虚构
parts = [
    p(f'{CO}生产安全事故应急预案', 'Title'),
    toc(['目  录- 1 -', f'第三篇 {S}- 20 -', f'1.火灾事故{S}- 20 -', f'2.触电事故{S}- 23 -',
         f'3.灼烫事故{S}- 26 -', f'4.起重伤害事故{S}- 28 -']),
    p('第一篇 综合应急预案', 'Heading1'),
    p(f'根据{CO}实际情况编制本预案。本公司成立于2021年3月5日，注册资本：伍佰万元整。'),
    p('公司现有员工6人，均为研发及管理人员。'),
    p('本单位设置24小时应急值班电话：13800001111或。'),
    p('具体现场处置措施按照相关现场处置方案进行处置：'),
    p(f'1）火灾事故{S}；'), p(f'2）触电伤害事故{S}；'), p(f'3）灼烫事故{S}；'), p(f'4）危险化学品泄漏事故{S}。'),
    p('表1-1 火灾事故类型一览表'),
    table([('事故类型', '可能场所'), ('可燃液体火灾', '试剂室')]),
    p('表1-2 应急职能小组组成及职责'),
    table([('应急岗位', '职位', '姓名', '职务', '手机'),
           ('应急指挥部', '总指挥', '王小明', '董事长', '13800001111'),
           ('应急指挥部', '副指挥', '王小明', '总经理', '13900002222'),
           ('应急指挥部', '现场总执行', '赵六', '副总经理', '13900002222'),
           ('应急救援小组', '通讯联络组组员', '钱七', '员工', '13700003333', '15000004444')]),
    p('第二篇 专项应急预案', 'Heading1'),
    p('表2-1 危险化学品泄漏事故类型一览表'),
    table([('物质', '场所'), ('乙酸乙酯', '试剂柜')]),
    p('表1-2 应急职能小组组成及职责'),
    p('6）停车后应拉紧手刹，放下叉脚，关掉电源，取出钥匙。'),
    p(f'第三篇 {S}', 'Heading1'),
    p(f'1.火灾事故{S}', 'Heading2'), p('发现火情立即报警，使用灭火器初期扑救。'),
    p(f'2.触电事故{S}', 'Heading2'), p('立即切断电源，用绝缘物使触电者脱离电源。'),
    p(f'3.灼烫事故{S}', 'Heading2'), p('立即用大量清水冲洗受伤部位。'),
    p(f'4.危险化学品泄漏事故{S}', 'Heading2'), p('撤离无关人员，使用吸附棉收集泄漏物。'),
    p('附件1 生产经营单位概况', 'Heading1'),
    p('附表1 企业基本情况'),
    table([('企业名称', CO), ('所属行业', 'M7340医学研究和试验发展'),
           ('经营范围', '新材料技术研发；技术服务、技术开发、技术咨询'),
           ('成立日期', '2021年03月15日'), ('注册资本', '伍佰万元整（人民币）')]),
    p('公司地址：四川省示例市高新区创新大道88号5楼。'),
    p('本公司主要从事智能配电设备的研发等，厂房火灾类别设计为戊类，耐火等级为二级。'),
    p('附表2 周边环境情况'),
    table([('方位', '单位'), ('东', '示例产业园管理办公室')]),
    p('附表4 主要设备一览表'),
    table([('设备', '数量'), ('通风橱', '2台')]),
    p('附件3 预案体系与衔接', 'Heading1'),
    p('附表5 应急预案体系'),
    table([('类别', '名称'), (S, f'火灾事故{S}'), (S, f'触电事故{S}'), (S, f'灼烫事故{S}'),
           (S, f'危险化学品泄漏事故{S}')]),
    p('附录B 应急资源调查报告', 'Heading1'),
    p('公司建立了由总经理以及各岗位员工8人组成应急救援队伍。'),
    p('4.1适用范围- 57 -', fields=('begin', 'separate')),       # 域只有开始没有结束
    p('（本段之后的内容在 Word 中可能无法显示）'),
]

DOC = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {NS}><w:body>{"".join(parts)}</w:body></w:document>'
CT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      '<Default Extension="xml" ContentType="application/xml"/>'
      '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
      '</Types>')
RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>')

out = Path(sys.argv[1] if len(sys.argv) > 1 else 'data/demo/示例预案_虚构.docx')
out.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    z.writestr('[Content_Types].xml', CT)
    z.writestr('_rels/.rels', RELS)
    z.writestr('word/document.xml', DOC)
print(out)

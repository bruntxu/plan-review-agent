# plan-review-agent：应急预案智能审查 Agent

上传一份《生产安全事故应急预案》（.docx，通常有 170–190 页），自动找出评审专家会挑的问题：表格编号错误、几处名单对不上、人员电话前后矛盾、套改时留下的上一家公司内容、会导致文档显示不全的损坏。

- **规则 + 大模型组合**：能用规则查的（编号、对比、计数）全用规则，免费、结果确定；需要"读懂意思"的（套改残留）交给 DeepSeek，**发送前先脱敏**，并有防泄漏的安全网。
- **LangGraph 编排**：解析 → 制定计划 → 规则检查 →（大模型检查）→ 汇总定级 → 写结论，每一步都记录执行过程。
- **FastAPI 服务 + 网页**：上传文件、实时看进度、按严重程度和检查项筛选、下载报告；附带虚构的示例预案，可以一键试用。
- **评测**：用真实专家评审意见对照，再加上注入式评测（自己埋已知的错，看能抓回多少）。

## 快速开始

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/Scripts/python.exe -r requirements.txt httpx
python scripts/make_demo_docx.py data/demo/示例预案_虚构.docx
.venv/Scripts/python.exe -m uvicorn plan_review.api:app --app-dir src --port 8000
```

打开 http://localhost:8000 ，点"用示例预案试一试"。设置了环境变量 `DEEPSEEK_API_KEY`，才能勾选大模型检查（见 `docs/DeepSeek接入.md`）。

Docker（本机还没装 Docker，**Dockerfile 还没实际构建验证过**）：

```bash
docker compose up --build        # 国内网络：PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple docker compose up --build
```

## 检查项

| 编号 | 检查 | 方式 |
|---|---|---|
| T1 | 表格编号：跳号、重复、章号倒退、格式不统一 | 规则 |
| T3 | 方案名单在目录、正文列表、预案体系表、章节四处是否对齐 | 规则 |
| T4 | 套改残留：描述的是别的公司的业务、设备、部门 | 大模型（脱敏后） |
| T5 | 前后矛盾：一人两号、一号多人、表格错位、号码没写完、成立日期 / 注册资本 / 人数不一致 | 规则 |
| T9 | Word 域没闭合（会导致后面的内容不显示） | 规则 |

## 结果摘要（详见 `docs/进度与结果.md`）

- 真实文档：专家第二轮意见里的编号、名单问题全部查出，另外还查出专家漏掉的几处。在已经过两轮评审的版本里，大模型仍查出 16 处带具体证据的套改残留（叉车、行车、鱼塘、制造部门……）。
- 注入式评测：规则 70/70（错是自己埋的，只说明规则按设计工作）；套改残留难题上，模型单独 67–92%，规则加模型合起来 92%。

## 命令行

```bash
python scripts/review.py 预案.docx output/审查报告.md [--llm] [--profile 补充画像.txt]
python scripts/preview_masked.py 预案.docx tmp/preview.txt        # 预演：看要发给大模型的内容
python scripts/run_bench.py tmp/bench 底稿.docx --variants 5 [--llm --hard]
```

## 测试

```bash
python tests/test_table_numbering.py      # 其余 tests/test_*.py 同理，只用标准库
.venv/Scripts/python.exe tests/test_api.py  # 接口测试需要虚拟环境
```

## 数据安全

`output/`、`tmp/`、`data/private/` 含有客户企业的真实信息，已写进 `.gitignore` 和 `.dockerignore`，**不能上传 GitHub，也不会打进镜像**。
文档和代码注释里的真实案例已改成"案例 A / 案例 B / 底本 C"，人名改成"甲 / 乙"。示例预案 `data/demo/` 是完全虚构的。

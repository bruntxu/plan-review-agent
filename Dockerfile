# 应急预案智能审查 Agent
# 构建：docker build -t plan-review .
# 运行：docker run -p 8000:8000 -e DEEPSEEK_API_KEY=你的key plan-review   （不传 Key 就只跑规则检查）
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
WORKDIR /app

# 国内网络可以加 --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.txt .
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} -r requirements.txt

COPY src ./src
COPY web ./web
COPY scripts/make_demo_docx.py ./scripts/
RUN python scripts/make_demo_docx.py data/demo/示例预案_虚构.docx

# 不用 root 跑服务
RUN useradd --create-home app && chown -R app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uvicorn", "plan_review.api:app", "--host", "0.0.0.0", "--port", "8000"]

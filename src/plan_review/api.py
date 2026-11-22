"""FastAPI 服务：上传预案 → 后台跑审查 Agent → 网页轮询进度和结果。

接口：
  GET  /                         网页
  GET  /api/health               健康检查（也告诉前端：服务器有没有配置 DeepSeek Key）
  POST /api/reviews              上传 .docx 开始审查，返回任务号（审查在后台线程里跑，接口立刻返回）
  POST /api/reviews/demo         用内置的虚构示例预案开始审查
  GET  /api/reviews/{id}         查进度和结果
  GET  /api/reviews/{id}/report.md  下载 Markdown 报告
  GET  /api/demo.docx            下载示例预案

隐私：上传的文件只在审查期间临时保存，审查结束立即删除；结果只存在内存里，服务重启就没了。

启动：uvicorn plan_review.api:app --port 8000（需要先把 src 放进 PYTHONPATH）
"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

from plan_review.agent import review, to_markdown

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / 'web'
DEMO = ROOT / 'data' / 'demo' / '示例预案_虚构.docx'
MAX_BYTES = 30 * 1024 * 1024
MAX_JOBS = 50

app = FastAPI(title='应急预案智能审查 Agent', version='0.1.0')
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()


def _run(job_id: str, path: Path, use_llm: bool, profile: str, delete_after: bool):
    def on_step(node, trace):
        with LOCK:
            JOBS[job_id]['trace'] = list(trace)
            JOBS[job_id]['stage'] = node
    try:
        result = review(str(path), use_llm=use_llm, extra_profile=profile, on_step=on_step)
        with LOCK:
            JOBS[job_id].update(status='done', result=result, finished=time.time())
    except Exception as e:                      # 出错也要告诉前端，不能让它一直转圈
        with LOCK:
            JOBS[job_id].update(status='error', error=f'{type(e).__name__}: {e}')
    finally:
        if delete_after:
            shutil.rmtree(path.parent, ignore_errors=True)


def _start(path: Path, name: str, use_llm: bool, profile: str, delete_after: bool) -> dict:
    job_id = uuid.uuid4().hex[:12]
    with LOCK:
        if len(JOBS) >= MAX_JOBS:                # 只在内存里留最近的任务
            oldest = min(JOBS, key=lambda k: JOBS[k]['created'])
            JOBS.pop(oldest)
        JOBS[job_id] = {'id': job_id, 'name': name, 'status': 'running', 'stage': '排队中', 'trace': [],
                        'use_llm': use_llm, 'created': time.time()}
    threading.Thread(target=_run, args=(job_id, path, use_llm, profile, delete_after), daemon=True).start()
    return {'id': job_id}


@app.get('/api/health')
def health():
    return {'ok': True, 'llm_configured': bool(os.environ.get('DEEPSEEK_API_KEY'))}


@app.post('/api/reviews')
async def create_review(file: UploadFile = File(...), use_llm: bool = Form(False), profile: str = Form('')):
    if not (file.filename or '').lower().endswith('.docx'):
        raise HTTPException(400, '只支持 .docx 文件（.doc 请先用 Word/WPS 另存为 .docx）')
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, '文件超过 30MB')
    if data[:2] != b'PK':
        raise HTTPException(400, '这不是有效的 .docx 文件')
    folder = Path(tempfile.mkdtemp(prefix='plan_review_'))
    path = folder / 'upload.docx'
    path.write_bytes(data)
    return _start(path, file.filename, use_llm, profile[:2000], delete_after=True)


@app.post('/api/reviews/demo')
def create_demo_review(use_llm: bool = Form(False)):
    if not DEMO.exists():
        raise HTTPException(500, '示例文件不存在，请先运行 scripts/make_demo_docx.py')
    profile = '新材料技术研发实验室，租用产业园一栋楼的第5层，员工6人；没有生产车间、仓库、叉车等生产设施。'
    return _start(DEMO, DEMO.name, use_llm, profile, delete_after=False)


@app.get('/api/reviews/{job_id}')
def get_review(job_id: str):
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(404, '任务不存在（服务重启后结果会清空）')
        return dict(job)


@app.get('/api/reviews/{job_id}/report.md', response_class=PlainTextResponse)
def get_report(job_id: str):
    job = get_review(job_id)
    if job['status'] != 'done':
        raise HTTPException(409, '审查还没完成')
    return PlainTextResponse(to_markdown(job['result'], job['name']), media_type='text/markdown; charset=utf-8')


@app.get('/api/demo.docx')
def demo_file():
    return FileResponse(DEMO, filename='示例预案_虚构.docx')


@app.get('/')
def index():
    return FileResponse(WEB / 'index.html')

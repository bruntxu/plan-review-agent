"""测试 Agent 流程和 HTTP 接口（用虚构示例预案，不调用大模型）。
需要虚拟环境：.venv\\Scripts\\python.exe tests/test_api.py"""
import io
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
os.environ.pop('DEEPSEEK_API_KEY', None)          # 测试里不花钱

from fastapi.testclient import TestClient          # noqa: E402
from plan_review.agent import review                # noqa: E402
from plan_review.api import app, DEMO               # noqa: E402

client = TestClient(app)
EXPECTED = ['T1', 'T3', 'T5', 'T9']


def wait(job_id, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        job = client.get(f'/api/reviews/{job_id}').json()
        if job['status'] != 'running':
            return job
        time.sleep(0.2)
    raise TimeoutError


def test_agent_finds_planted_errors():
    r = review(str(DEMO))
    assert r['plan'] == ['T9', 'T1', 'T3', 'T5']                  # 没开大模型，计划里没有 T4
    assert set(r['stats']['by_check']) == set(EXPECTED)
    assert r['findings'][0]['severity'] == '严重'                  # 文档损坏排在最前面
    assert [t['node'] for t in r['trace']] == ['解析文档', '制定计划', '规则检查', '汇总定级', '写审查结论']


def test_llm_requested_but_no_key_is_skipped_with_reason():
    r = review(str(DEMO), use_llm=True)
    assert 'T4' not in r['plan']
    assert '没有配置 DEEPSEEK_API_KEY' in r['trace'][1]['message']


def test_health():
    assert client.get('/api/health').json() == {'ok': True, 'llm_configured': False}


def test_upload_and_report():
    data = DEMO.read_bytes()
    r = client.post('/api/reviews', files={'file': ('示例.docx', data)}, data={'use_llm': 'false'})
    assert r.status_code == 200
    job = wait(r.json()['id'])
    assert job['status'] == 'done' and job['result']['stats']['total'] >= 10
    md = client.get(f'/api/reviews/{job["id"]}/report.md').text
    assert md.startswith('# 审查报告：示例.docx') and '| 严重 |' in md


def test_demo_endpoint():
    job = wait(client.post('/api/reviews/demo', data={'use_llm': 'false'}).json()['id'])
    assert job['status'] == 'done'


def test_rejects_non_docx():
    assert client.post('/api/reviews', files={'file': ('a.pdf', b'%PDF')}).status_code == 400
    assert client.post('/api/reviews', files={'file': ('a.docx', b'not a zip')}).status_code == 400


def test_index_page():
    r = client.get('/')
    assert r.status_code == 200 and '应急预案智能审查' in r.text


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('通过', name)

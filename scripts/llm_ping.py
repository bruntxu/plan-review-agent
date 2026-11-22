"""验证 DeepSeek API Key 是否可用（不会打印 Key）。用法：python scripts/llm_ping.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from plan_review.llm import DeepSeek, NoApiKey   # noqa: E402

try:
    llm = DeepSeek()
except NoApiKey as e:
    print('未连接：', e)
    sys.exit(1)
reply = llm.chat_json('你是一个测试助手。只输出 JSON。', '请返回 {"ok": true, "msg": "已连接"}')
u = llm.usage
print(f'已连接：模型回复 {reply}；本次 {u.prompt_tokens}+{u.completion_tokens} tokens，约 {u.cost_yuan:.5f} 元，用时 {u.seconds:.1f} 秒')

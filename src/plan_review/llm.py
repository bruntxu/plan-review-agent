"""调用 DeepSeek（OpenAI 兼容格式）。只用标准库 urllib，不装 SDK。

- API Key 从环境变量 DEEPSEEK_API_KEY 读取，代码里不出现 Key。
- 每次调用都记账：用了多少 tokens、大约花多少钱。
- 发送前过一道安全网：如果内容里还有手机号或信用代码（说明脱敏漏了），直接拒绝发送。
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

API_URL = 'https://api.deepseek.com/chat/completions'
MODEL = 'deepseek-flash'
# 2026-11 官方价格，单位：元 / 百万 tokens，按高峰价估算（偏保守）
PRICE_IN, PRICE_OUT = 2.0, 8.0

_LEAK_RE = re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)|(?<![0-9A-Z])[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}(?![0-9A-Z])')


class NoApiKey(RuntimeError):
    pass


class LeakBlocked(RuntimeError):
    pass


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    parse_errors: int = 0      # 重试后仍解析失败、只能当作"没发现"的块数

    @property
    def cost_yuan(self) -> float:
        return (self.prompt_tokens * PRICE_IN + self.completion_tokens * PRICE_OUT) / 1e6


@dataclass
class DeepSeek:
    model: str = MODEL
    thinking: bool = False
    timeout: int = 180
    usage: Usage = field(default_factory=Usage)

    def __post_init__(self):
        self.key = os.environ.get('DEEPSEEK_API_KEY', '').strip()
        if not self.key:
            raise NoApiKey('没有找到环境变量 DEEPSEEK_API_KEY，见 docs/DeepSeek接入.md')

    def chat_json(self, system: str, user: str) -> dict:
        """发一轮对话，要求模型返回 JSON，解析成 dict 返回。
        模型偶尔会返回格式坏掉的 JSON（比如引号没转义），这时重试一次；还不行就返回空结果并记一笔。"""
        for attempt in range(2):
            content = self._call(system, user)
            parsed = _parse_json(content)
            if parsed is not None:
                return parsed
        self.usage.parse_errors += 1
        return {}

    def _call(self, system: str, user: str) -> str:
        leaks = _LEAK_RE.findall(system + user)
        if leaks:
            raise LeakBlocked(f'待发送内容里还有 {len(leaks)} 处疑似手机号或信用代码，已拒绝发送')
        body = {
            'model': self.model,
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
            'response_format': {'type': 'json_object'},
            'thinking': {'type': 'enabled' if self.thinking else 'disabled'},
            'stream': False,
        }
        req = urllib.request.Request(
            API_URL, data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {self.key}'})
        t0 = time.perf_counter()
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                break
            except urllib.error.HTTPError as e:
                msg = e.read().decode('utf-8', 'replace')[:300]
                if e.code in (429, 500, 502, 503) and attempt < 2:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise RuntimeError(f'DeepSeek 返回 {e.code}：{msg}') from None
            except (urllib.error.URLError, TimeoutError):
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise
        self.usage.calls += 1
        self.usage.seconds += time.perf_counter() - t0
        u = data.get('usage', {})
        self.usage.prompt_tokens += u.get('prompt_tokens', 0)
        self.usage.completion_tokens += u.get('completion_tokens', 0)
        return data['choices'][0]['message']['content'] or '{}'


def _parse_json(content: str) -> dict | None:
    for candidate in (content, (re.search(r'\{.*\}', content, re.S) or [None])[0]):
        if not candidate:
            continue
        try:
            value = json.loads(candidate)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            continue
    return None


class FakeLLM:
    """测试用：不联网，按预设规则返回结果，同时记下收到的内容。"""

    def __init__(self, respond):
        self.respond = respond
        self.received: list[str] = []
        self.usage = Usage()

    def chat_json(self, system: str, user: str) -> dict:
        if _LEAK_RE.findall(system + user):
            raise LeakBlocked('fake: leak')
        self.received.append(user)
        self.usage.calls += 1
        return self.respond(user)

# DeepSeek API 接入步骤（需要你自己操作）

查询日期 2026-11-22，来源：DeepSeek 官方文档 api-docs.deepseek.com。

## 1. 注册并充值

1. 打开 https://platform.deepseek.com ，用手机号注册并登录。
2. 在"充值"页面充 10–20 元就够了。整个项目估计只花几块钱，审一份 180 页的预案大约几毛钱。
3. 价格（`deepseek-flash`，每百万 tokens）：输入 1–2 元，输出 4–8 元。工作日 9:00–12:00 和 14:00–18:00 是高峰时段，价格翻倍；晚上和周末是半价。

## 2. 创建 API Key

1. 左侧菜单进"API keys"→"创建 API key"，名字随便填，比如 `plan-review`。
2. 页面会显示一串 `sk-...` 开头的字符。**它只显示这一次**，马上复制。
3. **不要把 Key 发给任何人，也不要贴到聊天里、写进代码、传上 GitHub。** 谁拿到它，谁就能用你的余额。

## 3. 把 Key 存成环境变量（只做一次）

打开 PowerShell，粘贴下面这行，把 `sk-你的key` 换成你刚复制的 Key，然后回车：

```powershell
[Environment]::SetEnvironmentVariable("DEEPSEEK_API_KEY", "sk-你的key", "User")
```

然后**完全退出 Claude 桌面应用再重新打开**，新的环境变量才会生效。

## 4. 验证

告诉我"Key 设好了"就行，不用把 Key 发给我。我会运行：

```bash
python scripts/llm_ping.py
```

它只会打印"已连接"和这次花了多少 tokens，不会显示 Key。

## 我们用的配置

| 项 | 值 |
|---|---|
| 接口地址 | `https://api.deepseek.com/chat/completions`（OpenAI 兼容格式） |
| 模型 | `deepseek-flash`（便宜、快，支持 JSON 输出，上下文 1M） |
| 思考模式 | 默认关闭（`thinking: disabled`）。判断类任务不需要长推理，关掉更省钱；需要时可以单独打开 |
| 输出格式 | `response_format: json_object`，让模型按固定格式返回，程序好解析 |

# Qwen API 接入

项目提供两层入口：

- `POST /api/agent/chat`：服务端直接调用通义千问 DashScope，再把模型输出交给本地白名单路由器校验。
- `POST /api/agent/llm`：给已经由外部模型生成的 `model_output` 做验证，便于替换模型或离线测试。

## 配置 API Key

只在启动服务的服务端终端设置环境变量，浏览器不会接触 Key。PowerShell 示例：

```powershell
$env:DASHSCOPE_API_KEY = "你的 DashScope API Key"
$env:QWEN_MODEL = "qwen-plus"       # 可选，默认 qwen-plus
$env:QWEN_TIMEOUT_SECONDS = "30"    # 可选
python server.py
```

也可以设置 `QWEN_BASE_URL` 覆盖兼容 OpenAI 的接口地址；默认地址是
`https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`。

## 调用接口

```http
POST /api/agent/chat
Content-Type: application/json
Origin: http://127.0.0.1:18130
X-Demo-Token: <页面启动时生成的会话 Token>

{"message":"分析 2026 年 9 月账单，并告诉我有没有异常","context":{}}
```

返回值会包含 `source: "qwen"`、`model`、`tool_results`、`evidence_ids` 和 `requires_confirmation`。账单金额、卡片状态和订单状态由服务端重新计算，模型只能请求白名单查询或预览工具。卡片锁定、订单确认、账本写入等动作仍必须经过独立确认接口。

未设置 `DASHSCOPE_API_KEY` 或模型调用失败时，助手回退到本地规则，并在结果中标明来源和回退原因；不会声称已完成真实模型调用。

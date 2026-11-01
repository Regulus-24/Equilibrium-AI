# 衡智 Equilibrium AI

金枢智能（FinNexus）的本机金融助手研究原型，覆盖账单分析、理财条件比较和模拟卡片管理；不接入真实银行，不执行真实交易。

**队友首次使用请先阅读 [交接说明 HANDOFF.md](HANDOFF.md)**，包含代码拉取、启动、可选模型配置、更新内容、验收步骤和待人工验证项目。

- [本次审核版更新说明](RELEASE_NOTES_2026-11-01.md)
- [Demo 详细说明与历史记录](demo-v0.1/README.md)
- [模型接口配置](LLM_INTEGRATION.md)
- [理财数据源说明](WEALTH_PROVIDERS.md)

快速启动（Python 3.11+）：

```powershell
cd demo-v0.1
python server.py
```

浏览器打开 http://127.0.0.1:18128/；按 `Ctrl+C` 停止服务。运行数据仅保存在本机，不随仓库同步。

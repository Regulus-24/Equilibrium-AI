# 衡智 Equilibrium AI — 队友交接说明

更新日期：2026-11-01。对应功能审核版提交：`44dfca7`；之后的交接文档提交不改变该功能版本。最新代码以仓库 `main` 为准。

## 1. 拉取代码

仓库：[Regulus-24/Equilibrium-AI](https://github.com/Regulus-24/Equilibrium-AI)。准备 Git 和 Python 3.11 或以上版本，以下命令使用 PowerShell。

首次下载：

```powershell
git clone https://github.com/Regulus-24/Equilibrium-AI.git
cd Equilibrium-AI
```

已有本地仓库：

```powershell
cd Equilibrium-AI
git status
git switch main
git pull --ff-only origin main
git log -1 --oneline
```

如果有未提交修改，先提交或暂存自己的工作再更新。遇到分支分叉或冲突，不要使用强制覆盖；先核对双方改动。此文档提交后，最新提交号会不同于功能审核版 `44dfca7`，属于正常情况。

## 2. 启动应用

应用使用 Python 标准库，启动不需要安装前端依赖。

```powershell
cd demo-v0.1
python --version
python server.py
```

打开 **http://127.0.0.1:18128/**。保持终端运行，按 `Ctrl+C` 停止。若系统只有 `py` 命令，可使用 `py -3.11 server.py`（需已安装 Python 3.11）。

端口被占用时：

```powershell
python server.py --port 18129
```

随后访问 http://127.0.0.1:18129/。

账本、设置和反馈默认保存在 `demo-v0.1/data/`，不会通过 GitHub 同步。完整备份前先停止服务，再复制整个目录；页面里的“备份账本”不包含全部基金设置、记录和反馈。不要把真实账单、密钥、日志或运行数据提交仓库。

## 3. 配置可选模型接口

建议先不配密钥，确认基本功能可用。未配置模型或调用失败时，助手会回退本地规则，并明确显示来源与回退原因。

需要验证 Qwen 时，在**启动服务的同一个 PowerShell 窗口**设置环境变量：

```powershell
$env:DASHSCOPE_API_KEY = "<填写自己的 DashScope API Key>"
$env:QWEN_MODEL = "qwen-plus"
$env:QWEN_TIMEOUT_SECONDS = "30"
python server.py
```

以上命令在 `demo-v0.1` 目录执行。修改配置后重启服务。密钥只放服务端环境变量，不写进源码、不提交 GitHub、不发到群里。当前代码不会自动读取 `.env` 文件。

高级配置可设置 `QWEN_BASE_URL`，其值必须是完整请求端点，默认：

```text
https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
```

其他兼容接口尚未逐一验证。模型负责理解和规划，金额、状态核验及写操作确认仍由服务端控制。模型测试使用合成数据；输入的问题和上下文会发送给模型服务。

详细接口见 [模型配置说明](LLM_INTEGRATION.md)。

## 4. 本次更新

- **账单**：CSV/XLSX 导入预览、重复识别、版本冲突保护、可选卡片尾号绑定。
- **预算**：用户主动设置月度和分类预算，展示已用、剩余及超支提示，不根据历史自动推断预算目标。
- **理财比较**：持有期限、到账日期、新鲜度、排除原因和并列方案；资料不足不推荐，行情版本变化使旧比较失效。
- **异常案件**：状态流转与证据记录；关联卡片完成锁卡核验后，案件才能标记“已锁卡”。
- **提醒与演示**：ICS 导出、固定演示数据、一键清理、完整证据包。
- **恢复流程**：导入失败、版本冲突、行情失败、ICS 失败和案件冲突提供恢复入口。

重点修复跨文件导入 ID 冲突、预算用量不刷新、导入取消卡住、ICS 重试、案件与卡片状态不一致。完整记录见 [审核版更新说明](RELEASE_NOTES_2026-11-01.md)。

## 5. 建议验收顺序

1. 进入“卡片管理”，点击“准备演示数据”。
2. 预览锁卡并取消，确认卡片状态不变。
3. 再次预览，勾选确认，检查锁卡回执。
4. 验证重复锁卡后的重置，以及清理演示。
5. 导入合成账单，设置预算并检查统计。
6. 下载 ICS、分析报告和完整证据包。

自动化回归，在 `demo-v0.1` 目录执行：

```powershell
python -m unittest discover -q
```

本次功能发布检查：**95 项测试通过，全部前端 JavaScript 语法检查通过**。七个页面主要流程及关键故障恢复已在内置浏览器验证。前端语法检查需要额外安装 Node.js，应用启动本身不需要：

```powershell
Get-ChildItem web/*.js | ForEach-Object { node --check $_.FullName }
```

## 6. 仍需人工验证

- Edge、Chrome、Firefox/Safari 的实际兼容性；Edge 自动化受工具限制，未列为通过。
- Android/iOS 真机触摸、软键盘、文件选择及下载。
- ICS 导入系统日历后的日期、中文内容和重复事件表现。
- 配置真实密钥后的模型调用、超时及回退提示。
- 授权行情渠道、长时间后台运行及辅助功能。

320px、375px、768px 模拟视口已检查，但不能替代手机真机。公开行情已验证，腾讯授权适配器需另行提供合法授权配置，见 [理财数据源说明](WEALTH_PROVIDERS.md)。

当前仍是本机单用户研究原型，没有真实银行接入，不执行真实交易，不应公开部署或承载真实金融账户。

## 7. 问题反馈

请记录：提交号、浏览器/设备、复现步骤、预期结果、实际结果和截图。截图、日志及附件不要包含密钥或真实敏感账单。

[返回仓库首页](README.md) · [Demo 详细说明](demo-v0.1/README.md)

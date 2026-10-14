# 账单分析 JSON 契约与现有数据核对

日期：2026-10-13  
来源：用户明确授权读取本地项目，并要求先依据已有账单整理交易字段、收支口径和 JSON 数据契约。

## 状态

进行中：事实层和自然语言层 Schema 已写入 Demo；尚未接入 DeepSeek，也尚未把契约接入 `/api/insights/report` 的运行校验。

## 已核对事实

- 当前手动账本字段：`id`、`revision`、`kind`、`cents`、`date`、`category`、`note`。
- 金额按整数分保存；`kind` 只有 `income` 和 `expense`。
- 当前账本样例有 3 笔支出、无收入、无明确可用余额。
- 2026-09 对 2026-08 的现有报告：本期支出 4180 分，上期支出 7450 分，差额 -3270 分，比例 -4389 个基点；储蓄率为空；当前记录因历史不足不能生成金额偏离候选。
- `net_cents` 只表示已记录收入减支出，不是银行余额或可投资金额。

## 产物

- `demo-v0.1/schemas/bill-analysis-facts-v1.json`
- `demo-v0.1/schemas/bill-analysis-narrative-v1.json`
- `docs/账单分析JSON数据契约-v1.md`
- `demo-v0.1/test_bill_contract.py`

## 下一步

1. 用 `SchemaStore` 给事实层增加运行时校验，并把当前 `report()` 输出转换成事实契约。
2. 建立独立合成样例，覆盖收入、退款/转账局限、缺少比较期、零基数、当前月未结束和明确可用余额缺失。
3. 再接 DeepSeek，只传事实层；模型输出通过自然语言层 Schema 和账本版本校验。

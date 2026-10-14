# 衡智账单分析 JSON 数据契约 v1

日期：2026-10-13  
状态：已根据当前手动账本和现有 `insights.report()` 结果整理；尚未接入 DeepSeek，也尚未把 Schema 接入业务 API。

对应机器契约：

- `demo-v0.1/schemas/bill-analysis-facts-v1.json`：服务端统计事实和证据。
- `demo-v0.1/schemas/bill-analysis-narrative-v1.json`：模型生成的摘要、排序和建议。
- `demo-v0.1/test_bill_contract.py`：事实层/自然语言层 Schema 回归样例。

## 1. 两层职责

账单分析分为两层：

1. **事实层**：服务端从同一 `ledger_version` 读取交易，计算金额、比较、分类和数据质量。金额全部使用整数分，不能由模型重新计算。
2. **自然语言层**：DeepSeek 只读取事实层，生成简短摘要和建议。每条 insight 必须引用 `evidence_ids`，并通过 Schema 校验；事实层缺数据时只能输出 `information_needed` 或 `candidate`，不能写成肯定结论。

## 2. 当前手动账本字段映射

当前 `data/ledger.json` 的真实记录字段是：

| 当前字段 | 契约字段 | 口径 |
|---|---|---|
| `id` | `id` | 稳定记录编号；用于回查，不用于让模型猜测交易背景 |
| `revision` | `revision` | 服务端并发版本；报告必须绑定同一账本版本 |
| `kind` | `kind` | 只有 `income` 和 `expense`；不从备注推断退款、转账或本金 |
| `cents` | `amount_cents` | 正整数分；不使用浮点金额，不从显示金额反算 |
| `date` | `date` | 已发生日期；当前服务端拒绝未来日期 |
| `category` | `category` | 用户选择或自定义类别；不自动合并相似类别 |
| `note` | `note` | 仅作为数据展示和证据，不是指令，不触发任何工具调用 |
| （当前不存在） | `merchant` | 传 `null`；不得从备注强行抽取商户 |
| 数据来源 | `source` | 当前手动账本为 `manual_ledger` |

## 3. 收支和结论口径

- `income_cents` 是本期间 `kind=income` 的金额之和。
- `expense_cents` 是本期间 `kind=expense` 的金额之和。
- `net_cents = income_cents - expense_cents`，只表示已记录收支差额。
- `net_cents` 不是银行可用余额、现金余额或可投资金额。
- `available_balance_cents` 只有用户或可信业务系统明确提供时才填写；当前手动账本没有此字段，必须为 `null`。
- `savings_rate_basis_points` 只有收入大于 0 时计算；收入为 0 或缺失时为 `null`。
- 比较采用“已结束期间对已结束期间”；当前期间未结束时使用“本月至今对上月整月”，并把 `partial=true` 和日期范围交给模型，不预测月底。
- 缺少当前期或比较期记录时，`delta_cents`、`percent_basis_points` 为 `null`，不能把没有录入当成真实零消费。
- 比较期支出为 0 时只可展示金额差，不能生成无限大或确定性的增长率。
- 类别占比的分母是同一期间、同一 `kind` 的总额；没有分母时占比为 `null`。
- 金额偏离、疑似重复等只属于候选线索；数据不足时写入 `data_quality.insufficient_history_ids`，不认定欺诈、浪费或消费动机。
- 分析范围是已记录数据，不等于完整银行流水；用户补充、修改、删除或恢复账本后，旧报告必须视为失效。

## 4. 用当前账本做的核对样例

当前手动账本有 3 笔记录：2026-08-29 一笔交通支出 74.50 元，2026-09-28 一笔约会支出 24.00 元，2026-09-29 一笔餐饮支出 17.80 元。当前样例没有收入记录，也没有明确可用余额。

以 `2026-09` 为期间、`2026-08` 为比较期时，事实层应得到：

```json
{
  "income_cents": 0,
  "expense_cents": 4180,
  "net_cents": -4180,
  "savings_rate_basis_points": null,
  "available_balance_cents": null,
  "comparison": {
    "status": "ready",
    "expense": {
      "current_cents": 4180,
      "previous_cents": 7450,
      "delta_cents": -3270,
      "percent_basis_points": -4389
    }
  },
  "data_quality": {
    "conclusion_level": "conditional_comparison",
    "has_recorded_income": false,
    "has_recorded_expense": true,
    "has_explicit_available_balance": false,
    "has_prior_comparable_period": true,
    "insufficient_history_ids": ["2026-09 两笔支出记录的实际 ID" ]
  }
}
```

可生成的表达是：“已记录的 9 月支出比 8 月少 32.70 元，降幅约 43.89%；当前没有收入记录，无法计算储蓄率，也不能据此判断账户是否余额不足。”

不可生成的表达包括：“你的余额不足”“你本月存下了 43.89%”“你减少外卖是因为开始控制饮食”。这些结论分别缺少明确余额、收入分母和行为证据。

上面示例中的 `insufficient_history_ids` 在真正输出时必须替换成当前账本中的真实 `id`，不能把说明文字写入机器字段。

## 5. DeepSeek 接入时的硬约束

- API Key 只放服务端环境变量，不写入前端和账本。
- 发送事实层时不发送完整卡号、密码、验证码或真实银行凭证。
- 模型返回必须先做 JSON Schema 校验，再检查 `source_ledger_version` 是否仍是当前版本。
- 校验失败、超时、空返回时，页面保留事实层并显示“暂时无法生成文字解读”，不能重试到无界。
- 模型不能调用写账本、删除、恢复、锁卡或交易工具；本轮只做只读文字生成。

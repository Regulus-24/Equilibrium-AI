# 理财数据源与自定义产品

## 默认数据源

`eastmoney_public` 读取公开货币基金历史行情，适合本地演示和无账号跟踪。页面展示最新披露日期，不把披露日期冒充实时成交价。

## 腾讯理财通授权适配器

选择 `tencent_licensed` 后，服务端读取：

```powershell
$env:TENCENT_LCT_API_BASE_URL = "https://合作方提供的授权域名/v1"
$env:TENCENT_LCT_API_TOKEN = "服务端专用令牌"
```

适配器调用约定：`GET {base_url}/products/{code}`，返回 JSON 数组或 `{ "data": [...] }`，每条至少包含 `date` 和 `per10k`，可选 `annual7`、`nav`。这是项目内部适配契约，不是腾讯消费者端公开 API 的声明。

个人理财通网页登录、验证码、抓包和自动交易不属于实现范围。没有授权接口时，更新任务会记录失败并保留历史数据。

## 自定义产品

前端“理财跟踪”页可新增产品代码和名称。新增产品必须选择腾讯授权数据源，随后勾选加入每日跟踪。服务端接口为 `POST /api/funds/product/add`。

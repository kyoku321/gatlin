# 通信行业信息源调查报告

- 调查日期： 2026-09-04
- 测试方法：实际 HTTP 请求各候选源的 RSS/Atom feed 或 API，解析最新条目发布时间，判定是否在 1 个月内正常更新
- 结论：**已配置 21 个 RSS 源全部通过测试**（最新条目均在 2 天内），另配 Reddit / GitHub / Google News 补充渠道

## 交付物

| 文件 | 说明 |
|---|---|
| `data/config.telecom.json` | 通信行业专用配置（独立文件，不覆盖现有 AI 配置） |
| `profiles/telecom-news/` | 新增分析 profile（match.md / analysis.md / enrichment.md / profile.json） |

使用方式：运行时加 `--config data/config.telecom.json`（或 `-d` 指向单独数据目录）。

---

## 一、国际通信行业媒体 RSS（英文，全部已验证当天/当周更新）

| 源 | 覆盖范围 | 最新条目 |
|---|---|---|
| Light Reading | 运营商/5G/光网络，美国老牌电信媒体 | 2026-09-03 |
| Fierce Network | 无线/宽带/MVNO，报道过 Transatel 的 MVNE 签约 | 2026-09-03 |
| RCR Wireless News | 5G/Open RAN/私有网络 | 2026-09-03 |
| Mobile World Live | GSMA 旗下，全球运营商动态 | 2026-09-03 |
| Capacity Media | 海缆/批发/国际漫游 | 2026-09-04 |
| Total Telecom | 英国电信行业综合媒体 | 2026-09-03 |
| Telecom Reseller | 企业通信/运营商 B2B,MVNO-MVNE 交易多 | 2026-09-03 |
| Mobile Europe | 欧洲运营商动态 | 2026-09-03 |
| Developing Telecoms | 新兴市场运营商（新兴经济体 5G） | 2026-09-04 |
| GSMA Newsroom | GSMA 官方新闻稿 | 2026-09-03 |
| Network World | IDG 旗下，企业网络 | 2026-09-04 |
| The Mobile Network | 移动网络技术深入报道 | 2026-09-03 |
| Via Satellite | 卫星/NTN（直连终端、星座合作） | 2026-09-03 |

## 二、IoT / MVNO 垂直媒体

| 源 | 说明 | 最新条目 |
|---|---|---|
| IoT Business News | IoT 连接、模组、平台交易新闻 | 2026-09-03 |
| IoT Now | IoT/eSIM 行业媒体 | 2026-09-03 |
| IoT Insider | IoT 产业链 | 2026-09-03 |

## 三、日本市场媒体

| 源 | 说明 | 最新条目 |
|---|---|---|
| K-tai Watch (Impress) | 日本手机/运营商新闻，覆盖 KDDI/SoftBank/Docomo/楽天 | 2026-09-04 |
| WirelessWire News | 日本无线/移动产业专业媒体 | 2026-09-03 |

## 四、公司官方 Newsroom RSS

| 源 | 说明 | 最新条目 |
|---|---|---|
| Transatel Newsroom | 子公司官方，直接跟踪自家新闻稿 | 2026-09-02 |
| BT Newsroom | 英国电信 | 2026-09-04 |
| Telefonica Newsroom | 西班牙电信（EN） | 2026-09-03 |

## 五、KDDI / SoftBank / NTT DOCOMO 等无官方 RSS 的对策

经实测，**KDDI、SoftBank（集团及 SoftBank Corp）、NTT DOCOMO、Nokia、Ericsson、Verizon、T-Mobile、Orange、Vodafone 的官方新闻室均不存在公开可用的 RSS**（404 或被反爬拦截）。

解决方案：启用 `google_news` 源（无需 API key），配置为：

```
query: ("KDDI" OR "SoftBank" OR "NTT DOCOMO" OR "Transatel" OR "Rakuten Mobile" OR "MVNO")
locale: hl=ja, gl=JP
```

实测（2026-09-04）：日文检索返回 100 条、英文检索返回 44 条近 1 个月结果，可稳定覆盖日本运营商与 Transatel 的媒体报道。搜索词可按需增删（如需单独跟踪 KDDI，可改为更强约束的查询）。

## 六、社区与其他渠道

| 渠道 | 配置 | 状态 |
|---|---|---|
| Reddit r/telecom | min_score=3 | 活跃（本机被 Reddit 反爬拦截，无法直接测 API，经外部检索确认 2026-08 持续发帖） |
| Reddit r/5G | min_score=3 | 同上 |
| Reddit r/IoT | min_score=15 | 活跃 |
| Reddit r/esim | min_score=2 | 每日有帖（旅行 eSIM/MVNO 话题） |
| GitHub open5gs/open5gs | repo_releases | 开发活跃（2026-09-03 有提交，最近 release 2026-06） |
| GitHub free5gc/free5gc | repo_releases | 开发活跃（2026-09-02 有提交，最近 release 2026-06） |

- GDELT 源本次测试遭遇 429 限流（公司出口 IP 被限速），建议暂不启用；如恢复可作为公司名追踪的补充。

## 七、测试后放弃的源（备选记录）

| 源 | 放弃原因 |
|---|---|
| Telecoms.com | /feed 403 反爬 |
| TelecomTV | 已无公开 RSS（404） |
| SDxCentral | RSS 已下线（404） |
| VanillaPlus | 本站 SSL 握手异常 |
| Telecompaper | RSS 需付费订阅 |
| Stacey on IoT | 停更 2 个月+（2026-06-26） |
| 6GWorld | 停更 3 个月+（2026-06-11） |
| ITmedia Mobile | 旧 feed 已 302 下线 |
| C114.com.cn | 连接超时不可达 |
| srsran/srsRAN_Project | 最近 release 为 2025-11，超 1 个月 |
| magma/magma | 最近 release 为 2025-05 |
| opennetworkinglab/ONOS | 2024-06 后无开发活动 |
| Nokia/Ericsson/Verizon/T-Mobile/Orange/Vodafone 官方 | 无可用 RSS 或 403 |

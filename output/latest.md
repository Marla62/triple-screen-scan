# 候选清单 — 布林带回归 — 数据截至 2026-10-07（美东收盘）

生成时间（UTC）：2026-10-09T01:13:40+00:00  
股票池：517 只，有数据 512 只，候选 5 只  
大盘：SPY 2026-10-07 收盘 777.22，200 日均线 721.99，在均线之上 ✅（本策略不带过滤，仅供参考）  
全池回测（同一规则）：3812 笔，胜率 64.2%，盈亏比 0.77，单笔期望 0.78%，平均持有 9.3 天

入场：收盘 > 200 日均线 且 收盘 < 布林下轨(20,2) → 次日开盘买入；收盘 ≥ 中轨(20 日均线) → 次日开盘卖出；3×ATR 保护止损；最多持 15 天  
出场：止损 = 入场价 − 3×ATR；收盘 ≥ 20 日均线(中轨) → 次日开盘卖出；最多持有 15 个交易日  
胜率来自每只股票自身约 3 年的回测（含 0.05% 往返成本）。排序用“修正胜率”= Wilson 95% 置信下界，样本越少向下修正越多（10 笔 10 胜 ≈ 72%）；笔数 < 8 另标注样本不足。

| # | 代码 | 名称 | 状态 | 收盘 | ATR14 | 参考价(收盘) | 初始止损 | 止盈 | 每股风险 | 每$1万可买 | 修正胜率 | 原始胜率 | 笔数 | 盈亏比 | 单笔期望 | 平均持有天 | 模拟持仓 |
|--:|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| 1 | **DE** | Deere & Company | 新信号 | 656.87 | 18.65 | 656.87 | 600.93 |  | 55.94 | 3 | **61.0%** | ⚠️样本不足 100.0% | 6 |  | 3.98% | 6.5 |  |
| 2 | **WELL** | Welltower | 新信号 | 221.12 | 4.93 | 221.12 | 206.33 |  | 14.79 | 13 | **46.8%** | 75.0% | 12 | 1.00 | 2.16% | 8.2 | 持有中 2026-09-21 入场 229.26，止损 214.43 |
| 3 | **PFG** | Principal Financial Gr | 新信号 | 108.73 | 2.29 | 108.73 | 101.86 |  | 6.87 | 29 | **37.6%** | ⚠️样本不足 80.0% | 5 | 0.57 | 1.41% | 9.4 | 持有中 2026-10-07 入场 109.03，止损 101.90 |
| 4 | **SOLV** | Solventum | 新信号 | 85.88 | 1.90 | 85.88 | 80.17 |  | 5.71 | 35 | **9.5%** | ⚠️样本不足 50.0% | 2 | 0.71 | -1.66% | 2.0 |  |
| 5 | **TGT** | Target Corporation | 新信号 | 150.92 | 3.75 | 150.92 | 139.68 |  | 11.24 | 17 | **6.1%** | ⚠️样本不足 33.3% | 3 | 1.88 | -0.14% | 7.7 |  |

## 运行提示

- 纳斯达克 100 来源 wikipedia 只解析到 0 只，换下一个来源
- 纳斯达克 100 来源 invesco_qqq 失败: HTTPError('406 Client Error: Not Acceptable for url: https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0?audienceType=Investor&action=download&ticker=QQQ')
- 纳斯达克 100 名单全部来源失败，使用内置兜底名单
- yfinance 缺 3 只，尝试 stooq 兜底
- stooq EA: ConnectTimeout(MaxRetryError("HTTPSConnectionPool(host='stooq.com', port=443): Max retries exceeded with url: /q/d/l/?s=ea.us&i=d&d1=20221009 (Caused by ConnectTimeoutError(<HTTPSConnection(host='stooq.com', port=443) at 0x7f0c94c3eb70>, 'Connection to stooq.com timed out. (connect timeout=20)'))"))
- stooq PSKY: ConnectTimeout(MaxRetryError("HTTPSConnectionPool(host='stooq.com', port=443): Max retries exceeded with url: /q/d/l/?s=psky.us&i=d&d1=20221009 (Caused by ConnectTimeoutError(<HTTPSConnection(host='stooq.com', port=443) at 0x7f0c94b033b0>, 'Connection to stooq.com timed out. (connect timeout=20)'))"))
- stooq WBD: ConnectTimeout(MaxRetryError("HTTPSConnectionPool(host='stooq.com', port=443): Max retries exceeded with url: /q/d/l/?s=wbd.us&i=d&d1=20221009 (Caused by ConnectTimeoutError(<HTTPSConnection(host='stooq.com', port=443) at 0x7f0c94b3b290>, 'Connection to stooq.com timed out. (connect timeout=20)'))"))

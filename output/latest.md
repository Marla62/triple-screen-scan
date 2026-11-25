# 候选清单 — 布林带回归 — 数据截至 2026-11-24（美东收盘）

**仅供研究，尚无样本外验证，不是实盘买入建议；当前股票池仍有幸存者偏差。**

生成时间（UTC）：2026-11-25T04:09:13+00:00  
股票池：518 只，有数据 513 只，候选 2 只  
大盘：SPY 2026-11-24 收盘 718.78，200 日均线 733.04，在均线之下 ⛔（本策略不带过滤，仅供参考）  
全池回测（同一规则）：3726 笔，胜率 64.4%，盈亏比 0.74，单笔期望 0.75%，平均持有 9.2 天

入场：收盘 > 200 日均线 且 收盘 < 布林下轨(20,2) → 次日开盘买入；收盘 ≥ 中轨(20 日均线) → 次日开盘卖出；3×ATR 保护止损；最多持 15 天  
出场：止损 = 入场价 − 3×ATR；收盘 ≥ 20 日均线(中轨) → 次日开盘卖出；最多持有 15 个交易日  
仓位：单笔初始风险0.5%、单票金额10%、合计初始风险2%；风险含预计买卖费用，现金含买入费，按最严约束取整股；持仓不因浮盈释放原始风险。每 $10,000 全现金无其他持仓账户的研究示例，非实盘建议；实际须扣除已有仓位及挂单占用。  
成本：每端按实际成交额扣0.025%的简化成本；未平仓仅扣买入端，不能保证覆盖真实IBKR费用、滑点或跳空。  
排序按当时可得的信号强度、代码；与组合模拟一致。单票胜率来自约 3 年历史，Wilson 下界只作诊断，笔数 < 8 标注样本不足；不能据此证明未来胜率。

| # | 代码 | 名称 | 状态 | 信号强度 | 收盘 | ATR14 | 参考价(收盘) | 初始止损 | 止盈 | 每股止损距离 | 每$1万示例股数 | 修正胜率 | 原始胜率 | 笔数 | 盈亏比 | 单笔期望 | 平均持有天 | 模拟持仓 |
|--:|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| 1 | **EBAY** | eBay Inc. | 新信号 | 0.245 | 113.77 | 3.99 | 113.77 | 101.79 |  | 11.98 | 4 | **45.3%** | 77.8% | 9 | 5.49 | 4.90% | 9.4 | 持有中 2026-11-23 入场 117.36，止损 106.03 |
| 2 | **HAS** | Hasbro | 新信号 | 0.064 | 112.24 | 3.10 | 112.24 | 102.95 |  | 9.29 | 5 | **13.7%** | 37.5% | 8 | 0.77 | -1.65% | 8.8 | 持有中 2026-11-20 入场 115.60，止损 106.15 |

## 运行提示

- 纳斯达克 100 来源 wikipedia 只解析到 0 只，换下一个来源
- 纳斯达克 100 来源 invesco_qqq 失败: HTTPError('406 Client Error: Not Acceptable for url: https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0?audienceType=Investor&action=download&ticker=QQQ')
- 纳斯达克 100 名单全部来源失败，使用内置兜底名单
- yfinance 缺 3 只，尝试 stooq 兜底
- stooq EA: ConnectTimeout(MaxRetryError("HTTPSConnectionPool(host='stooq.com', port=443): Max retries exceeded with url: /q/d/l/?s=ea.us&i=d&d1=20221125 (Caused by ConnectTimeoutError(<HTTPSConnection(host='stooq.com', port=443) at 0x7acab4f40470>, 'Connection to stooq.com timed out. (connect timeout=20)'))"))
- stooq VYLR: ConnectTimeout(MaxRetryError("HTTPSConnectionPool(host='stooq.com', port=443): Max retries exceeded with url: /q/d/l/?s=vylr.us&i=d&d1=20221125 (Caused by ConnectTimeoutError(<HTTPSConnection(host='stooq.com', port=443) at 0x7acab4d96570>, 'Connection to stooq.com timed out. (connect timeout=20)'))"))
- stooq WBD: ConnectTimeout(MaxRetryError("HTTPSConnectionPool(host='stooq.com', port=443): Max retries exceeded with url: /q/d/l/?s=wbd.us&i=d&d1=20221125 (Caused by ConnectTimeoutError(<HTTPSConnection(host='stooq.com', port=443) at 0x7acab4f49490>, 'Connection to stooq.com timed out. (connect timeout=20)'))"))
- 1 只数据日期 ≠ 2026-11-24，已排除候选: SNDK

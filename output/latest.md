# 候选清单 — 布林带回归 — 数据截至 2026-11-03（美东收盘）

**仅供研究，尚无样本外验证，不是实盘买入建议；当前股票池仍有幸存者偏差。**

生成时间（UTC）：2026-11-04T03:01:58+00:00  
股票池：518 只，有数据 512 只，候选 6 只  
大盘：SPY 2026-11-03 收盘 754.35，200 日均线 729.47，在均线之上 ✅（本策略不带过滤，仅供参考）  
全池回测（同一规则）：3719 笔，胜率 64.7%，盈亏比 0.76，单笔期望 0.82%，平均持有 9.2 天

入场：收盘 > 200 日均线 且 收盘 < 布林下轨(20,2) → 次日开盘买入；收盘 ≥ 中轨(20 日均线) → 次日开盘卖出；3×ATR 保护止损；最多持 15 天  
出场：止损 = 入场价 − 3×ATR；收盘 ≥ 20 日均线(中轨) → 次日开盘卖出；最多持有 15 个交易日  
仓位：单笔初始风险0.5%、单票金额10%、合计初始风险2%；风险含预计买卖费用，现金含买入费，按最严约束取整股；持仓不因浮盈释放原始风险。每 $10,000 全现金无其他持仓账户的研究示例，非实盘建议；实际须扣除已有仓位及挂单占用。  
成本：每端按实际成交额扣0.025%的简化成本；未平仓仅扣买入端，不能保证覆盖真实IBKR费用、滑点或跳空。  
排序按当时可得的信号强度、代码；与组合模拟一致。单票胜率来自约 3 年历史，Wilson 下界只作诊断，笔数 < 8 标注样本不足；不能据此证明未来胜率。

| # | 代码 | 名称 | 状态 | 信号强度 | 收盘 | ATR14 | 参考价(收盘) | 初始止损 | 止盈 | 每股止损距离 | 每$1万示例股数 | 修正胜率 | 原始胜率 | 笔数 | 盈亏比 | 单笔期望 | 平均持有天 | 模拟持仓 |
|--:|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| 1 | **ZBRA** | Zebra Technologies | 新信号 | 1.345 | 329.50 | 15.48 | 329.50 | 283.05 |  | 46.45 | 1 | **35.9%** | ⚠️样本不足 71.4% | 7 | 0.27 | -1.14% | 7.9 |  |
| 2 | **SHOP** | SHOP | 新信号 | 1.086 | 142.57 | 8.35 | 142.57 | 117.51 |  | 25.06 | 1 | **30.6%** | 62.5% | 8 | 0.39 | -1.79% | 7.5 |  |
| 3 | **PLTR** | Palantir Technologies | 新信号 | 0.297 | 175.40 | 8.70 | 175.40 | 149.30 |  | 26.10 | 1 | **45.3%** | 77.8% | 9 | 4.69 | 13.10% | 8.4 | 持有中 2026-11-03 入场 168.18，止损 143.09 |
| 4 | **AAPL** | Apple Inc. | 新信号 | 0.271 | 331.90 | 7.44 | 331.90 | 309.57 |  | 22.33 | 2 | **43.4%** | 72.7% | 11 | 0.98 | 1.93% | 9.1 |  |
| 5 | **DDOG** | Datadog | 新信号 | 0.203 | 220.52 | 15.84 | 220.52 | 173.01 |  | 47.51 | 1 | **25.0%** | ⚠️样本不足 57.1% | 7 | 0.84 | 0.29% | 9.9 | 持有中 2026-11-02 入场 235.51，止损 187.86 |
| 6 | **HSIC** | Henry Schein | 新信号 | 0.133 | 82.50 | 2.20 | 82.50 | 75.91 |  | 6.59 | 7 | **20.8%** | ⚠️样本不足 66.7% | 3 | 1.16 | 1.53% | 9.7 |  |

## 运行提示

- 纳斯达克 100 来源 wikipedia 只解析到 0 只，换下一个来源
- 纳斯达克 100 来源 invesco_qqq 失败: HTTPError('406 Client Error: Not Acceptable for url: https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0?audienceType=Investor&action=download&ticker=QQQ')
- 纳斯达克 100 名单全部来源失败，使用内置兜底名单
- yfinance 缺 4 只，尝试 stooq 兜底
- stooq EA: ConnectTimeout(MaxRetryError("HTTPSConnectionPool(host='stooq.com', port=443): Max retries exceeded with url: /q/d/l/?s=ea.us&i=d&d1=20221104 (Caused by ConnectTimeoutError(<HTTPSConnection(host='stooq.com', port=443) at 0x7f5238f8b770>, 'Connection to stooq.com timed out. (connect timeout=20)'))"))
- stooq KVUE: ConnectTimeout(MaxRetryError("HTTPSConnectionPool(host='stooq.com', port=443): Max retries exceeded with url: /q/d/l/?s=kvue.us&i=d&d1=20221104 (Caused by ConnectTimeoutError(<HTTPSConnection(host='stooq.com', port=443) at 0x7f5234e42c60>, 'Connection to stooq.com timed out. (connect timeout=20)'))"))
- stooq VYLR: ConnectTimeout(MaxRetryError("HTTPSConnectionPool(host='stooq.com', port=443): Max retries exceeded with url: /q/d/l/?s=vylr.us&i=d&d1=20221104 (Caused by ConnectTimeoutError(<HTTPSConnection(host='stooq.com', port=443) at 0x7f5234b43350>, 'Connection to stooq.com timed out. (connect timeout=20)'))"))
- stooq WBD: ConnectTimeout(MaxRetryError("HTTPSConnectionPool(host='stooq.com', port=443): Max retries exceeded with url: /q/d/l/?s=wbd.us&i=d&d1=20221104 (Caused by ConnectTimeoutError(<HTTPSConnection(host='stooq.com', port=443) at 0x7f5234d11040>, 'Connection to stooq.com timed out. (connect timeout=20)'))"))

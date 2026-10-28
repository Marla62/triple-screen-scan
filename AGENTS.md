# 持仓日报工作流

2026-10-27用户指定：扫描数据唯一来源为 GitHub 仓库 https://github.com/Marla62/triple-screen-scan 的 main 分支。每次直接读取远端 config.json、output/latest.json、output/latest.md、output/status.json；策略评估按需读取远端 output/lab.json 或 output/lab.md。禁止读取本地 output/、历史备份或旧缓存作为扫描数据，禁止在远端失败时回退本地。远端读取失败须报告“GitHub扫描数据不可用”，不使用旧信号给出新仓建议；远端可读但过期时标明日期且不作为当日信号。本地 portfolio/ 实盘台账继续保留，账户、持仓及订单仍从 IBKR 核实。不得恢复本机扫描任务。
本地 output/ 已移出工作区；不要恢复或读取。不要把本次本地扫描文件移除提交或推送到 GitHub，以免删除远端产物。

处理用户持仓/日报请求时，先读 portfolio/README.md、rules.json、trade-plans.json、latest.json、trades.jsonl 和 REPORT_TEMPLATE.md，再核对最新扫描与实盘。此前本地扫描与自动日报已取消，使用用户手动运行的 GitHub Actions。2026-10-26用户指定以后交易及入场/退出策略记录保存到本地portfolio台账；每次更新本地记录，未经用户明确要求不提交或推送；只提交相关记录，保护用户其他改动，不强推、不下单、不恢复本地任务。非日报的普通代码请求不自动提交推送。

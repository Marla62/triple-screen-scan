# 持仓日报工作流

处理用户持仓/日报请求时，先读 portfolio/README.md、rules.json、latest.json 和 REPORT_TEMPLATE.md，再核对最新扫描与实盘。此前本地扫描与自动日报已取消，使用用户手动运行的 GitHub Actions。每次用户手动要求日报，已授权更新portfolio记录并提交推送；只提交相关记录，保护用户其他改动，不强推、不下单、不恢复本地任务。非日报的普通代码请求不自动提交推送。

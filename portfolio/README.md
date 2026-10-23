# 真实持仓记录与手动日报入口

本目录用于跨会话保留实盘快照，不是扫描器模拟仓，不执行交易。

用户于2026-10-23明确授权：可在本公开仓库发布持仓、成交历史、账户净值及现金余额，并直接提交推送；禁止包含账号、账户标识、凭据或密钥。该授权适用于后续用户手动要求的日报更新。

## 新会话先读

1. `portfolio/rules.json`：用户已确认预算与退出规则。
2. `portfolio/latest.json`：最后一次 IBKR 实盘查询及观测时间，不代表当前实时状态。
3. `portfolio/trades.jsonl`：已查证成交；当前起始导入为2026-10-23查询的近30天记录，并非完整账户历史。
4. `portfolio/snapshots/YYYY-MM-DD.json` 和 `portfolio/reports/YYYY-MM-DD.md`：历史快照、报告。
5. `portfolio/REPORT_TEMPLATE.md`：日报格式与更新流程。
6. `config.json`、`output/latest.json`、`output/latest.md`、`output/status.json`：当次扫描，必要时读实验室。

用户手动运行 GitHub Actions 后，手动要求助手生成日报。已取消本机 launchd 扫描和 Codex 定时日报；不要自行恢复。GitHub 自带定时扫描仍保留，手动入口不变。

## 每次生成报告必须执行

- 先同步远端 main，检查工作区；保护用户未提交改动。不要强推。
- 刷新 IBKR 摘要、分币种现金、持仓、订单、必要成交及收益。失败时保留旧快照观测日期，单独记本次查询失败；不得把旧数据改成今天成功。
- 用户更新优先于旧文档。没有明确成交证据，不把建议或扫描 `sim_holdings` / `open_trade` 当持仓；没有归属证据，不追认策略。
- 核对最近完成的美股交易日、扫描 as_of、generated_at、缺失和错误。fresh 不等于全池完整。过期信号不给当日入场建议。
- 按模板生成中文报告；用代码计算资金/股数/止损，按资金、单票、分区、风险、合计风险的最严格约束向下取整，合并同票和主题敞口，不融资。
- 更新 latest.json、当日快照和当日报告；以后每次只增补成交，以 executed_at/symbol/side/quantity/price/commission 去重，保留历史。快照同日重查可覆盖当日版本，Git保留修改历史；其他日期不伪造补写。
- 用户已授权每次手动日报完成时，将必要持仓记录提交并推送到本仓库。只提交本次记录与必要说明，不夹带用户其他改动，不改扫描产物或策略代码。
- git diff --check；解析 JSON/JSONL，核对仓位、规则、订单和日期；推送后 fetch/ls-remote 验证远端提交。推送失败如实说明，本地记录不等于远端已保存。
- 不提交账号、账户ID、凭据、token、完整原始接口日志；仓库可被匿名读取，持仓及账户汇总会随提交发布。GitHub Actions扫描本身不能读取IBKR，也不自动更新实盘记录。

## 可直接复制到新GPT会话

请读取 https://github.com/Marla62/triple-screen-scan 的 main 分支 portfolio/README.md、portfolio/rules.json、portfolio/latest.json、portfolio/REPORT_TEMPLATE.md，再核对 output/latest.json 与 output/status.json。按最新账户记录生成中文美股日报。旧快照不是实时账户；有IBKR时重新查询，没权限时让我补充。不要把模拟仓或上次建议当成交。若你有仓库写权限，按已授权流程更新快照、报告和成交并提交推送；没有写权限则交付待保存文件并明确说明未推送。不下单。

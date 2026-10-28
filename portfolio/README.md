# 真实持仓记录与手动日报入口

本目录用于跨会话保留实盘快照，不是扫描器模拟仓，不执行交易。

2026-10-26用户指定：以后将交易记录和入场策略保存到本地代码仓库 `/Users/jiangchenxiang/zp/jcx/triple-screen-scan/portfolio/`。本地台账为主入口，默认保存到工作区；只有用户明确要求提交或推送时才执行。此前2026-10-23的公开发布授权不作为当前自动提交推送的依据。禁止写入账号、凭据或密钥。

## 新会话先读

1. `portfolio/rules.json`：用户已确认预算与退出规则。
   同时读 `portfolio/STRATEGY_PLAN.md`：2026-10-28 起的研究、试行及资金部署门槛。当前主动新仓处于研究阶段，不能因扫描出现候选就建议实盘开仓；老仓继续按原规则管理，长期资金另行复核。
2. `portfolio/trade-plans.json`：逐笔开仓理由、策略确认、入场参数、退出条件及期限；建议与成交分开，缺失理由明确保留未知。
3. `portfolio/latest.json`：最后一次 IBKR 实盘查询及观测时间，不代表当前实时状态。
4. `portfolio/trades.jsonl`：已查证成交；当前起始导入为2026-10-23查询的近30天记录，并非完整账户历史。
5. `portfolio/snapshots/YYYY-MM-DD.json` 和 `portfolio/reports/YYYY-MM-DD.md`：历史快照、报告。
6. `portfolio/REPORT_TEMPLATE.md`：日报格式与更新流程。
7. **仅从 GitHub main 直接读取** `config.json`、`output/latest.json`、`output/latest.md`、`output/status.json`；必要时读取远端实验室。禁止读取本地扫描文件或回退备份。

用户手动运行 GitHub Actions 后，手动要求助手生成日报。已取消本机 launchd 扫描和 Codex 定时日报；不要自行恢复。GitHub 自带定时扫描仍保留，手动入口不变。

## 每次生成报告必须执行

- 先检查本地工作区并读取本地规则、策略台账；保留未提交改动，远端旧记录不得覆盖较新的用户确认。扫描数据必须直接读取 GitHub main，不自动拉取合并或提交推送。2026-10-27用户指定：扫描数据唯一来源为 GitHub 仓库 https://github.com/Marla62/triple-screen-scan 的 main 分支。每次直接读取远端 config.json、output/latest.json、output/latest.md、output/status.json；策略评估按需读取远端 output/lab.json 或 output/lab.md。禁止读取本地 output/、历史备份或旧缓存作为扫描数据，禁止在远端失败时回退本地。远端读取失败须报告“GitHub扫描数据不可用”，不使用旧信号给出新仓建议；远端可读但过期时标明日期且不作为当日信号。本地 portfolio/ 实盘台账继续保留，账户、持仓及订单仍从 IBKR 核实。不得恢复本机扫描任务。
- 刷新 IBKR 摘要、分币种现金、持仓、订单、必要成交及收益。失败时保留旧快照观测日期，单独记本次查询失败；不得把旧数据改成今天成功。
- 用户更新优先于旧文档。没有明确成交证据，不把建议或扫描 `sim_holdings` / `open_trade` 当持仓；没有归属证据，不追认策略。
- 先检查 `rules.json.strategy_development.active_entry_stage`。研究阶段只给主动观察名单及验证缺口；通过复核并明确进入试行后才提出主动新仓。试行每笔0.25%、最多2笔，后续上限0.5%；有效入场挂单也占风险，同主题主动风险合计不超过0.5%。这些限制由日报核查，扫描示例不自动执行。
- 核对最近完成的美股交易日、扫描 as_of、generated_at、缺失和错误。fresh 不等于全池完整。过期信号不给当日入场建议。
- 按模板生成中文报告；用代码计算资金/股数/止损，按资金、单票、分区、风险、合计风险的最严格约束向下取整，合并同票和主题敞口，不融资。
- 更新 latest.json、当日快照和当日报告；以后每次只增补成交，以 executed_at/symbol/side/quantity/price/commission 去重，保留历史。快照同日重查可覆盖当日版本，Git保留修改历史；其他日期不伪造补写。
- 每次提出开仓建议、核实新成交或收到用户策略确认时，更新 trade-plans.json，记录理由、信号及来源、分区/策略、入场与跳过条件、原始ATR、止损、其他退出规则、最晚退出日和计数口径、订单与财报安排。未知字段不补造，后补解释注明日期，变更追加history，已清仓记录保留复盘。成交只追加到trades.jsonl并去重，未成交建议不得写入成交记录。
- 默认仅本地保存。用户明确要求时才提交或推送相关记录，不夹带其他改动，不改扫描产物或策略代码。
- git diff --check；解析 JSON/JSONL，核对仓位、规则、订单和日期；如获授权推送，完成后用 fetch/ls-remote 验证远端提交。未推送或失败须明说。
- 不提交账号、账户ID、凭据、token、完整原始接口日志；仓库可被匿名读取，持仓及账户汇总会随提交发布。GitHub Actions扫描本身不能读取IBKR，也不自动更新实盘记录。

## 可直接复制到新GPT会话

请先读取本地 /Users/jiangchenxiang/zp/jcx/triple-screen-scan/portfolio/ 的 README.md、rules.json、trade-plans.json、latest.json、trades.jsonl 和 REPORT_TEMPLATE.md，再核对最新扫描及IBKR实盘。以最新用户确认为准，每票先复述已记录的开仓理由和退出条件，缺失信息标未知。更新本地台账、快照和日报，不把模拟仓或未成交建议当真实交易，不下单；未经明确要求不提交或推送。扫描只读 GitHub main，读取失败不回退本地、备份或旧缓存；扫描不可用时不提供新信号建议。远端扫描不能覆盖较新的本地策略记录。

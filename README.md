# 每日选股扫描器 + 策略实验室

每个交易日美股收盘后，用 GitHub Actions 自动扫描 **S&P 500 + 纳斯达克 100**，
按 `config.json` 里选定的策略找出候选，对每只股票回测，输出到 `output/` 目录。
另有一个“策略实验室”（`--lab`），把所有内置策略放在同一股票池、同一时间段、同一套资金规则下并排比较。

## 内置策略（`config.json` 的 `strategy` 字段）

| 名称 | 入场 | 出场 |
|---|---|---|
| `triple_screen` | 周线 26 周 EMA 向上且 Impulse 不为红；日线 2 日 Force Index < 0 且 Impulse 不为红；买入止损单挂前一日高点 + 0.01 | 移动止损 = 建仓后最高价 − 2×ATR(14) |
| `ts_target` | 同上 | 1×ATR 止盈 / 2×ATR 固定止损 |
| `rsi2` / `rsi2_strict` | 收盘 > 200 日均线 且 RSI(2) < 10（/ < 5），次日开盘买入 | 收盘 > 5 日均线次日开盘卖出；3×ATR 保护止损；最多 10 天 |
| `bb_revert` | 收盘 > 200 日均线 且 收盘 < 布林下轨(20,2)，次日开盘买入 | 收盘 ≥ 20 日均线次日开盘卖出；3×ATR 保护止损；最多 15 天 |
| `triple_screen_rf` / `rsi2_rf` / `bb_revert_rf` | 同名策略 + **大盘过滤器**：只在 SPY 收盘 > 200 日均线时接受新信号 | 同名策略 |
| `mom_12_1` | **12-1 截面动量（月度）**：月末按过去 12 个月、剔除最近 1 个月的收益选正动量前 10；次日开盘给新入选股分配现金，已有仓不重新等权；月末有效 SPY 过滤不通过时转现金 | 掉出前 10 的次月初开盘卖出；不设止损；缺报价不虚构成交 |
| `mom_12_1_nf` | 同上，不带大盘过滤 | 同上 |

- 每日模式只生成研究观察清单。信号类策略示例按每笔0.5%计划风险、单票10%、现金与预计费用约束向下取整；动量按资金分配，不虚构ATR止损。报告按每 $10,000 给出，示例股数不代表实盘建议，组合风险还要核对已有仓位和挂单。
- 每日模式的排序：信号类策略按信号生成时已知的信号强度，与组合模拟一致；动量策略按动量值。单票历史修正胜率仅作诊断。
  单票回测只有几笔到十几笔，**排序只能当参考**，判断策略好坏请看实验室的组合级结果。
- 大盘状态（SPY 收盘 / 200 日均线 / 是否在均线上）每天写入 `latest.json` 的 `market` 字段，不带过滤器的策略也能看到。

## 策略实验室（`python scan.py --lab`，或 Actions → strategy-lab → Run workflow）

`output/lab.md` 第一张表是**组合级资金曲线**：每个策略用同一套资金规则模拟一个 $10,000 账户——

- 信号类策略：每笔计划风险最多0.5%、单票市值最多10%、合计原始计划风险最多2%，整股定仓并计入预计费用；不用融资，取消原“最低买到净值5%”门槛。同时最多10只；同日按信号强度择优，未触发或无法买入一股时跳过。持仓按初始风险保守占用额度；日线无法确定的盘中卖出现金／仓位不用于同日新买单。
- 动量策略：月末选前10只，仅给新入选股分配现金并受单票上限约束，已有仓不重新等权；无开盘报价的待退出仓位继续占用资金，等真实有效开盘报价再退出，不用收盘价虚构卖出，也不自动追买错过的新入选股。大盘未知时禁止新增，旧仓仍按可确认排名管理；有效大盘过滤明确失败时才按策略转现金。
- 指标：年化收益、最大回撤、Sharpe、Calmar、终值、实际成交笔数、平均持仓数、平均敞口、分年收益；并与 **SPY 买入持有** 对照。

第二张表才是原来的单笔统计（每个信号都成交、不受资金限制的口径）。`output/lab_equity.csv` 是各策略月末资金曲线，可直接画图。

研究模拟不是完整实盘组合：没有自动约束实际长期／中期／短期预算、主题集中度、财报或IBKR佣金阶梯。月度动量没有ATR止损，其潜在亏损不受信号策略2%计划风险上限覆盖。修改仓位和成交规则后必须重新产生远端结果，不能沿用旧绩效。当前没有独立样本外验证；候选方向和晋级门槛见 [交易方法与验证计划](portfolio/STRATEGY_PLAN.md)。

## 输出文件

- `output/latest.md` —— 当日候选表（GitHub 上直接可读）
- `output/latest.csv` / `output/latest.json` —— 同样内容，供程序读取（`market` = 大盘状态；动量策略另有 `next_rebalance`、`sim_holdings`、`portfolio`）
- `output/history/YYYY-MM-DD.json` —— 每日存档
- `output/status.json` —— 运行诊断（缺数据的股票、报错等）
- `output/lab.md` / `lab.json` / `lab_equity.csv` —— 策略实验室结果

## 安装（约 5 分钟，只做一次）

1. **建仓库**：登录 GitHub → 右上角 “+” → New repository → 名字随意（如 `triple-screen-scan`），
   选 **Public**（我这边的每日任务需要匿名读取结果），其它都不勾 → Create repository。
2. **上传文件**：在新仓库页面点 **Add file → Upload files**，把解压后的全部内容
   （`scan.py`、`requirements.txt`、`README.md`、`.gitignore` 和整个 `.github` 文件夹）拖进去 → Commit changes。
   - 如果拖拽时 `.github` 文件夹没上传成功，就点 **Add file → Create new file**，
     文件名输入 `.github/workflows/scan.yml`（会自动建目录），把 `scan.yml` 的内容粘贴进去后 Commit。
3. **给工作流写权限**：仓库 **Settings → Actions → General → Workflow permissions**，
   选 **Read and write permissions** → Save。
4. **手动跑第一次**：仓库顶部 **Actions** 标签 → 左侧 `triple-screen-scan` →
   右侧 **Run workflow → Run workflow**。等 3~8 分钟，刷新仓库首页，会看到 `output/latest.md`。
5. 把仓库地址（形如 `https://github.com/你的用户名/triple-screen-scan`）发给 Claude，每日推送就接上了。

之后每个交易日 21:30 UTC（北京时间 05:30，GitHub 可能延迟 10~40 分钟）自动运行、自动提交结果。

## 日报扫描数据来源

2026-10-27用户指定：扫描数据唯一来源为 GitHub 仓库 https://github.com/Marla62/triple-screen-scan 的 main 分支。每次直接读取远端 config.json、output/latest.json、output/latest.md、output/status.json；策略评估按需读取远端 output/lab.json 或 output/lab.md。禁止读取本地 output/、历史备份或旧缓存作为扫描数据，禁止在远端失败时回退本地。远端读取失败须报告“GitHub扫描数据不可用”，不使用旧信号给出新仓建议；远端可读但过期时标明日期且不作为当日信号。本地 portfolio/ 实盘台账继续保留，账户、持仓及订单仍从 IBKR 核实。不得恢复本机扫描任务。

本地旧 output/ 已移出仓库，仅保留恢复备份；不要将本地文件移除提交或推送到 GitHub。GitHub Actions 继续在远端生成并保存 output/。

## 注意

- 回测采用0.05%往返比例成本的简化情景，按实际发生的买入／卖出端扣费；未平仓只估值。它不是已充分覆盖小额IBKR佣金和滑点的证明，启用实盘前另核真实费用和翻倍成本压力。跳空穿越止损按开盘价成交；买入止损入场当日的高低先后不明，触及初始止损保守计亏损。
- 单票胜率来自每只股票自身约 3 年的历史回测，笔数少时噪音很大；判断策略优劣请看 `lab.md` 的组合级结果，且 3 年窗口只覆盖一轮牛市，对趋势/动量类策略偏乐观。
- 组合模拟里“同日信号择优”和“现金不足跳过”会让结果依赖于具体路径，换一批股票或换起点数字会变；把它当量级参考，不要当精确预测。
- 数据来自 Yahoo Finance（yfinance），偶尔会缺票或延迟，`status.json` 里会列出；SPY缺失或对应日期缺数据时，带过滤策略禁止新入场，不用等权代理冒充SPY。待触发信号在已完成日的过滤条件失效后取消，已有仓位退出规则不变。
- 股票池仅有当前成分股及加入日期过滤，未包含完整历史剔除／退市公司，仍存在幸存者偏差；日扫描和实验室的股票池范围也不同。日线无法还原所有盘中订单触发顺序，研究结果不等于逐笔可成交证明。
- 若把 `config.json` 切到 `mom_12_1`，每日报告的字段含义会变（`entry_mode = "monthly"`，无止损），读报告的一方需要相应调整。

## 真实持仓与手动日报

新会话读取 [portfolio/README.md](portfolio/README.md)，持仓快照在 [portfolio/latest.json](portfolio/latest.json)，模板在 [portfolio/REPORT_TEMPLATE.md](portfolio/REPORT_TEMPLATE.md)。这些是独立实盘记录，和 output 中的回测/模拟仓分开。用户手动运行Actions后要求日报时，助手刷新并保存本地实盘台账，未经明确要求不提交或推送；扫描始终只读 GitHub，已取消本机扫描及Codex定时日报。

## 本地实现验证

安装已有 requirements.txt 依赖后运行 `python -m unittest discover -s tests -v`。测试仅使用内存合成行情及临时目录，验证触价、退出、资金时序、风险上限和输出契约；不下载行情、不运行实际扫描，不证明策略收益。本地禁止生成真实扫描产物，实际策略研究仍只在GitHub运行。

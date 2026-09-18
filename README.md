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
| `mom_12_1` | **12-1 截面动量（月度）**：每月最后一个交易日按“过去 12 个月收益、剔除最近 1 个月”排名，取动量 > 0 的前 10 只，次日开盘等权买入；SPY < 200 日均线时清仓持现金 | 掉出前 10 的次月初开盘卖出；不设止损 |
| `mom_12_1_nf` | 同上，不带大盘过滤 | 同上 |

- 每日模式的仓位：信号类策略按 2% 原则（股数 = 2%×资金 ÷ (止损倍数×ATR)），动量策略等权（资金 ÷ 10）；报告按每 $10,000 给出。
- 每日模式的排序：信号类策略按“修正胜率”（每只股票自身回测胜率的 Wilson 95% 下界，小样本自动向下修正）；动量策略按动量值。
  单票回测只有几笔到十几笔，**排序只能当参考**，判断策略好坏请看实验室的组合级结果。
- 大盘状态（SPY 收盘 / 200 日均线 / 是否在均线上）每天写入 `latest.json` 的 `market` 字段，不带过滤器的策略也能看到。

## 策略实验室（`python scan.py --lab`，或 Actions → strategy-lab → Run workflow）

`output/lab.md` 第一张表是**组合级资金曲线**：每个策略用同一套资金规则模拟一个 $10,000 账户——

- 信号类策略：每笔风险 = 2% × 当前净值，仓位金额 = 风险 ÷ 每股风险；不用融资（现金不够就缩仓，仓位小于净值 5% 就跳过）；同时最多 10 只；同一天信号过多时按“信号强度”择优（均值回归取偏离越深越优先）。
- 动量策略：等权持有前 10 只，月末调仓。
- 指标：年化收益、最大回撤、Sharpe、Calmar、终值、实际成交笔数、平均持仓数、平均敞口、分年收益；并与 **SPY 买入持有** 对照。

第二张表才是原来的单笔统计（每个信号都成交、不受资金限制的口径）。`output/lab_equity.csv` 是各策略月末资金曲线，可直接画图。

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

## 本地运行（可选）

```bash
pip install -r requirements.txt
python scan.py                          # 全股票池，config.json 里的策略
python scan.py --strategy mom_12_1      # 临时换一个策略
python scan.py --limit 30               # 只跑前 30 只，测试用
python scan.py --lab                    # 策略实验室
python scan.py --lab --sample ./csvdir  # 用本地 CSV（每只一个文件，含 SPY.csv 则用它做大盘）
```

## 注意

- 回测每笔扣 0.05% 往返成本；跳空穿越止损按开盘价成交；入场当天若最低价触及初始止损，按当天止损出局处理。
- 单票胜率来自每只股票自身约 3 年的历史回测，笔数少时噪音很大；判断策略优劣请看 `lab.md` 的组合级结果，且 3 年窗口只覆盖一轮牛市，对趋势/动量类策略偏乐观。
- 组合模拟里“同日信号择优”和“现金不足跳过”会让结果依赖于具体路径，换一批股票或换起点数字会变；把它当量级参考，不要当精确预测。
- 数据来自 Yahoo Finance（yfinance），偶尔会缺票或延迟，`status.json` 里会列出；SPY 拿不到时大盘过滤器改用股票池等权代理指数。
- 若把 `config.json` 切到 `mom_12_1`，每日报告的字段含义会变（`entry_mode = "monthly"`，无止损），读报告的一方需要相应调整。

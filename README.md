# 三重滤网每日选股扫描器

每个交易日美股收盘后，用 GitHub Actions 自动扫描 **S&P 500 + 纳斯达克 100**，
按《以交易为生》的三重滤网找出可买候选，并用 **2×ATR 移动止损** 对每只股票回测得到胜率，
按胜率排序输出到 `output/` 目录。

## 规则

| 环节 | 规则 |
|---|---|
| 第一重（周线） | 26 周 EMA 向上，且周线 Impulse 不为红（EMA13 与 MACD 柱不同时下降） |
| 第二重（日线） | 2 日 Force Index < 0（上升趋势中的回调），且日线 Impulse 不为红 |
| 第三重（入场） | 买入止损单挂在前一日最高价上方 0.01；未触发则每天下移到最新高点上方，周线趋势转弱撤单 |
| 出场 | 移动止损 = 建仓后盘中最高价 − 2×ATR(14)，只升不降（ATR 取入场时的值） |
| 仓位 | 2% 原则：股数 = 2%×资金 ÷ (2×ATR)；报告按每 $10,000 资金给出 |
| 排序 | 纯胜率降序；回测笔数 < 8 视为样本不足，排在后面 |

## 输出文件

- `output/latest.md` —— 当日候选表（GitHub 上直接可读）
- `output/latest.csv` / `output/latest.json` —— 同样内容，供程序读取
- `output/history/YYYY-MM-DD.json` —— 每日存档
- `output/status.json` —— 运行诊断（缺数据的股票、报错等）

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
python scan.py            # 全股票池
python scan.py --limit 30 # 只跑前 30 只，测试用
```

## 注意

- 胜率来自每只股票自身约 3 年的历史回测，笔数少时噪音很大；`latest.md` 顶部的“全池回测”是同一规则在整个股票池上的整体表现，可用来判断单票胜率是否只是运气。
- 回测不含手续费与滑点；跳空穿越止损按开盘价成交；入场当天若最低价触及初始止损，按当天止损出局处理。
- 数据来自 Yahoo Finance（yfinance），偶尔会缺票或延迟，`status.json` 里会列出。

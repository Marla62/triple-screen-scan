#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三重滤网（Elder Triple Screen）每日选股扫描器
================================================
股票池：S&P 500 + 纳斯达克 100
规则（参考《以交易为生》第 2 版）：
  第一重（周线，趋势）：26 周 EMA 向上，且周线 Impulse 不为红（EMA13 与 MACD 柱不同时下降）
  第二重（日线，回调）：2 日 Force Index < 0，且日线 Impulse 不为红
  第三重（入场）：买入止损单挂在前一日最高价上方 1 tick（0.01）
出场（jj 的规则）：移动止损 = 建仓后盘中最高价 − 2×ATR(14)，只升不降；ATR 取入场时的值
排序：按每只股票在自身历史上用同样规则回测得到的胜率（纯胜率）排序，样本不足的排后

输出（output/ 目录）：
  latest.json / latest.csv / latest.md   当日候选（含回测统计与仓位参考）
  history/YYYY-MM-DD.json                历史存档
  status.json                            运行诊断（数据缺失、异常等）
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import sys
import time
import traceback
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------
# 配置
# ----------------------------------------------------------------------------
ATR_N = 14                 # ATR 周期
ATR_MULT = 2.0             # 移动止损 = 最高价 − ATR_MULT × ATR
TICK = 0.01                # 买入止损单挂在前高上方 1 tick
LOOKBACK_YEARS = 4         # 下载年数（前 ~9 个月用于指标预热，不计入回测）
WARMUP_WEEKS = 35          # 周线指标预热周数（26 周 EMA 需要）
MIN_TRADES = 8             # 少于此笔数的胜率视为“样本不足”
RISK_PCT = 0.02            # 2% 原则
SIZE_BASIS = 10_000        # 报告里“每 1 万美元资金可买股数”的基数
OUT_DIR = Path("output")
SP500_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
NDX_WIKI_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"

# 纳斯达克 100 兜底名单（Wikipedia 拉不到时使用；成分会随再平衡漂移，仅作兜底）
NDX_FALLBACK = """
AAPL MSFT NVDA AMZN META AVGO GOOGL GOOG TSLA COST NFLX TMUS ASML CSCO PLTR AZN LIN ISRG INTU AMD
PEP ADBE BKNG TXN QCOM AMGN MU ARM HON GILD PANW AMAT SHOP CMCSA ADP APP LRCX VRTX MELI KLAC
CRWD ADI SBUX INTC CEG MSTR CTAS DASH CDNS ORLY MDLZ SNPS MAR FTNT PDD ABNB MRVL REGN ADSK MNST
CSX WDAY AEP PYPL ROP CHTR PCAR AXON NXPI PAYX ROST CPRT FAST EXC KDP DDOG TTWO IDXX CCEP FANG
BKR VRSK XEL EA ZS CTSH LULU ODFL TEAM KHC GEHC CSGP DXCM ON TTD WBD BIIB GFS MDB CDW
""".split()


# ----------------------------------------------------------------------------
# 股票池
# ----------------------------------------------------------------------------
def load_universe(status: dict) -> pd.DataFrame:
    """返回 DataFrame[ticker, name, sector, index]，index ∈ {SPX, NDX, SPX+NDX}"""
    import requests

    rows = {}
    # S&P 500
    try:
        r = requests.get(SP500_URL, timeout=30)
        r.raise_for_status()
        sp = pd.read_csv(io.StringIO(r.text))
        sym_col = "Symbol" if "Symbol" in sp.columns else sp.columns[0]
        name_col = "Security" if "Security" in sp.columns else ("Name" if "Name" in sp.columns else sp.columns[1])
        sec_col = "GICS Sector" if "GICS Sector" in sp.columns else ("Sector" if "Sector" in sp.columns else None)
        for _, x in sp.iterrows():
            t = str(x[sym_col]).strip().upper()
            rows[t] = {"ticker": t, "name": str(x[name_col]), "sector": str(x[sec_col]) if sec_col else "", "index": "SPX"}
        status["sp500_count"] = len(sp)
    except Exception as e:  # noqa
        status["errors"].append(f"S&P 500 名单获取失败: {e!r}")

    # Nasdaq-100
    ndx = []
    try:
        r = requests.get(NDX_WIKI_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0 (triple-screen-scan)"})
        r.raise_for_status()
        tables = pd.read_html(io.StringIO(r.text))
        for tb in tables:
            cols = [str(c) for c in tb.columns]
            tcol = next((c for c in cols if c.lower() in ("ticker", "symbol", "ticker symbol")), None)
            if tcol and len(tb) >= 80:
                ncol = next((c for c in cols if c.lower() in ("company", "security", "name")), None)
                scol = next((c for c in cols if "sector" in c.lower()), None)
                for _, x in tb.iterrows():
                    t = str(x[tcol]).strip().upper()
                    ndx.append((t, str(x[ncol]) if ncol else t, str(x[scol]) if scol else ""))
                break
        if not ndx:
            raise RuntimeError("Wikipedia 页面里没找到成分表")
        status["ndx_source"] = "wikipedia"
    except Exception as e:  # noqa
        status["errors"].append(f"纳斯达克 100 名单获取失败，使用兜底名单: {e!r}")
        ndx = [(t, t, "") for t in NDX_FALLBACK]
        status["ndx_source"] = "fallback"
    status["ndx_count"] = len(ndx)

    for t, n, s in ndx:
        if t in rows:
            rows[t]["index"] = "SPX+NDX"
        else:
            rows[t] = {"ticker": t, "name": n, "sector": s, "index": "NDX"}

    uni = pd.DataFrame(list(rows.values())).sort_values("ticker").reset_index(drop=True)
    status["universe_size"] = len(uni)
    return uni


def to_yahoo_symbol(t: str) -> str:
    return t.replace(".", "-")


# ----------------------------------------------------------------------------
# 行情下载（yfinance 主，stooq 兜底）
# ----------------------------------------------------------------------------
def _clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame | None:
    if df is None or len(df) == 0:
        return None
    df = df.rename(columns=lambda c: str(c).strip().title())
    need = ["Open", "High", "Low", "Close", "Volume"]
    if not all(c in df.columns for c in need):
        return None
    df = df[need].copy()
    df.index = pd.to_datetime(df.index)
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df["Volume"] = df["Volume"].fillna(0)
    if len(df) < 60:
        return None
    return df


def fetch_yfinance(tickers: list[str], status: dict, batch: int = 60, pause: float = 1.5) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    out: dict[str, pd.DataFrame] = {}
    start = (datetime.now(timezone.utc) - timedelta(days=int(365.25 * LOOKBACK_YEARS))).strftime("%Y-%m-%d")
    sym_map = {to_yahoo_symbol(t): t for t in tickers}
    syms = list(sym_map)
    for i in range(0, len(syms), batch):
        chunk = syms[i:i + batch]
        for attempt in range(3):
            try:
                raw = yf.download(chunk, start=start, interval="1d", auto_adjust=False,
                                  group_by="ticker", threads=True, progress=False, timeout=30)
                break
            except Exception as e:  # noqa
                status["errors"].append(f"yfinance 批次 {i // batch} 第 {attempt + 1} 次失败: {e!r}")
                time.sleep(10 * (attempt + 1))
                raw = None
        if raw is None or len(raw) == 0:
            continue
        if isinstance(raw.columns, pd.MultiIndex):
            lvl0 = raw.columns.get_level_values(0)
            for s in chunk:
                if s in lvl0:
                    d = _clean_ohlcv(raw[s])
                    if d is not None:
                        out[sym_map[s]] = d
        else:  # 单票时可能是平铺列
            if len(chunk) == 1:
                d = _clean_ohlcv(raw)
                if d is not None:
                    out[sym_map[chunk[0]]] = d
        time.sleep(pause)
    return out


def fetch_stooq(tickers: list[str], status: dict, max_n: int = 150) -> dict[str, pd.DataFrame]:
    """stooq 兜底：逐票 CSV。有每日次数限制，只补少量缺口。"""
    import requests

    out = {}
    d1 = (datetime.now(timezone.utc) - timedelta(days=int(365.25 * LOOKBACK_YEARS))).strftime("%Y%m%d")
    for t in tickers[:max_n]:
        url = f"https://stooq.com/q/d/l/?s={t.lower().replace('-', '.')}.us&i=d&d1={d1}"
        try:
            r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200 or "Date" not in r.text[:50]:
                continue
            df = pd.read_csv(io.StringIO(r.text), parse_dates=["Date"]).set_index("Date")
            d = _clean_ohlcv(df)
            if d is not None:
                out[t] = d
        except Exception as e:  # noqa
            status["errors"].append(f"stooq {t}: {e!r}")
        time.sleep(0.3)
    return out


# ----------------------------------------------------------------------------
# 指标
# ----------------------------------------------------------------------------
def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int = ATR_N) -> pd.Series:
    hl = df["High"] - df["Low"]
    hc = (df["High"] - df["Close"].shift(1)).abs()
    lc = (df["Low"] - df["Close"].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()  # Wilder 平滑


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """在日线 DataFrame 上加：ATR、日线 EMA13/MACD 柱/Force Index、以及“当天看到的周线”指标。"""
    d = df.copy()
    c = d["Close"]
    d["atr"] = atr(d)
    d["ema13"] = ema(c, 13)
    macd = ema(c, 12) - ema(c, 26)
    d["hist"] = macd - ema(macd, 9)
    d["fi2"] = ema((c - c.shift(1)) * d["Volume"], 2)
    d["d_red"] = (d["ema13"] < d["ema13"].shift(1)) & (d["hist"] < d["hist"].shift(1))

    # ---- 周线：已收周 K 计算 EMA，再用本周（未收）的最新收盘做部分更新，等价于图表上看到的本周周线 ----
    w = d.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    w = w.dropna(subset=["Close"])
    wc = w["Close"]
    w_e26, w_e13, w_e12 = ema(wc, 26), ema(wc, 13), ema(wc, 12)
    w_macd = w_e12 - w_e26
    w_sig = ema(w_macd, 9)
    w_hist = w_macd - w_sig

    days_to_fri = (4 - d.index.weekday) % 7
    week_end = d.index + pd.to_timedelta(days_to_fri, unit="D")
    prev_pos = np.searchsorted(w.index.values, week_end.values, side="left") - 1  # 本周之前最后一根已收周 K
    valid = prev_pos >= WARMUP_WEEKS
    pp = np.clip(prev_pos, 0, len(w) - 1)

    def take(s: pd.Series) -> np.ndarray:
        arr = s.values[pp].astype(float)
        arr[~valid] = np.nan
        return arr

    E26p, E13p, E12p, SIGp, HISTp = take(w_e26), take(w_e13), take(w_e12), take(w_sig), take(w_hist)
    a26, a13, a12, a9 = 2 / 27, 2 / 14, 2 / 13, 2 / 10
    cv = c.values.astype(float)
    e26 = a26 * cv + (1 - a26) * E26p
    e13 = a13 * cv + (1 - a13) * E13p
    e12 = a12 * cv + (1 - a12) * E12p
    m = e12 - e26
    sig = a9 * m + (1 - a9) * SIGp
    hist = m - sig
    d["w_valid"] = valid
    d["w_ema26_up"] = e26 > E26p
    d["w_hist_up"] = hist > HISTp
    d["w_red"] = (e13 < E13p) & (hist < HISTp)

    d["screen1"] = d["w_valid"] & d["w_ema26_up"] & ~d["w_red"]
    d["screen2"] = (d["fi2"] < 0) & ~d["d_red"]
    d["signal"] = d["screen1"] & d["screen2"] & d["atr"].notna()
    return d


# ----------------------------------------------------------------------------
# 回测：同一套信号 + 2×ATR 移动止损，得到每只股票自身的胜率
# ----------------------------------------------------------------------------
@dataclass
class Trade:
    entry_date: str
    exit_date: str
    entry: float
    exit: float
    ret: float
    days: int


def backtest(d: pd.DataFrame) -> tuple[list[Trade], dict]:
    O, H, L = d["Open"].values, d["High"].values, d["Low"].values
    A, S, W = d["atr"].values, d["signal"].values, d["screen1"].values
    idx = d.index
    n = len(d)
    first = int(np.argmax(d["w_valid"].values)) if d["w_valid"].any() else n
    trades: list[Trade] = []
    state = "flat"
    trigger = math.nan
    pending_since = -1
    entry = atr_e = hh = stop = math.nan
    entry_i = -1

    for i in range(max(first, 1), n):
        o, h, l = O[i], H[i], L[i]
        if state == "long":
            if l <= stop:
                px = stop if o >= stop else o  # 跳空低开在止损之下，按开盘价成交
                trades.append(Trade(str(idx[entry_i].date()), str(idx[i].date()), float(entry), float(px),
                                    float(px / entry - 1), i - entry_i))
                state = "flat"
            else:
                hh = max(hh, h)
                stop = max(stop, hh - ATR_MULT * atr_e)
        elif state == "pending":
            if h > trigger:
                px = o if o > trigger else trigger  # 跳空高开高于触发价，按开盘价成交
                entry, entry_i, atr_e = px, i, A[i - 1]
                if not np.isfinite(atr_e) or atr_e <= 0:
                    state = "flat"
                else:
                    stop0 = entry - ATR_MULT * atr_e
                    hh = h
                    if l <= stop0:  # 入场当天就打到初始止损（保守处理为当天止损出局）
                        trades.append(Trade(str(idx[i].date()), str(idx[i].date()), float(entry), float(stop0),
                                            float(stop0 / entry - 1), 0))
                        state = "flat"
                    else:
                        stop = max(stop0, hh - ATR_MULT * atr_e)
                        state = "long"
            else:
                if W[i]:
                    trigger = min(trigger, h + TICK)  # 未触发：把买入止损下移到最新一根 K 线的高点上方
                else:
                    state = "flat"  # 周线趋势不再向上，撤单
        if state == "flat" and S[i]:
            state, trigger, pending_since = "pending", h + TICK, i

    last = {
        "state": state,
        "trigger": float(trigger) if state == "pending" else None,
        "pending_since": str(idx[pending_since].date()) if state == "pending" and pending_since >= 0 else None,
        "sim_entry": float(entry) if state == "long" else None,
        "sim_entry_date": str(idx[entry_i].date()) if state == "long" else None,
        "sim_stop": float(stop) if state == "long" else None,
    }
    return trades, last


def stats(trades: list[Trade]) -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0, "wins": 0, "win_rate": None, "avg_win": None, "avg_loss": None,
                "payoff": None, "expectancy": None, "profit_factor": None, "avg_days": None}
    r = np.array([t.ret for t in trades])
    wins, losses = r[r > 0], r[r <= 0]
    aw = float(wins.mean()) if len(wins) else 0.0
    al = float(losses.mean()) if len(losses) else 0.0
    return {
        "trades": n,
        "wins": int(len(wins)),
        "win_rate": float(len(wins) / n),
        "avg_win": aw,
        "avg_loss": al,
        "payoff": float(aw / abs(al)) if al < 0 else None,
        "expectancy": float(r.mean()),
        "profit_factor": float(wins.sum() / abs(losses.sum())) if losses.sum() < 0 else None,
        "avg_days": float(np.mean([t.days for t in trades])),
    }


# ----------------------------------------------------------------------------
# 单票处理
# ----------------------------------------------------------------------------
def analyze(ticker: str, meta: dict, df: pd.DataFrame) -> dict | None:
    d = add_indicators(df)
    if not d["w_valid"].any():
        return None
    trades, last = backtest(d)
    st = stats(trades)
    row = d.iloc[-1]
    as_of = str(d.index[-1].date())
    a = float(row["atr"])
    is_signal = bool(row["signal"])
    is_pending = last["state"] == "pending"
    candidate = is_signal or is_pending
    trigger = float(row["High"]) + TICK if candidate else None
    stop0 = trigger - ATR_MULT * a if candidate else None
    risk_ps = ATR_MULT * a
    shares = int(math.floor(RISK_PCT * SIZE_BASIS / risk_ps)) if risk_ps > 0 else None
    return {
        "ticker": ticker,
        "name": meta.get("name", ticker),
        "sector": meta.get("sector", ""),
        "index": meta.get("index", ""),
        "as_of": as_of,
        "close": round(float(row["Close"]), 2),
        "high": round(float(row["High"]), 2),
        "atr14": round(a, 3),
        "atr_pct": round(a / float(row["Close"]) * 100, 2),
        "candidate": candidate,
        "status": "新信号" if is_signal else ("挂单延续" if is_pending else ""),
        "signal_date": as_of if is_signal else last.get("pending_since"),
        "buy_stop": round(trigger, 2) if trigger else None,
        "initial_stop": round(stop0, 2) if stop0 else None,
        "risk_per_share": round(risk_ps, 3),
        "shares_per_10k": shares,
        "fi2": round(float(row["fi2"]), 0),
        "w_ema26_up": bool(row["w_ema26_up"]),
        "w_hist_up": bool(row["w_hist_up"]),
        "d_red": bool(row["d_red"]),
        "screen1": bool(row["screen1"]),
        "screen2": bool(row["screen2"]),
        "sim_state": last["state"],
        "sim_entry": last["sim_entry"],
        "sim_entry_date": last["sim_entry_date"],
        "sim_stop": round(last["sim_stop"], 2) if last["sim_stop"] else None,
        "bt_from": trades[0].entry_date if trades else None,
        **{f"bt_{k}": v for k, v in st.items()},
        "_trades": [asdict(t) for t in trades],
    }


def rank_key(r: dict):
    enough = 1 if (r["bt_trades"] or 0) >= MIN_TRADES else 0
    return (-enough, -(r["bt_win_rate"] or 0), -(r["bt_payoff"] or 0), -(r["bt_trades"] or 0))


# ----------------------------------------------------------------------------
# 输出
# ----------------------------------------------------------------------------
CSV_COLS = ["rank", "ticker", "name", "sector", "index", "status", "signal_date", "close", "high", "atr14", "atr_pct",
            "buy_stop", "initial_stop", "risk_per_share", "shares_per_10k",
            "bt_win_rate", "bt_trades", "bt_wins", "bt_payoff", "bt_expectancy", "bt_profit_factor", "bt_avg_days",
            "w_hist_up", "fi2"]


def fmt_pct(x, nd=1):
    return "" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 100:.{nd}f}%"


def fmt(x, nd=2):
    return "" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def write_outputs(cands: list[dict], all_rows: list[dict], status: dict, as_of: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "history").mkdir(exist_ok=True)

    # 全股票池系统级统计（用来判断单票胜率是否只是噪音）
    all_trades = [t for r in all_rows for t in r["_trades"]]
    sys_st = stats([Trade(**t) for t in all_trades])
    sys_st["tickers_with_data"] = len(all_rows)

    for i, r in enumerate(cands, 1):
        r["rank"] = i
    slim = [{k: v for k, v in r.items() if not k.startswith("_")} for r in cands]
    payload = {
        "as_of": as_of,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rules": {
            "screen1": "周线 26 周 EMA 向上 且 周线 Impulse 不为红",
            "screen2": "日线 2 日 Force Index < 0 且 日线 Impulse 不为红",
            "screen3": "买入止损单 = 前一日最高价 + 0.01",
            "exit": f"移动止损 = 建仓后盘中最高价 − {ATR_MULT:g}×ATR({ATR_N})，只升不降；ATR 取入场时值",
            "ranking": f"纯胜率降序；回测笔数 < {MIN_TRADES} 视为样本不足排后",
            "sizing": f"2% 原则：股数 = 2%×资金 ÷ ({ATR_MULT:g}×ATR)，报告按每 ${SIZE_BASIS:,} 资金给出",
        },
        "system_stats": sys_st,
        "candidate_count": len(slim),
        "candidates": slim,
        "status": status,
    }
    (OUT_DIR / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT_DIR / "history" / f"{as_of}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    pd.DataFrame(slim, columns=CSV_COLS).to_csv(OUT_DIR / "latest.csv", index=False, encoding="utf-8-sig")
    (OUT_DIR / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")

    # Markdown（GitHub 上直接可读）
    lines = [f"# 三重滤网候选清单 — 数据截至 {as_of}（美东收盘）", "",
             f"生成时间（UTC）：{payload['generated_at']}  ",
             f"股票池：{status.get('universe_size', '?')} 只，有数据 {len(all_rows)} 只，候选 {len(slim)} 只  ",
             f"全池回测（同一规则）：{sys_st['trades']} 笔，胜率 {fmt_pct(sys_st['win_rate'])}，"
             f"盈亏比 {fmt(sys_st['payoff'])}，单笔期望 {fmt_pct(sys_st['expectancy'], 2)}，平均持有 {fmt(sys_st['avg_days'], 1)} 天", "",
             "规则：周线 26 周 EMA 向上且周线 Impulse 不为红 → 日线 2 日 Force Index < 0 且日线 Impulse 不为红 → "
             f"买入止损单挂前一日高点 +0.01；出场 = 建仓后最高价 − {ATR_MULT:g}×ATR(14) 移动止损。"
             f"胜率来自每只股票自身约 {LOOKBACK_YEARS - 1} 年的回测，笔数 < {MIN_TRADES} 标记为样本不足。", "",
             "| # | 代码 | 名称 | 状态 | 收盘 | ATR14 | 买入止损价 | 初始止损 | 每股风险 | 每$1万可买 | 胜率 | 笔数 | 盈亏比 | 单笔期望 | 平均持有天 | 模拟持仓 |",
             "|--:|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|"]
    for r in slim:
        low = "⚠️样本不足 " if (r["bt_trades"] or 0) < MIN_TRADES else ""
        sim = (f"持有中 {r['sim_entry_date']} 入场 {r['sim_entry']:.2f}，止损 {r['sim_stop']:.2f}"
               if r["sim_state"] == "long" else "")
        lines.append(f"| {r['rank']} | **{r['ticker']}** | {r['name'][:22]} | {r['status']} | {r['close']:.2f} | {r['atr14']:.2f} | "
                     f"{r['buy_stop']:.2f} | {r['initial_stop']:.2f} | {r['risk_per_share']:.2f} | {r['shares_per_10k']} | "
                     f"{low}{fmt_pct(r['bt_win_rate'])} | {r['bt_trades']} | {fmt(r['bt_payoff'])} | {fmt_pct(r['bt_expectancy'], 2)} | "
                     f"{fmt(r['bt_avg_days'], 1)} | {sim} |")
    if status.get("errors"):
        lines += ["", "## 运行提示", ""] + [f"- {e}" for e in status["errors"][:30]]
    (OUT_DIR / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def load_local_samples(folder: Path) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """--sample 模式：读取本地 CSV（Date,Open,High,Low,Close,Volume），文件名即代码。"""
    prices, metas = {}, []
    for f in sorted(folder.glob("*.csv")):
        t = f.stem.upper()
        df = pd.read_csv(f)
        dcol = next((c for c in df.columns if c.lower() == "date"), df.columns[0])
        df[dcol] = pd.to_datetime(df[dcol])
        df = df.set_index(dcol)
        ren = {}
        for c in df.columns:
            cl = c.lower().split(".")[-1]
            if cl in ("open", "high", "low", "close", "volume"):
                ren[c] = cl.title()
        d = _clean_ohlcv(df.rename(columns=ren))
        if d is not None:
            prices[t] = d
            metas.append({"ticker": t, "name": t, "sector": "", "index": "SAMPLE"})
    return pd.DataFrame(metas), prices


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", help="用本地 CSV 目录代替网络数据（测试用）")
    ap.add_argument("--limit", type=int, help="只跑前 N 只（测试用）")
    args = ap.parse_args()

    status = {"started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "errors": [], "missing": []}
    t0 = time.time()
    try:
        if args.sample:
            uni, prices = load_local_samples(Path(args.sample))
            status["universe_size"] = len(uni)
        else:
            uni = load_universe(status)
            if args.limit:
                uni = uni.head(args.limit)
            tickers = uni["ticker"].tolist()
            prices = fetch_yfinance(tickers, status)
            missing = [t for t in tickers if t not in prices]
            if missing:
                status["errors"].append(f"yfinance 缺 {len(missing)} 只，尝试 stooq 兜底")
                prices.update(fetch_stooq(missing, status))
            status["missing"] = [t for t in tickers if t not in prices]
        status["priced"] = len(prices)

        rows = []
        for _, m in uni.iterrows():
            t = m["ticker"]
            if t not in prices:
                continue
            try:
                r = analyze(t, m.to_dict(), prices[t])
                if r:
                    rows.append(r)
            except Exception as e:  # noqa
                status["errors"].append(f"{t} 计算失败: {e!r}")

        if not rows:
            raise RuntimeError("没有任何股票完成计算")
        # 以多数股票的最后日期为准，剔除数据滞后的票（避免用旧数据发信号）
        dates = pd.Series([r["as_of"] for r in rows])
        as_of = dates.mode().iloc[0]
        stale = [r["ticker"] for r in rows if r["as_of"] != as_of]
        if stale:
            status["errors"].append(f"{len(stale)} 只数据日期 ≠ {as_of}，已排除候选: {', '.join(stale[:20])}")
        cands = sorted([r for r in rows if r["candidate"] and r["as_of"] == as_of], key=rank_key)
        status["as_of"] = as_of
        status["elapsed_sec"] = round(time.time() - t0, 1)
        write_outputs(cands, rows, status, as_of)
        print(f"as_of={as_of} universe={status.get('universe_size')} priced={len(prices)} candidates={len(cands)} "
              f"elapsed={status['elapsed_sec']}s errors={len(status['errors'])}")
        return 0
    except Exception:
        status["fatal"] = traceback.format_exc()
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
        print(status["fatal"], file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

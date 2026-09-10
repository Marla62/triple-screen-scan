#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日选股扫描器 + 策略实验室
================================================
股票池：S&P 500 + 纳斯达克 100

每日模式（python scan.py）：按 config.json 里选定的策略扫描候选、回测每只股票自身的胜率、按胜率排序，
  输出 output/latest.json / latest.csv / latest.md / history/YYYY-MM-DD.json / status.json
实验室模式（python scan.py --lab）：把所有策略在同一股票池、同一时间段、同样手续费下并排回测，
  输出 output/lab.json / lab.md

内置策略（STRATEGIES）：
  triple_screen  三重滤网入场（周线趋势 + 日线 Force Index 回调 + 前高买入止损），2×ATR 移动止损   ← 基准
  ts_target      三重滤网入场，1×ATR 止盈 / 2×ATR 固定止损（演示“止盈近、止损远”对胜率的作用）
  rsi2           RSI(2) 均值回归：收盘 > 200 日均线，RSI(2) < 10 次日开盘买入；收盘站上 5 日均线次日开盘卖出；3×ATR 保护止损；最多持 10 天
  rsi2_strict    同上，RSI(2) < 5
  bb_revert      布林带回归：收盘 > 200 日均线，收盘 < 下轨(20,2) 次日开盘买入；收盘回到中轨(20 日均线) 次日开盘卖出；3×ATR 保护止损；最多持 15 天

成交假设：买入止损单在触发日按 max(触发价, 开盘价) 成交；“次日开盘”按开盘价成交；止损/止盈盘中触发，跳空按开盘价；
  同日同时触及止损与止盈按止损计；收盘条件出场按次日开盘成交；每笔扣除 COST_RT（往返）成本。
"""
from __future__ import annotations

import argparse
import io
import json
import math
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
ATR_N = 14
TICK = 0.01
LOOKBACK_YEARS = 4          # 下载年数（前 ~200 个交易日用于指标预热，不计入回测）
WARMUP_WEEKS = 35
MIN_TRADES = 8              # 少于此笔数的胜率视为“样本不足”
RISK_PCT = 0.02
SIZE_BASIS = 10_000
COST_RT = 0.0005            # 往返成本 0.05%（佣金 + 滑点的保守估计），所有策略一视同仁
OUT_DIR = Path("output")
CONFIG_PATH = Path("config.json")
SP500_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
NDX_WIKI_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"

NDX_FALLBACK = """
AAPL MSFT NVDA AMZN META AVGO GOOGL GOOG TSLA COST NFLX TMUS ASML CSCO PLTR AZN LIN ISRG INTU AMD
PEP ADBE BKNG TXN QCOM AMGN MU ARM HON GILD PANW AMAT SHOP CMCSA ADP APP LRCX VRTX MELI KLAC
CRWD ADI SBUX INTC CEG MSTR CTAS DASH CDNS ORLY MDLZ SNPS MAR FTNT PDD ABNB MRVL REGN ADSK MNST
CSX WDAY AEP PYPL ROP CHTR PCAR AXON NXPI PAYX ROST CPRT FAST EXC KDP DDOG TTWO IDXX CCEP FANG
BKR VRSK XEL EA ZS CTSH LULU ODFL TEAM KHC GEHC CSGP DXCM ON TTD WBD BIIB GFS MDB CDW
""".split()

# 策略注册表 -----------------------------------------------------------------
#   entry: "buy_stop"（信号日次日，前高 + tick 买入止损；未触发逐日下移；周线趋势转弱撤单）
#          "next_open"（信号日次日开盘买入）
#   signal: add_indicators 里生成的布尔列
#   stop_atr: 初始止损 = 入场价 − stop_atr × ATR；trailing=True 时按“建仓后最高价 − stop_atr × ATR”上移
#   target_atr: 止盈 = 入场价 + target_atr × ATR（None 不设）
#   exit_cond: 收盘满足该布尔列 → 次日开盘卖出（None 不设）
#   max_days: 持有超过 N 个交易日 → 次日开盘卖出（None 不设）
STRATEGIES = {
    "triple_screen": dict(label="三重滤网 + 2×ATR 移动止损", entry="buy_stop", signal="sig_ts",
                          stop_atr=2.0, trailing=True, target_atr=None, exit_cond=None, max_days=None,
                          desc="周线 26 周 EMA 向上且周线 Impulse 不为红；日线 2 日 Force Index < 0 且日线 Impulse 不为红；"
                               "买入止损单挂前一日高点 + 0.01；出场 = 建仓后最高价 − 2×ATR 移动止损"),
    "ts_target": dict(label="三重滤网 + 1×ATR 止盈 / 2×ATR 止损", entry="buy_stop", signal="sig_ts",
                      stop_atr=2.0, trailing=False, target_atr=1.0, exit_cond=None, max_days=None,
                      desc="入场同三重滤网；止盈 = 入场价 + 1×ATR，止损 = 入场价 − 2×ATR（固定）"),
    "rsi2": dict(label="RSI(2) 均值回归 (<10)", entry="next_open", signal="sig_rsi2",
                 stop_atr=3.0, trailing=False, target_atr=None, exit_cond="x_sma5", max_days=10,
                 desc="收盘 > 200 日均线 且 RSI(2) < 10 → 次日开盘买入；收盘 > 5 日均线 → 次日开盘卖出；3×ATR 保护止损；最多持 10 天"),
    "rsi2_strict": dict(label="RSI(2) 均值回归 (<5)", entry="next_open", signal="sig_rsi2s",
                        stop_atr=3.0, trailing=False, target_atr=None, exit_cond="x_sma5", max_days=10,
                        desc="同 rsi2，但 RSI(2) < 5"),
    "bb_revert": dict(label="布林带回归", entry="next_open", signal="sig_bb",
                      stop_atr=3.0, trailing=False, target_atr=None, exit_cond="x_sma20", max_days=15,
                      desc="收盘 > 200 日均线 且 收盘 < 布林下轨(20,2) → 次日开盘买入；收盘 ≥ 中轨(20 日均线) → 次日开盘卖出；3×ATR 保护止损；最多持 15 天"),
}
DEFAULT_STRATEGY = "triple_screen"


def load_config() -> dict:
    cfg = {"strategy": DEFAULT_STRATEGY}
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception as e:  # noqa
            print(f"config.json 解析失败，使用默认: {e!r}", file=sys.stderr)
    if cfg["strategy"] not in STRATEGIES:
        print(f"config.json 里的策略 {cfg['strategy']!r} 不存在，使用默认 {DEFAULT_STRATEGY}", file=sys.stderr)
        cfg["strategy"] = DEFAULT_STRATEGY
    return cfg


# ----------------------------------------------------------------------------
# 股票池
# ----------------------------------------------------------------------------
def load_universe(status: dict) -> pd.DataFrame:
    import requests

    rows = {}
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

    ndx = []
    for src_name, fn in (("wikipedia", _ndx_from_wikipedia), ("invesco_qqq", _ndx_from_invesco)):
        try:
            ndx = fn(status)
            if len(ndx) >= 80:
                status["ndx_source"] = src_name
                break
            status["errors"].append(f"纳斯达克 100 来源 {src_name} 只解析到 {len(ndx)} 只，换下一个来源")
            ndx = []
        except Exception as e:  # noqa
            status["errors"].append(f"纳斯达克 100 来源 {src_name} 失败: {e!r}")
    if not ndx:
        status["errors"].append("纳斯达克 100 名单全部来源失败，使用内置兜底名单")
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


def _pick_ticker_table(tables: list[pd.DataFrame], status: dict, tag: str) -> list[tuple[str, str, str]]:
    """在若干表格里找“成分股表”：优先列名含 ticker/symbol，否则找同时含 AAPL/MSFT/NVDA 的列。"""
    shapes = []
    for tb in tables:
        tb = tb.copy()
        tb.columns = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in tb.columns]
        shapes.append(f"{tb.shape[0]}x{tb.shape[1]}:{'|'.join(str(c)[:12] for c in tb.columns[:5])}")
        if len(tb) < 80 or len(tb) > 130:
            continue
        cols = list(tb.columns)
        tcol = next((c for c in cols if "ticker" in c.lower() or "symbol" in c.lower()), None)
        if tcol is None:
            for c in cols:
                vals = set(tb[c].astype(str).str.strip().str.upper())
                if {"AAPL", "MSFT", "NVDA"} <= vals:
                    tcol = c
                    break
        if tcol is None:
            continue
        ncol = next((c for c in cols if any(k in c.lower() for k in ("company", "security", "name"))), None)
        scol = next((c for c in cols if "sector" in c.lower()), None)
        out = []
        for _, x in tb.iterrows():
            t = str(x[tcol]).strip().upper()
            if t and t != "NAN" and len(t) <= 6:
                out.append((t, str(x[ncol]) if ncol else t, str(x[scol]) if scol else ""))
        if len(out) >= 80:
            return out
    status[f"ndx_{tag}_tables"] = shapes[:12]  # 诊断：没匹配上时记录各表形状
    return []


def _ndx_from_wikipedia(status: dict) -> list[tuple[str, str, str]]:
    import requests

    r = requests.get(NDX_WIKI_URL, timeout=30,
                     headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) triple-screen-scan/1.0 (+https://github.com)"})
    r.raise_for_status()
    status["ndx_wikipedia_bytes"] = len(r.text)
    return _pick_ticker_table(pd.read_html(io.StringIO(r.text)), status, "wikipedia")


def _ndx_from_invesco(status: dict) -> list[tuple[str, str, str]]:
    """Invesco QQQ 持仓 CSV（跟踪纳斯达克 100）。"""
    import requests

    url = ("https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0"
           "?audienceType=Investor&action=download&ticker=QQQ")
    r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [str(c).strip() for c in df.columns]
    tcol = next((c for c in df.columns if "holding ticker" in c.lower() or c.lower() == "ticker"), None)
    if tcol is None:
        for c in df.columns:
            vals = set(df[c].astype(str).str.strip().str.upper())
            if {"AAPL", "MSFT", "NVDA"} <= vals:
                tcol = c
                break
    if tcol is None:
        status["ndx_invesco_columns"] = list(df.columns)[:10]
        return []
    ncol = next((c for c in df.columns if c.lower() in ("name", "security name", "holding name")), None)
    scol = next((c for c in df.columns if "sector" in c.lower()), None)
    out = []
    for _, x in df.iterrows():
        t = str(x[tcol]).strip().upper()
        if t and t != "NAN" and len(t) <= 6 and t.replace(".", "").isalpha():
            out.append((t, str(x[ncol]) if ncol else t, str(x[scol]) if scol else ""))
    return out


def to_yahoo_symbol(t: str) -> str:
    return t.replace(".", "-")


# ----------------------------------------------------------------------------
# 行情
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
        raw = None
        for attempt in range(3):
            try:
                raw = yf.download(chunk, start=start, interval="1d", auto_adjust=False,
                                  group_by="ticker", threads=True, progress=False, timeout=30)
                break
            except Exception as e:  # noqa
                status["errors"].append(f"yfinance 批次 {i // batch} 第 {attempt + 1} 次失败: {e!r}")
                time.sleep(10 * (attempt + 1))
        if raw is None or len(raw) == 0:
            continue
        if isinstance(raw.columns, pd.MultiIndex):
            lvl0 = raw.columns.get_level_values(0)
            for s in chunk:
                if s in lvl0:
                    d = _clean_ohlcv(raw[s])
                    if d is not None:
                        out[sym_map[s]] = d
        elif len(chunk) == 1:
            d = _clean_ohlcv(raw)
            if d is not None:
                out[sym_map[chunk[0]]] = d
        time.sleep(pause)
    return out


def fetch_stooq(tickers: list[str], status: dict, max_n: int = 150) -> dict[str, pd.DataFrame]:
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
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def rsi(c: pd.Series, n: int) -> pd.Series:
    diff = c.diff()
    up = diff.clip(lower=0).ewm(alpha=1.0 / n, adjust=False).mean()
    dn = (-diff.clip(upper=0)).ewm(alpha=1.0 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(100.0).where(dn != 0, 100.0)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c = d["Close"]
    d["atr"] = atr(d)
    # 日线（三重滤网用）
    d["ema13"] = ema(c, 13)
    macd = ema(c, 12) - ema(c, 26)
    d["hist"] = macd - ema(macd, 9)
    d["fi2"] = ema((c - c.shift(1)) * d["Volume"], 2)
    d["d_red"] = (d["ema13"] < d["ema13"].shift(1)) & (d["hist"] < d["hist"].shift(1))
    # 均值回归用
    d["sma5"] = c.rolling(5).mean()
    d["sma20"] = c.rolling(20).mean()
    d["sma200"] = c.rolling(200).mean()
    sd20 = c.rolling(20).std(ddof=0)
    d["bb_lo"] = d["sma20"] - 2 * sd20
    d["bb_hi"] = d["sma20"] + 2 * sd20
    d["rsi2"] = rsi(c, 2)

    # 周线（已收周 K 的 EMA + 本周部分更新）
    w = d.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    w = w.dropna(subset=["Close"])
    wc = w["Close"]
    w_e26, w_e13, w_e12 = ema(wc, 26), ema(wc, 13), ema(wc, 12)
    w_macd = w_e12 - w_e26
    w_sig = ema(w_macd, 9)
    w_hist = w_macd - w_sig
    days_to_fri = (4 - d.index.weekday) % 7
    week_end = d.index + pd.to_timedelta(days_to_fri, unit="D")
    prev_pos = np.searchsorted(w.index.values, week_end.values, side="left") - 1
    w_ok = prev_pos >= WARMUP_WEEKS
    pp = np.clip(prev_pos, 0, len(w) - 1)

    def take(s: pd.Series) -> np.ndarray:
        arr = s.values[pp].astype(float)
        arr[~w_ok] = np.nan
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
    d["w_ema26_up"] = e26 > E26p
    d["w_hist_up"] = hist > HISTp
    d["w_red"] = (e13 < E13p) & (hist < HISTp)

    # 统一的有效区间：周线预热完成 且 200 日均线可用（所有策略同一起点，便于公平对比）
    d["valid"] = w_ok & d["sma200"].notna() & d["atr"].notna()
    d["screen1"] = d["valid"] & d["w_ema26_up"] & ~d["w_red"]
    d["screen2"] = (d["fi2"] < 0) & ~d["d_red"]
    d["sig_ts"] = d["screen1"] & d["screen2"]
    up = d["valid"] & (c > d["sma200"])
    d["sig_rsi2"] = up & (d["rsi2"] < 10)
    d["sig_rsi2s"] = up & (d["rsi2"] < 5)
    d["sig_bb"] = up & (c < d["bb_lo"])
    d["x_sma5"] = c > d["sma5"]
    d["x_sma20"] = c >= d["sma20"]
    return d


# ----------------------------------------------------------------------------
# 通用回测
# ----------------------------------------------------------------------------
@dataclass
class Trade:
    entry_date: str
    exit_date: str
    entry: float
    exit: float
    ret: float
    days: int
    reason: str


def run_strategy(d: pd.DataFrame, st: dict) -> tuple[list[Trade], dict]:
    O, H, L, C = (d[k].values.astype(float) for k in ("Open", "High", "Low", "Close"))
    A = d["atr"].values.astype(float)
    S = d[st["signal"]].values.astype(bool)
    W = d["screen1"].values.astype(bool)
    X = d[st["exit_cond"]].values.astype(bool) if st["exit_cond"] else None
    V = d["valid"].values.astype(bool)
    idx = d.index
    n = len(d)
    first = int(np.argmax(V)) if V.any() else n
    k_stop, k_tgt, trailing, max_days = st["stop_atr"], st["target_atr"], st["trailing"], st["max_days"]

    trades: list[Trade] = []
    state = "flat"          # flat / pending_stop / pending_open / long
    trigger = math.nan
    pending_since = -1
    entry = atr_e = hh = stop = target = math.nan
    entry_i = -1
    days_held = 0
    exit_pending = None     # None 或 出场原因（次日开盘执行）

    def open_position(i: int, px: float) -> bool:
        """在第 i 天以 px 建仓；返回 False 表示当天就被止损（已记录交易）。"""
        nonlocal entry, entry_i, atr_e, hh, stop, target, days_held, exit_pending, state
        a = A[i - 1]
        if not np.isfinite(a) or a <= 0:
            return False
        entry, entry_i, atr_e, days_held, exit_pending = px, i, a, 0, None
        stop = entry - k_stop * a
        target = entry + k_tgt * a if k_tgt else math.nan
        hh = H[i]
        if L[i] <= stop:  # 入场当天触及初始止损：保守按止损出局
            trades.append(Trade(str(idx[i].date()), str(idx[i].date()), entry, stop, stop / entry - 1 - COST_RT, 0, "stop"))
            state = "flat"
            return False
        if trailing:
            stop = max(stop, hh - k_stop * a)
        if X is not None and X[i]:
            exit_pending = "cond"
        state = "long"
        return True

    for i in range(max(first, 1), n):
        o, h, l = O[i], H[i], L[i]
        if state == "long":
            px, reason = None, None
            if exit_pending:
                px, reason = o, exit_pending
            elif l <= stop:
                px, reason = (stop if o >= stop else o), "stop"
            elif k_tgt and h >= target:
                px, reason = (target if o <= target else o), "target"
            if px is not None:
                trades.append(Trade(str(idx[entry_i].date()), str(idx[i].date()), entry, px, px / entry - 1 - COST_RT,
                                    i - entry_i, reason))
                state = "flat"
            else:
                days_held += 1
                if trailing:
                    hh = max(hh, h)
                    stop = max(stop, hh - k_stop * atr_e)
                if X is not None and X[i]:
                    exit_pending = "cond"
                elif max_days and days_held >= max_days:
                    exit_pending = "time"
        elif state == "pending_stop":
            if h > trigger:
                open_position(i, o if o > trigger else trigger)
            elif W[i]:
                trigger = min(trigger, h + TICK)
            else:
                state = "flat"
        elif state == "pending_open":
            open_position(i, o)

        if state == "flat" and S[i]:
            if st["entry"] == "buy_stop":
                state, trigger, pending_since = "pending_stop", h + TICK, i
            else:
                state, pending_since = "pending_open", i

    last = {
        "state": state,
        "trigger": float(trigger) if state == "pending_stop" else None,
        "pending_since": str(idx[pending_since].date()) if state.startswith("pending") and pending_since >= 0 else None,
        "sim_entry": float(entry) if state == "long" else None,
        "sim_entry_date": str(idx[entry_i].date()) if state == "long" else None,
        "sim_stop": float(stop) if state == "long" else None,
        "sim_target": float(target) if state == "long" and k_tgt else None,
        "sim_exit_pending": exit_pending if state == "long" else None,
    }
    return trades, last


def wilson_lb(wins: int, n: int, z: float = 1.96) -> float:
    """胜率的 Wilson 95% 置信下界：样本越少，向下修正越多（10 笔 10 胜 ≈ 72%，35 笔 30 胜 ≈ 71%）。"""
    if n <= 0:
        return 0.0
    p = wins / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / denom


def stats(trades: list[Trade]) -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0, "wins": 0, "win_rate": None, "win_rate_lb": 0.0, "avg_win": None, "avg_loss": None,
                "payoff": None, "expectancy": None, "profit_factor": None, "avg_days": None, "exp_per_day": None, "reasons": {}}
    r = np.array([t.ret for t in trades])
    wins, losses = r[r > 0], r[r <= 0]
    aw = float(wins.mean()) if len(wins) else 0.0
    al = float(losses.mean()) if len(losses) else 0.0
    days = np.array([max(t.days, 1) for t in trades])
    reasons = {}
    for t in trades:
        reasons[t.reason] = reasons.get(t.reason, 0) + 1
    return {
        "trades": n, "wins": int(len(wins)), "win_rate": float(len(wins) / n),
        "win_rate_lb": wilson_lb(int(len(wins)), n),
        "avg_win": aw, "avg_loss": al,
        "payoff": float(aw / abs(al)) if al < 0 else None,
        "expectancy": float(r.mean()),
        "profit_factor": float(wins.sum() / abs(losses.sum())) if losses.sum() < 0 else None,
        "avg_days": float(np.mean([t.days for t in trades])),
        "exp_per_day": float(r.mean() / days.mean()),
        "reasons": reasons,
    }


# ----------------------------------------------------------------------------
# 单票分析（每日模式）
# ----------------------------------------------------------------------------
def analyze(ticker: str, meta: dict, d: pd.DataFrame, strat_name: str) -> dict | None:
    st = STRATEGIES[strat_name]
    if not d["valid"].any():
        return None
    trades, last = run_strategy(d, st)
    s = stats(trades)
    row = d.iloc[-1]
    as_of = str(d.index[-1].date())
    a = float(row["atr"])
    is_signal = bool(row[st["signal"]])
    is_pending = last["state"].startswith("pending")
    candidate = is_signal or is_pending
    if st["entry"] == "buy_stop":
        ref = float(row["High"]) + TICK if candidate else None  # 买入止损价
        entry_text = "买入止损单 @ 前一日高点 + 0.01"
    else:
        ref = float(row["Close"]) if candidate else None        # 次日开盘买入，参考价 = 收盘
        entry_text = "次日开盘买入（参考价 = 收盘价）"
    risk_ps = st["stop_atr"] * a
    shares = int(math.floor(RISK_PCT * SIZE_BASIS / risk_ps)) if risk_ps > 0 else None
    return {
        "ticker": ticker, "name": meta.get("name", ticker), "sector": meta.get("sector", ""), "index": meta.get("index", ""),
        "strategy": strat_name, "as_of": as_of,
        "close": round(float(row["Close"]), 2), "high": round(float(row["High"]), 2),
        "atr14": round(a, 3), "atr_pct": round(a / float(row["Close"]) * 100, 2),
        "candidate": candidate,
        "status": "新信号" if is_signal else ("挂单延续" if is_pending else ""),
        "signal_date": as_of if is_signal else last.get("pending_since"),
        "entry_mode": st["entry"], "entry_text": entry_text,
        "buy_stop": round(ref, 2) if (ref and st["entry"] == "buy_stop") else None,
        "ref_price": round(ref, 2) if ref else None,
        "initial_stop": round(ref - risk_ps, 2) if ref else None,
        "target": round(ref + st["target_atr"] * a, 2) if (ref and st["target_atr"]) else None,
        "exit_text": exit_text(st),
        "risk_per_share": round(risk_ps, 3), "shares_per_10k": shares,
        "rsi2": round(float(row["rsi2"]), 1), "fi2": round(float(row["fi2"]), 0),
        "w_hist_up": bool(row["w_hist_up"]), "screen1": bool(row["screen1"]), "screen2": bool(row["screen2"]),
        "sim_state": last["state"], "sim_entry": last["sim_entry"], "sim_entry_date": last["sim_entry_date"],
        "sim_stop": round(last["sim_stop"], 2) if last["sim_stop"] else None,
        "bt_from": trades[0].entry_date if trades else None,
        **{f"bt_{k}": v for k, v in s.items() if k != "reasons"},
        "_trades": [asdict(t) for t in trades],
    }


def exit_text(st: dict) -> str:
    parts = []
    if st["trailing"]:
        parts.append(f"移动止损 = 建仓后最高价 − {st['stop_atr']:g}×ATR")
    else:
        parts.append(f"止损 = 入场价 − {st['stop_atr']:g}×ATR")
    if st["target_atr"]:
        parts.append(f"止盈 = 入场价 + {st['target_atr']:g}×ATR")
    if st["exit_cond"] == "x_sma5":
        parts.append("收盘 > 5 日均线 → 次日开盘卖出")
    if st["exit_cond"] == "x_sma20":
        parts.append("收盘 ≥ 20 日均线(中轨) → 次日开盘卖出")
    if st["max_days"]:
        parts.append(f"最多持有 {st['max_days']} 个交易日")
    return "；".join(parts)


def rank_key(r: dict):
    """按样本修正后的胜率（Wilson 95% 下界）降序；并列看盈亏比、笔数。"""
    return (-(r["bt_win_rate_lb"] or 0), -(r["bt_payoff"] or 0), -(r["bt_trades"] or 0))


# ----------------------------------------------------------------------------
# 输出（每日模式）
# ----------------------------------------------------------------------------
CSV_COLS = ["rank", "ticker", "name", "sector", "index", "strategy", "status", "signal_date", "close", "high", "atr14", "atr_pct",
            "entry_mode", "buy_stop", "ref_price", "initial_stop", "target", "risk_per_share", "shares_per_10k",
            "bt_win_rate_lb", "bt_win_rate", "bt_trades", "bt_wins", "bt_payoff", "bt_expectancy", "bt_profit_factor", "bt_avg_days",
            "rsi2", "w_hist_up", "fi2"]


def fmt_pct(x, nd=1):
    return "" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 100:.{nd}f}%"


def fmt(x, nd=2):
    return "" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def write_outputs(cands: list[dict], all_rows: list[dict], status: dict, as_of: str, strat_name: str) -> None:
    st = STRATEGIES[strat_name]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "history").mkdir(exist_ok=True)
    all_trades = [Trade(**t) for r in all_rows for t in r["_trades"]]
    sys_st = stats(all_trades)
    sys_st["tickers_with_data"] = len(all_rows)

    for i, r in enumerate(cands, 1):
        r["rank"] = i
    slim = [{k: v for k, v in r.items() if not k.startswith("_")} for r in cands]
    payload = {
        "as_of": as_of,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "strategy": strat_name, "strategy_label": st["label"], "strategy_desc": st["desc"],
        "entry_mode": st["entry"], "exit_rule": exit_text(st),
        "rules": {
            "ranking": f"按样本修正后的胜率（Wilson 95% 置信下界）降序，小样本自动向下修正；笔数 < {MIN_TRADES} 仍标注样本不足",
            "sizing": f"2% 原则：股数 = 2%×资金 ÷ ({st['stop_atr']:g}×ATR)，报告按每 ${SIZE_BASIS:,} 资金给出",
            "cost": f"回测每笔扣往返成本 {COST_RT * 100:.2f}%",
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

    price_hdr = "买入止损价" if st["entry"] == "buy_stop" else "参考价(收盘)"
    lines = [f"# 候选清单 — {st['label']} — 数据截至 {as_of}（美东收盘）", "",
             f"生成时间（UTC）：{payload['generated_at']}  ",
             f"股票池：{status.get('universe_size', '?')} 只，有数据 {len(all_rows)} 只，候选 {len(slim)} 只  ",
             f"全池回测（同一规则）：{sys_st['trades']} 笔，胜率 {fmt_pct(sys_st['win_rate'])}，盈亏比 {fmt(sys_st['payoff'])}，"
             f"单笔期望 {fmt_pct(sys_st['expectancy'], 2)}，平均持有 {fmt(sys_st['avg_days'], 1)} 天", "",
             f"入场：{st['desc']}  ", f"出场：{exit_text(st)}  ",
             f"胜率来自每只股票自身约 {LOOKBACK_YEARS - 1} 年的回测（含 {COST_RT * 100:.2f}% 往返成本）。排序用“修正胜率”= Wilson 95% 置信下界，"
             f"样本越少向下修正越多（10 笔 10 胜 ≈ 72%）；笔数 < {MIN_TRADES} 另标注样本不足。", "",
             f"| # | 代码 | 名称 | 状态 | 收盘 | ATR14 | {price_hdr} | 初始止损 | 止盈 | 每股风险 | 每$1万可买 | 修正胜率 | 原始胜率 | 笔数 | 盈亏比 | 单笔期望 | 平均持有天 | 模拟持仓 |",
             "|--:|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|"]
    for r in slim:
        low = "⚠️样本不足 " if (r["bt_trades"] or 0) < MIN_TRADES else ""
        sim = (f"持有中 {r['sim_entry_date']} 入场 {r['sim_entry']:.2f}，止损 {r['sim_stop']:.2f}" if r["sim_state"] == "long" else "")
        lines.append(f"| {r['rank']} | **{r['ticker']}** | {r['name'][:22]} | {r['status']} | {r['close']:.2f} | {r['atr14']:.2f} | "
                     f"{r['ref_price']:.2f} | {r['initial_stop']:.2f} | {fmt(r['target'])} | {r['risk_per_share']:.2f} | {r['shares_per_10k']} | "
                     f"**{fmt_pct(r['bt_win_rate_lb'])}** | {low}{fmt_pct(r['bt_win_rate'])} | {r['bt_trades']} | {fmt(r['bt_payoff'])} | {fmt_pct(r['bt_expectancy'], 2)} | "
                     f"{fmt(r['bt_avg_days'], 1)} | {sim} |")
    if status.get("errors"):
        lines += ["", "## 运行提示", ""] + [f"- {e}" for e in status["errors"][:30]]
    (OUT_DIR / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------------
# 策略实验室
# ----------------------------------------------------------------------------
def run_lab(uni: pd.DataFrame, prices: dict[str, pd.DataFrame], status: dict) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ind = {}
    for t in uni["ticker"]:
        if t in prices:
            try:
                d = add_indicators(prices[t])
                if d["valid"].any():
                    ind[t] = d
            except Exception as e:  # noqa
                status["errors"].append(f"{t} 指标计算失败: {e!r}")
    as_of = pd.Series([str(d.index[-1].date()) for d in ind.values()]).mode().iloc[0]
    results = {}
    for name, st in STRATEGIES.items():
        all_trades, per_ticker, cand_today = [], [], 0
        for t, d in ind.items():
            trades, last = run_strategy(d, st)
            all_trades += trades
            s = stats(trades)
            per_ticker.append({"ticker": t, **{k: v for k, v in s.items() if k != "reasons"}})
            if bool(d.iloc[-1][st["signal"]]) or last["state"].startswith("pending"):
                cand_today += 1
        sys_st = stats(all_trades)
        # 按年
        by_year = {}
        for tr in all_trades:
            by_year.setdefault(tr.entry_date[:4], []).append(tr)
        yearly = {y: {k: v for k, v in stats(v_).items() if k in ("trades", "win_rate", "payoff", "expectancy")}
                  for y, v_ in sorted(by_year.items())}
        wr = [p["win_rate"] for p in per_ticker if (p["trades"] or 0) >= MIN_TRADES]
        top = sorted([p for p in per_ticker if (p["trades"] or 0) >= MIN_TRADES],
                     key=lambda p: (-(p["win_rate_lb"] or 0), -(p["payoff"] or 0)))[:15]
        years = max((len(d) for d in ind.values()), default=250) / 252
        results[name] = {
            "label": st["label"], "desc": st["desc"], "exit": exit_text(st),
            "system": sys_st,
            "trades_per_ticker_per_year": round(sys_st["trades"] / max(len(ind), 1) / max(years - 0.8, 0.5), 2),
            "tickers_ranked": len(wr),
            "median_ticker_win_rate": float(np.median(wr)) if wr else None,
            "pct_tickers_wr_ge_50": float(np.mean([x >= 0.5 for x in wr])) if wr else None,
            "candidates_today": cand_today,
            "yearly": yearly,
            "top_tickers": top,
        }
    payload = {"as_of": as_of, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "tickers": len(ind), "cost_rt": COST_RT, "min_trades": MIN_TRADES, "strategies": results, "status": status}
    (OUT_DIR / "lab.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = [f"# 策略实验室 — 数据截至 {as_of}", "",
             f"股票池 {len(ind)} 只，约 {LOOKBACK_YEARS - 1} 年回测窗口（所有策略同一起点），每笔扣往返成本 {COST_RT * 100:.2f}%。", "",
             "| 策略 | 笔数 | 胜率 | 平均盈利 | 平均亏损 | 盈亏比 | 单笔期望 | 日均期望 | 利润因子 | 平均持有天 | 每票每年笔数 | 单票胜率中位数 | 胜率≥50%的票占比 | 今日候选 |",
             "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for name, r in results.items():
        s = r["system"]
        lines.append(f"| **{r['label']}** | {s['trades']} | {fmt_pct(s['win_rate'])} | {fmt_pct(s['avg_win'], 2)} | {fmt_pct(s['avg_loss'], 2)} | "
                     f"{fmt(s['payoff'])} | {fmt_pct(s['expectancy'], 2)} | {fmt_pct(s['exp_per_day'], 3)} | {fmt(s['profit_factor'])} | "
                     f"{fmt(s['avg_days'], 1)} | {r['trades_per_ticker_per_year']} | {fmt_pct(r['median_ticker_win_rate'])} | "
                     f"{fmt_pct(r['pct_tickers_wr_ge_50'], 0)} | {r['candidates_today']} |")
    lines += ["", "## 分年表现（按入场年份）", ""]
    years_all = sorted({y for r in results.values() for y in r["yearly"]})
    lines.append("| 策略 | " + " | ".join(years_all) + " |")
    lines.append("|---|" + "---|" * len(years_all))
    for name, r in results.items():
        cells = []
        for y in years_all:
            yy = r["yearly"].get(y)
            cells.append(f"{yy['trades']}笔 胜率{fmt_pct(yy['win_rate'], 0)} 期望{fmt_pct(yy['expectancy'], 2)}" if yy else "")
        lines.append(f"| {r['label']} | " + " | ".join(cells) + " |")
    lines += ["", "## 出场原因分布", ""]
    for name, r in results.items():
        lines.append(f"- {r['label']}：" + "，".join(f"{k} {v}" for k, v in r["system"]["reasons"].items()))
    lines += ["", "## 各策略修正胜率最高的股票（Wilson 下界，笔数 ≥ 8）", ""]
    for name, r in results.items():
        lines.append(f"**{r['label']}**：" + "，".join(f"{p['ticker']} 修正{fmt_pct(p['win_rate_lb'], 0)}/原始{fmt_pct(p['win_rate'], 0)}({p['trades']}笔, 盈亏比{fmt(p['payoff'], 1)})" for p in r["top_tickers"][:10]))
        lines.append("")
    lines += ["## 策略定义", ""] + [f"- **{r['label']}**：{r['desc']}。出场：{r['exit']}" for r in results.values()]
    (OUT_DIR / "lab.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def load_local_samples(folder: Path) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
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
    ap.add_argument("--lab", action="store_true", help="策略实验室：并排回测所有策略")
    ap.add_argument("--strategy", help="覆盖 config.json 里的策略（每日模式）")
    args = ap.parse_args()

    cfg = load_config()
    strat_name = args.strategy if args.strategy in STRATEGIES else cfg["strategy"]
    status = {"started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "errors": [], "missing": [],
              "strategy": strat_name, "mode": "lab" if args.lab else "daily"}
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

        if args.lab:
            payload = run_lab(uni, prices, status)
            status["elapsed_sec"] = round(time.time() - t0, 1)
            (OUT_DIR / "lab_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
            for name, r in payload["strategies"].items():
                s = r["system"]
                print(f"{name:14s} trades={s['trades']:6d} win={fmt_pct(s['win_rate'])} payoff={fmt(s['payoff'])} "
                      f"exp={fmt_pct(s['expectancy'], 2)} days={fmt(s['avg_days'], 1)} cand={r['candidates_today']}")
            return 0

        rows = []
        for _, m in uni.iterrows():
            t = m["ticker"]
            if t not in prices:
                continue
            try:
                r = analyze(t, m.to_dict(), add_indicators(prices[t]), strat_name)
                if r:
                    rows.append(r)
            except Exception as e:  # noqa
                status["errors"].append(f"{t} 计算失败: {e!r}")
        if not rows:
            raise RuntimeError("没有任何股票完成计算")
        dates = pd.Series([r["as_of"] for r in rows])
        as_of = dates.mode().iloc[0]
        stale = [r["ticker"] for r in rows if r["as_of"] != as_of]
        if stale:
            status["errors"].append(f"{len(stale)} 只数据日期 ≠ {as_of}，已排除候选: {', '.join(stale[:20])}")
        cands = sorted([r for r in rows if r["candidate"] and r["as_of"] == as_of], key=rank_key)
        status["as_of"] = as_of
        status["elapsed_sec"] = round(time.time() - t0, 1)
        write_outputs(cands, rows, status, as_of, strat_name)
        print(f"strategy={strat_name} as_of={as_of} universe={status.get('universe_size')} priced={len(prices)} "
              f"candidates={len(cands)} elapsed={status['elapsed_sec']}s errors={len(status['errors'])}")
        return 0
    except Exception:
        status["fatal"] = traceback.format_exc()
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / ("lab_status.json" if args.lab else "status.json")).write_text(
            json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
        print(status["fatal"], file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

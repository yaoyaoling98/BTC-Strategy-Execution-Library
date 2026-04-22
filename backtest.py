#!/usr/bin/env python3
"""
BTC/USD 均值回归策略回测
算法与 btc-signal-v2.html 完全一致：
  Jesse  → RSI(Wilder) / BB / EMA / VWAP(每日重置)
  Freqtrade → 信号触发逻辑 / EMA趋势风控
"""

import requests, time, math
from datetime import datetime
from collections import defaultdict

# ── 配置 ──────────────────────────────────────────────────────────
PAIR          = 'XBTUSD'
INTERVAL      = 15            # 15分钟K线
START_TS      = 1640995200    # 2022-01-01 UTC
END_TS        = 1735689600    # 2025-01-01 UTC
KRAKEN_URL    = 'https://api.kraken.com/0/public/OHLC'

RSI_PERIOD    = 14
BB_PERIOD     = 20
BB_STD        = 2
EMA_SHORT     = 20
EMA_LONG      = 50
VOL_PERIOD    = 20
SIG_THRESHOLD = 70
STOP_LOSS     = 0.015         # 1.5%
TAKE_PROFIT   = 0.030         # 3.0%  (2:1盈亏比)
EOD_HOUR_UTC  = 22            # 每天22:00 UTC 强制平仓（模拟睡前清仓）

# ── 数据下载 ──────────────────────────────────────────────────────
def download_ohlcv():
    candles, since = [], START_TS
    print(f"下载 BTC/USD 15m K线: 2022-01-01 → 2024-12-31")
    while True:
        try:
            r = requests.get(f"{KRAKEN_URL}?pair={PAIR}&interval={INTERVAL}&since={since}", timeout=20)
            data = r.json()
        except Exception as e:
            print(f"  请求失败，3秒后重试: {e}"); time.sleep(3); continue

        if data.get('error'): print(f"  API错误: {data['error']}"); break

        result = data['result']
        raw = result.get(PAIR) or result.get('XXBTZUSD', [])
        if not raw: break

        added = 0
        for c in raw:
            ts = int(c[0])
            if ts >= END_TS: break
            candles.append({'time': ts, 'open': float(c[1]), 'high': float(c[2]),
                            'low': float(c[3]), 'close': float(c[4]), 'volume': float(c[6])})
            added += 1
        else:
            last_ts = int(raw[-1][0])
            print(f"  → {datetime.utcfromtimestamp(last_ts).date()}  累计 {len(candles)} 根")
            if last_ts <= since: break
            since = last_ts
            time.sleep(1.2)
            continue
        break  # 已到END_TS

    return candles

# ── 指标计算（Jesse公式，与HTML完全一致）─────────────────────────

def calc_rsi(closes, period=RSI_PERIOD):
    if len(closes) < period + 1: return None
    g = l = 0
    for i in range(1, period + 1):
        d = closes[i] - closes[i-1]
        if d > 0: g += d
        else:     l += abs(d)
    ag, al = g / period, l / period
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i-1]
        ag = (ag * (period-1) + (d if d > 0 else 0))          / period
        al = (al * (period-1) + (abs(d) if d < 0 else 0))     / period
    if al == 0: return 100.0
    return 100 - 100 / (1 + ag / al)

def calc_bb(closes, period=BB_PERIOD, mult=BB_STD):
    if len(closes) < period: return None
    sl  = closes[-period:]
    mid = sum(sl) / period
    std = math.sqrt(sum((x - mid)**2 for x in sl) / period)
    lo, hi = mid - mult*std, mid + mult*std
    pct = (closes[-1] - lo) / (hi - lo) if hi != lo else 0.5
    return {'upper': hi, 'middle': mid, 'lower': lo, 'pct': pct}

def calc_ema(closes, period):
    if len(closes) < period: return closes[-1]
    k   = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for x in closes[period:]: ema = x * k + ema * (1 - k)
    return ema

def calc_vwap(day_candles):
    cvp = cv = 0
    for c in day_candles:
        tp  = (c['high'] + c['low'] + c['close']) / 3
        cvp += tp * c['volume']
        cv  += c['volume']
    return cvp / cv if cv > 0 else None

def calc_vol_ratio(volumes, period=VOL_PERIOD):
    if len(volumes) < period + 1: return 1.0
    avg = sum(volumes[-period-1:-1]) / period
    return volumes[-1] / avg if avg > 0 else 1.0

# ── 打分系统（Freqtrade信号逻辑，与HTML完全一致）────────────────

def score_rsi(rsi):
    if rsi is None: return 0, 0
    if rsi <= 20: return 25, +1
    if rsi <= 30: return 20, +1
    if rsi <= 38: return 10, +1
    if rsi <= 45: return  4, +1
    if rsi <  55: return  0,  0
    if rsi <  62: return  4, -1
    if rsi <  70: return 10, -1
    if rsi <  80: return 20, -1
    return 25, -1

def score_bb(pct):
    if pct <= 0.00: return 25, +1
    if pct <= 0.10: return 22, +1
    if pct <= 0.20: return 16, +1
    if pct <= 0.35: return  7, +1
    if pct <= 0.65: return  0,  0
    if pct <= 0.80: return  7, -1
    if pct <= 0.90: return 16, -1
    if pct <= 1.00: return 22, -1
    return 25, -1

def score_vwap(dev):
    a = abs(dev)
    s = 25 if a >= 2.0 else 20 if a >= 1.2 else 14 if a >= 0.6 else 7 if a >= 0.3 else 2
    return s, (+1 if dev < 0 else -1 if dev > 0 else 0)

def score_vol(ratio):
    if ratio >= 3.0: return 25
    if ratio >= 2.0: return 20
    if ratio >= 1.5: return 15
    if ratio >= 1.2: return 10
    if ratio >= 1.0: return  5
    return 0

# ── 回测引擎 ──────────────────────────────────────────────────────
WARMUP = max(RSI_PERIOD + 1, EMA_LONG + 1, BB_PERIOD) + VOL_PERIOD

def run_backtest(candles):
    trades   = []
    position = None

    closes  = [c['close']  for c in candles]
    volumes = [c['volume'] for c in candles]

    # 按日期分组（VWAP每日重置用）
    by_date = defaultdict(list)
    for c in candles:
        by_date[datetime.utcfromtimestamp(c['time']).date()].append(c)

    print(f"预热期: {WARMUP} 根K线，开始回测...")

    for i in range(WARMUP, len(candles)):
        c     = candles[i]
        price = c['close']
        dt    = datetime.utcfromtimestamp(c['time'])
        today = dt.date()

        # ── 日内强制平仓（睡前清仓）────────────────────────────
        if position and dt.hour >= EOD_HOUR_UTC:
            ep  = position['entry']
            ret = (price - ep) / ep if position['dir'] == 'BUY' else (ep - price) / ep
            trades.append({**position, 'exit': price, 'exit_time': dt,
                           'pnl': ret, 'reason': 'EOD'})
            position = None

        # ── 持仓止损 / 止盈 ────────────────────────────────────
        if position:
            ep  = position['entry']
            hit = False
            if position['dir'] == 'BUY':
                if price <= ep * (1 - STOP_LOSS):
                    trades.append({**position, 'exit': price, 'exit_time': dt,
                                   'pnl': -STOP_LOSS, 'reason': 'SL'}); hit = True
                elif price >= ep * (1 + TAKE_PROFIT):
                    trades.append({**position, 'exit': price, 'exit_time': dt,
                                   'pnl': +TAKE_PROFIT, 'reason': 'TP'}); hit = True
            else:
                if price >= ep * (1 + STOP_LOSS):
                    trades.append({**position, 'exit': price, 'exit_time': dt,
                                   'pnl': -STOP_LOSS, 'reason': 'SL'}); hit = True
                elif price <= ep * (1 - TAKE_PROFIT):
                    trades.append({**position, 'exit': price, 'exit_time': dt,
                                   'pnl': +TAKE_PROFIT, 'reason': 'TP'}); hit = True
            if hit: position = None
            else:   continue   # 持仓中，不开新仓

        # ── 计算指标 ────────────────────────────────────────────
        cl = closes[:i+1]
        vo = volumes[:i+1]

        rsi   = calc_rsi(cl)
        bb    = calc_bb(cl)
        ema20 = calc_ema(cl, EMA_SHORT)
        ema50 = calc_ema(cl, EMA_LONG)
        volr  = calc_vol_ratio(vo)
        today_cl = [x for x in by_date[today] if x['time'] <= c['time']]
        vwap  = calc_vwap(today_cl)

        # ── 打分 ────────────────────────────────────────────────
        rs, rv = score_rsi(rsi)
        bs, bv = score_bb(bb['pct'] if bb else 0.5)
        vs, vv = score_vwap((price - vwap) / vwap * 100) if vwap else (0, 0)
        total  = rs + bs + vs + score_vol(volr)
        votes  = rv + bv + vv
        direc  = 'BUY' if votes > 0 else ('SELL' if votes < 0 else None)

        if not direc or total < SIG_THRESHOLD: continue

        # ── 风控：EMA趋势过滤（Freqtrade逻辑）──────────────────
        if direc == 'BUY'  and ema20 < ema50: continue
        if direc == 'SELL' and ema20 > ema50: continue

        # ── 开仓 ────────────────────────────────────────────────
        position = {'dir': direc, 'entry': price, 'entry_time': dt, 'score': total}

    return trades

# ── 统计输出 ──────────────────────────────────────────────────────
def print_stats(trades):
    if not trades:
        print("⚠ 无交易记录"); return

    n      = len(trades)
    wins   = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr     = len(wins) / n * 100
    aw     = sum(t['pnl'] for t in wins)   / len(wins)   * 100 if wins   else 0
    al     = sum(t['pnl'] for t in losses) / len(losses) * 100 if losses else 0
    pf     = abs(aw / al) if al else float('inf')

    eq, peak, mdd = 1.0, 1.0, 0.0
    for t in trades:
        eq *= (1 + t['pnl'])
        peak = max(peak, eq)
        mdd  = max(mdd, (peak - eq) / peak)

    sl  = sum(1 for t in trades if t['reason'] == 'SL')
    tp  = sum(1 for t in trades if t['reason'] == 'TP')
    eod = sum(1 for t in trades if t['reason'] == 'EOD')

    W = 52
    print("\n" + "═"*W)
    print("  BTC/USD 15m 均值回归策略  |  2022-2024 回测")
    print("  止损 1.5%  止盈 3.0%  日内强平 22:00 UTC")
    print("═"*W)
    print(f"  总交易次数    {n:>6}    做多 {sum(1 for t in trades if t['dir']=='BUY')}  做空 {sum(1 for t in trades if t['dir']=='SELL')}")
    print(f"  盈利 / 亏损   {len(wins):>4} / {len(losses):<4}")
    print("─"*W)
    print(f"  胜  率        {wr:>6.1f}%")
    print(f"  平均盈利      {aw:>+6.2f}%")
    print(f"  平均亏损      {al:>+6.2f}%")
    print(f"  盈 亏 比      {pf:>6.2f}x")
    print("─"*W)
    print(f"  总收益（复利）{(eq-1)*100:>+6.1f}%")
    print(f"  最大回撤      {mdd*100:>6.1f}%")
    print("─"*W)
    print(f"  止损触发      {sl:>6} 次")
    print(f"  止盈触发      {tp:>6} 次")
    print(f"  日内强平      {eod:>6} 次")
    print("─"*W)
    print(f"  {'年份':<6}{'交易':>6}{'胜率':>8}{'收益':>9}")
    for yr in [2022, 2023, 2024]:
        yt = [t for t in trades if t['entry_time'].year == yr]
        if not yt: continue
        yw  = sum(1 for t in yt if t['pnl'] > 0) / len(yt) * 100
        yr_ = 1.0
        for t in yt: yr_ *= (1 + t['pnl'])
        print(f"  {yr:<6}{len(yt):>6}{yw:>7.1f}%{(yr_-1)*100:>+8.1f}%")
    print("═"*W + "\n")

if __name__ == '__main__':
    candles = download_ohlcv()
    print(f"共 {len(candles)} 根K线  {datetime.utcfromtimestamp(candles[0]['time']).date()} → {datetime.utcfromtimestamp(candles[-1]['time']).date()}\n")
    trades = run_backtest(candles)
    print_stats(trades)

#!/usr/bin/env python3
"""
BTC/USD 均值回归策略回测  —  增量计算版（O(n)）
算法与 btc-signal-v2.html 完全一致：
  Jesse  → RSI(Wilder) / BB / EMA / VWAP(每日重置)
  Freqtrade → 信号触发逻辑 / EMA趋势风控
  市场状态 → MA200 ±3% 判定牛熊震荡

注：因无法访问外网，数据使用 GBM 模型模拟，
    价格锚点基于 BTC 真实历史区间。
"""

import math, random, urllib.request, json, ssl
from datetime import datetime

# ── 配置 ──────────────────────────────────────────────────────────
MA200_PERIOD  = 200 * 96   # 200日均线（15m×96=1天）
MA200_BAND    = 0.03       # ±3% 判定带：牛市禁空 / 熊市禁多
RSI_PERIOD    = 14
BB_PERIOD     = 20
BB_STD        = 2
EMA_SHORT     = 20
EMA_LONG      = 50
VOL_PERIOD    = 20
SIG_THRESHOLD = 70
STOP_LOSS     = 0.015
TAKE_PROFIT   = 0.030
EOD_HOUR_UTC  = 22

INTERVAL_SEC  = 900    # 15分钟

# ── OKX 真实数据拉取 ──────────────────────────────────────────────
def fetch_okx_candles(inst_id="BTC-USDT", bar="15m", limit=1500):
    url = (f"https://www.okx.com/api/v5/market/history-candles"
           f"?instId={inst_id}&bar={bar}&limit={limit}")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        data = json.loads(resp.read())
    if data.get('code') != '0':
        raise RuntimeError(f"OKX API error: {data.get('msg')}")
    rows = data['data']
    rows.reverse()   # OKX 返回最新在前，翻转为时间正序
    candles = []
    for row in rows:
        candles.append({
            'time':   int(row[0]) // 1000,
            'open':   float(row[1]),
            'high':   float(row[2]),
            'low':    float(row[3]),
            'close':  float(row[4]),
            'volume': float(row[5]),
        })
    t0 = datetime.utcfromtimestamp(candles[0]['time']).strftime('%Y-%m-%d %H:%M')
    t1 = datetime.utcfromtimestamp(candles[-1]['time']).strftime('%Y-%m-%d %H:%M')
    print(f"OKX真实K线: {len(candles)} 根  {t0} → {t1} (UTC)")
    return candles

# ── 模拟数据生成 ──────────────────────────────────────────────────
# 价格锚点（基于 BTC 历史真实价格）
ANCHORS = [
    (1640995200, 47000),  # 2022-01  牛熊转折
    (1648771200, 45000),  # 2022-04
    (1656633600, 20000),  # 2022-07  崩盘后
    (1664582400, 19500),  # 2022-10
    (1672531200, 16500),  # 2023-01  底部
    (1680307200, 28000),  # 2023-04  反弹
    (1688169600, 30000),  # 2023-07
    (1696118400, 27000),  # 2023-10
    (1704067200, 43000),  # 2024-01  新牛市
    (1711929600, 71000),  # 2024-04  历史高点
    (1719792000, 58000),  # 2024-07  回调
    (1727740800, 63000),  # 2024-10
    (1735689600, 98000),  # 2025-01  新高
]

def generate_candles():
    random.seed(42)
    candles = []
    bar_vol = 0.030 / math.sqrt(96)  # 日波动3%，换算15m

    for i in range(len(ANCHORS) - 1):
        t0, p0 = ANCHORS[i]
        t1, p1 = ANCHORS[i + 1]
        n = (t1 - t0) // INTERVAL_SEC
        drift = math.log(p1 / p0) / n
        price = p0

        for k in range(n):
            close = price * math.exp(drift + bar_vol * random.gauss(0, 1))
            amp   = price * bar_vol * abs(random.gauss(0.8, 0.4))
            high  = close + amp * random.uniform(0.2, 1.0)
            low   = close - amp * random.uniform(0.2, 1.0)
            vol   = random.lognormvariate(3.0, 0.8) * (random.uniform(2,5) if random.random()<0.05 else 1)
            candles.append({
                'time': t0 + k * INTERVAL_SEC,
                'open': price, 'high': high, 'low': low, 'close': close, 'volume': vol,
            })
            price = close

    print(f"模拟K线: {len(candles)} 根  "
          f"{datetime.utcfromtimestamp(candles[0]['time']).date()} → "
          f"{datetime.utcfromtimestamp(candles[-1]['time']).date()}")
    print("价格锚点: 2022熊市($47k→$16k) | 2023复苏($16k→$43k) | 2024牛市($43k→$98k)\n")
    return candles

# ── 预计算所有指标（O(n) 增量法）─────────────────────────────────
def precompute(candles):
    n   = len(candles)
    rsi = [None] * n
    bb  = [None] * n
    e20 = [None] * n
    e50 = [None] * n
    vwr = [1.0]  * n
    vwap= [None] * n

    closes  = [c['close']  for c in candles]
    volumes = [c['volume'] for c in candles]

    # ── RSI (Jesse Wilder 平滑) ────────────────────────────────
    ag = al = 0.0
    for i in range(1, RSI_PERIOD + 1):
        d = closes[i] - closes[i-1]
        if d > 0: ag += d
        else:     al += abs(d)
    ag /= RSI_PERIOD
    al /= RSI_PERIOD
    rs = ag / al if al else 100
    rsi[RSI_PERIOD] = 100 - 100 / (1 + rs)

    for i in range(RSI_PERIOD + 1, n):
        d  = closes[i] - closes[i-1]
        ag = (ag * (RSI_PERIOD-1) + (d if d > 0 else 0))        / RSI_PERIOD
        al = (al * (RSI_PERIOD-1) + (abs(d) if d < 0 else 0))   / RSI_PERIOD
        rs = ag / al if al else 100
        rsi[i] = 100 - 100 / (1 + rs)

    # ── BB (Jesse SMA + 总体标准差) ────────────────────────────
    win_sum = sum(closes[:BB_PERIOD])
    for i in range(BB_PERIOD, n):
        if i > BB_PERIOD:
            win_sum += closes[i] - closes[i - BB_PERIOD]
        mid = win_sum / BB_PERIOD
        sl  = closes[i - BB_PERIOD + 1 : i + 1]
        std = math.sqrt(sum((x - mid)**2 for x in sl) / BB_PERIOD)
        hi, lo = mid + BB_STD*std, mid - BB_STD*std
        pct = (closes[i] - lo) / (hi - lo) if hi != lo else 0.5
        bb[i] = pct

    # ── EMA20 / EMA50 (Jesse) ──────────────────────────────────
    k20, k50 = 2/(EMA_SHORT+1), 2/(EMA_LONG+1)
    ema20 = sum(closes[:EMA_SHORT]) / EMA_SHORT
    ema50 = sum(closes[:EMA_LONG])  / EMA_LONG
    e20[EMA_SHORT - 1] = ema20
    e50[EMA_LONG  - 1] = ema50

    for i in range(EMA_SHORT, n):
        ema20 = closes[i] * k20 + ema20 * (1 - k20)
        e20[i] = ema20
    for i in range(EMA_LONG, n):
        ema50 = closes[i] * k50 + ema50 * (1 - k50)
        e50[i] = ema50

    # ── Volume Ratio ────────────────────────────────────────────
    vsum = sum(volumes[:VOL_PERIOD])
    for i in range(VOL_PERIOD, n):
        avg = vsum / VOL_PERIOD
        vwr[i] = volumes[i] / avg if avg > 0 else 1.0
        vsum += volumes[i] - volumes[i - VOL_PERIOD]

    # ── VWAP (Jesse 每日重置) ───────────────────────────────────
    cur_date = None
    cum_vp = cum_v = 0.0
    for i, c in enumerate(candles):
        d = datetime.utcfromtimestamp(c['time']).date()
        if d != cur_date:
            cum_vp = cum_v = 0.0
            cur_date = d
        tp = (c['high'] + c['low'] + c['close']) / 3
        cum_vp += tp * c['volume']
        cum_v  += c['volume']
        vwap[i] = cum_vp / cum_v if cum_v > 0 else None

    # ── MA200 (200日均线，用于牛熊判断) ─────────────────────────
    MA_P  = MA200_PERIOD
    ma200 = [None] * n
    if n >= MA_P:
        ma_sum = sum(closes[:MA_P])
        ma200[MA_P - 1] = ma_sum / MA_P
        for i in range(MA_P, n):
            ma_sum += closes[i] - closes[i - MA_P]
            ma200[i] = ma_sum / MA_P

    return rsi, bb, e20, e50, vwr, vwap, ma200

# ── 打分系统（Freqtrade信号逻辑）─────────────────────────────────
def score_rsi(v):
    if v is None: return 0, 0
    if v <= 20: return 25, +1
    if v <= 30: return 20, +1
    if v <= 38: return 10, +1
    if v <= 45: return  4, +1
    if v <  55: return  0,  0
    if v <  62: return  4, -1
    if v <  70: return 10, -1
    if v <  80: return 20, -1
    return 25, -1

def score_bb(p):
    if p <= 0.00: return 25, +1
    if p <= 0.10: return 22, +1
    if p <= 0.20: return 16, +1
    if p <= 0.35: return  7, +1
    if p <= 0.65: return  0,  0
    if p <= 0.80: return  7, -1
    if p <= 0.90: return 16, -1
    if p <= 1.00: return 22, -1
    return 25, -1

def score_vwap(dev):
    a = abs(dev)
    s = 25 if a>=2.0 else 20 if a>=1.2 else 14 if a>=0.6 else 7 if a>=0.3 else 2
    return s, (+1 if dev < 0 else -1 if dev > 0 else 0)

def score_vol(r):
    if r >= 3.0: return 25
    if r >= 2.0: return 20
    if r >= 1.5: return 15
    if r >= 1.2: return 10
    if r >= 1.0: return  5
    return 0

# ── 回测引擎 ──────────────────────────────────────────────────────
WARMUP_BASE = max(RSI_PERIOD, EMA_LONG, BB_PERIOD) + VOL_PERIOD + 1  # 71根

def run_backtest(candles, rsi, bb, e20, e50, vwr, vwap, ma200):
    trades   = []
    position = None

    # 有MA200数据则从第一个有效值开始，否则用基础预热
    first_ma = next((i for i, v in enumerate(ma200) if v is not None), None)
    warmup   = max(first_ma, WARMUP_BASE) if first_ma is not None else WARMUP_BASE
    print(f"  预热期: {warmup} 根K线，开始回测...")

    for i in range(warmup, len(candles)):
        c     = candles[i]
        price = c['close']
        dt    = datetime.utcfromtimestamp(c['time'])

        # ── 日内强制平仓（EOD 模拟睡前清仓）────────────────────
        if position and dt.hour >= EOD_HOUR_UTC:
            ep  = position['entry']
            ret = (price-ep)/ep if position['dir']=='BUY' else (ep-price)/ep
            trades.append({**position, 'exit': price, 'exit_time': dt,
                           'pnl': ret, 'reason': 'EOD'})
            position = None

        # ── 持仓止损 / 止盈 ────────────────────────────────────
        if position:
            ep, hit = position['entry'], False
            if position['dir'] == 'BUY':
                if   price <= ep*(1-STOP_LOSS):   pnl, hit = -STOP_LOSS,   True
                elif price >= ep*(1+TAKE_PROFIT):  pnl, hit = +TAKE_PROFIT, True
            else:
                if   price >= ep*(1+STOP_LOSS):   pnl, hit = -STOP_LOSS,   True
                elif price <= ep*(1-TAKE_PROFIT):  pnl, hit = +TAKE_PROFIT, True
            if hit:
                reason = 'SL' if pnl < 0 else 'TP'
                trades.append({**position, 'exit': price, 'exit_time': dt,
                               'pnl': pnl, 'reason': reason})
                position = None
            else:
                continue

        # ── MA200 市场状态判断（数据不足时默认震荡市）───────────────
        ma = ma200[i]
        if ma is not None:
            ratio = price / ma
            if   ratio > 1 + MA200_BAND: mkt = 'BULL'
            elif ratio < 1 - MA200_BAND: mkt = 'BEAR'
            else:                        mkt = 'RANGING'
        else:
            mkt = 'RANGING'  # 不足200日历史，不限制方向

        # ── 评分和方向投票 ────────────────────────────────────────
        rs, rv = score_rsi(rsi[i])
        bs, bv = score_bb(bb[i] if bb[i] is not None else 0.5)
        vs, vv = score_vwap((price - vwap[i]) / vwap[i] * 100) if vwap[i] else (0, 0)
        total  = rs + bs + vs + score_vol(vwr[i])
        votes  = rv + bv + vv
        direc  = 'BUY' if votes > 0 else ('SELL' if votes < 0 else None)
        if not direc or total < SIG_THRESHOLD: continue

        # ── MA200 方向过滤 ────────────────────────────────────────
        if mkt == 'BULL' and direc == 'SELL': continue   # 牛市禁空
        if mkt == 'BEAR' and direc == 'BUY':  continue   # 熊市禁多

        # ── EMA20/50 短周期趋势风控（保留）──────────────────────
        if direc == 'BUY'  and e20[i] is not None and e20[i] < e50[i]: continue
        if direc == 'SELL' and e20[i] is not None and e20[i] > e50[i]: continue

        position = {'dir': direc, 'entry': price, 'entry_time': dt, 'mode': mkt}

    return trades

# ── 统计 ──────────────────────────────────────────────────────────
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

    eq = peak = 1.0; mdd = 0.0
    for t in trades:
        eq  *= (1 + t['pnl'])
        peak = max(peak, eq)
        mdd  = max(mdd, (peak - eq) / peak)

    sl  = sum(1 for t in trades if t['reason'] == 'SL')
    tp  = sum(1 for t in trades if t['reason'] == 'TP')
    eod = sum(1 for t in trades if t['reason'] == 'EOD')
    buys = sum(1 for t in trades if t['dir'] == 'BUY')

    W = 52
    print("═"*W)
    print("  BTC/USD 15m 均值回归策略  |  2022-2024 回测")
    print("  止损 1.5%  |  止盈 3.0%  |  日内强平 22:00 UTC")
    print("═"*W)
    print(f"  总交易次数    {n:>6}    做多 {buys}  做空 {n-buys}")
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
    print(f"  市场状态分解（MA200 ±{MA200_BAND*100:.0f}%）")
    labels = {'BULL': '牛市(禁空)', 'BEAR': '熊市(禁多)', 'RANGING': '震荡市(双向)'}
    for mkt in ['BULL', 'BEAR', 'RANGING']:
        mt = [t for t in trades if t.get('mode') == mkt]
        if not mt: continue
        mw = sum(1 for t in mt if t['pnl'] > 0)
        mr = 1.0
        for t in mt: mr *= (1 + t['pnl'])
        print(f"  {labels[mkt]:<12}{len(mt):>4}笔  胜率{mw/len(mt)*100:.0f}%  收益{(mr-1)*100:>+.1f}%")
    print("─"*W)
    print(f"  {'年月':<8}{'交易':>6}{'胜率':>8}{'收益':>9}")
    years = sorted(set(t['entry_time'].year for t in trades))
    for yr in years:
        yt = [t for t in trades if t['entry_time'].year == yr]
        if not yt: continue
        yw  = sum(1 for t in yt if t['pnl'] > 0) / len(yt) * 100
        yr_ = 1.0
        for t in yt: yr_ *= (1 + t['pnl'])
        print(f"  {yr:<6}{len(yt):>6}{yw:>7.1f}%{(yr_-1)*100:>+8.1f}%")
    print("═"*W)

# ── 主程序 ────────────────────────────────────────────────────────
if __name__ == '__main__':
    try:
        print("正在从 OKX 拉取真实K线数据...")
        candles = fetch_okx_candles(limit=1500)
    except Exception as e:
        print(f"OKX 获取失败（{e}），切换为模拟数据...\n")
        candles = generate_candles()

    print("预计算指标中（含MA200）...")
    rsi, bb, e20, e50, vwr, vwap, ma200 = precompute(candles)
    trades = run_backtest(candles, rsi, bb, e20, e50, vwr, vwap, ma200)
    print(f"完成，共 {len(trades)} 笔交易\n")
    print_stats(trades)

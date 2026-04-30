/**
 * backtest_core.mjs — 单源策略模块（ES Module，纯函数，零DOM依赖）
 * 同时被 backfill.html 和 backtest_runner.mjs 复用，不存在两套逻辑。
 */

/* ── 常量 ──────────────────────────────────────────────────── */
export const SLIPPAGE = 0.0010;
export const FEE      = 0.0026;
export const COST     = SLIPPAGE + FEE;   // 单边 0.36%
export const CFG      = { EOD_HOUR_UTC: 22, DEDUP_MINUTES: 30 };

export const PRESETS = {
  base: {
    name: '基准',
    EMA_SHORT: 20, EMA_LONG: 50,
    STOP_LOSS_PCT: 0.015, TAKE_PROFIT_PCT: 0.020,
    SIG_THRESHOLD: 70,
    ATR_SL_MULT: 1.0, ATR_TP_MULT: 1.5,
    ADX_MIN: 15, ADX_MID: 20, ADX_MID_SCORE: 80,
    ENTRY_DISTANCE_PCT: 0,
    MAX_HOLD_HOURS: 24, TIMEOUT_R_RATIO: 0.5,
    TRAIL_ACTIVATION: 0.5, TRAIL_STEP: 0.35,
  },
  A: {
    name: 'A组高胜率',
    EMA_SHORT: 20, EMA_LONG: 50,
    STOP_LOSS_PCT: 0.015, TAKE_PROFIT_PCT: 0.020,
    SIG_THRESHOLD: 78,
    ATR_SL_MULT: 1.7, ATR_TP_MULT: 1.1,
    ADX_MIN: 15, ADX_MID: 20, ADX_MID_SCORE: 80,
    ENTRY_DISTANCE_PCT: 0.0015,
    MAX_HOLD_HOURS: 24, TIMEOUT_R_RATIO: 0.5,
    TRAIL_ACTIVATION: 0.5, TRAIL_STEP: 0.35,
  },
  B: {
    name: 'B组平衡',
    EMA_SHORT: 20, EMA_LONG: 50,
    STOP_LOSS_PCT: 0.015, TAKE_PROFIT_PCT: 0.020,
    SIG_THRESHOLD: 75,
    ATR_SL_MULT: 1.6, ATR_TP_MULT: 1.3,
    ADX_MIN: 18, ADX_MID: 25, ADX_MID_SCORE: 75,
    ENTRY_DISTANCE_PCT: 0.0015,
    MAX_HOLD_HOURS: 24, TIMEOUT_R_RATIO: 0.5,
    TRAIL_ACTIVATION: 0.5, TRAIL_STEP: 0.35,
  },
  C: {
    name: 'C组保守',
    EMA_SHORT: 20, EMA_LONG: 50,
    STOP_LOSS_PCT: 0.015, TAKE_PROFIT_PCT: 0.020,
    SIG_THRESHOLD: 75,
    ATR_SL_MULT: 1.0, ATR_TP_MULT: 1.5,
    ADX_MIN: 15, ADX_MID: 20, ADX_MID_SCORE: 80,
    ENTRY_DISTANCE_PCT: 0,
    MAX_HOLD_HOURS: 24, TIMEOUT_R_RATIO: 0.5,
    TRAIL_ACTIVATION: 0.5, TRAIL_STEP: 0.35,
  },
};

/* ── 指标计算 ───────────────────────────────────────────────── */
export function calcRSI(closes, period = 14) {
  if (closes.length < period + 1) return null;
  let ag = 0, al = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    if (d > 0) ag += d; else al += Math.abs(d);
  }
  ag /= period; al /= period;
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    ag = (ag * (period - 1) + (d > 0 ? d : 0)) / period;
    al = (al * (period - 1) + (d < 0 ? Math.abs(d) : 0)) / period;
  }
  const rs = al === 0 ? 100 : ag / al;
  return 100 - 100 / (1 + rs);
}

export function calcBB(closes, period = 20, mult = 2) {
  if (closes.length < period) return null;
  const sl  = closes.slice(-period);
  const mid = sl.reduce((s, v) => s + v, 0) / period;
  const std = Math.sqrt(sl.reduce((s, v) => s + (v - mid) ** 2, 0) / period);
  const upper = mid + mult * std, lower = mid - mult * std;
  const last  = closes[closes.length - 1];
  const pct   = upper !== lower ? (last - lower) / (upper - lower) : 0.5;
  return { upper, middle: mid, lower, pct };
}

export function calcEMA(closes, period) {
  if (closes.length < period) return closes[closes.length - 1];
  const k = 2 / (period + 1);
  let ema = closes.slice(0, period).reduce((s, v) => s + v, 0) / period;
  for (let i = period; i < closes.length; i++) ema = closes[i] * k + ema * (1 - k);
  return ema;
}

// VWAP 使用 UTC 日切，Node 和浏览器行为完全一致
export function calcVWAP(candles) {
  const last       = new Date(candles[candles.length - 1].time);
  const todayStart = Date.UTC(last.getUTCFullYear(), last.getUTCMonth(), last.getUTCDate());
  let cv = 0, cv2 = 0;
  for (const c of candles) {
    if (c.time < todayStart) continue;
    const tp = (c.high + c.low + c.close) / 3;
    cv += tp * c.volume; cv2 += c.volume;
  }
  return cv2 > 0 ? cv / cv2 : null;
}

export function calcMFI(candles, period = 14) {
  if (candles.length < period + 1) return 50;
  const sl = candles.slice(-(period + 1));
  let pos = 0, neg = 0;
  for (let i = 1; i <= period; i++) {
    const tp  = (sl[i].high   + sl[i].low   + sl[i].close)   / 3;
    const tpP = (sl[i-1].high + sl[i-1].low + sl[i-1].close) / 3;
    const mf  = tp * sl[i].volume;
    if (tp > tpP) pos += mf; else if (tp < tpP) neg += mf;
  }
  return neg === 0 ? 100 : 100 - 100 / (1 + pos / neg);
}

export function calcVolRatio(volumes, period = 20) {
  if (volumes.length < period + 1) return 1;
  const avg = volumes.slice(-period - 1, -1).reduce((s, v) => s + v, 0) / period;
  return avg > 0 ? volumes[volumes.length - 1] / avg : 1;
}

export function calcADX(candles, period = 14) {
  if (candles.length < period * 2) return null;
  const trs = [], plusDMs = [], minusDMs = [];
  for (let i = 1; i < candles.length; i++) {
    const h = candles[i].high, l = candles[i].low;
    const ph = candles[i-1].high, pl = candles[i-1].low, pc = candles[i-1].close;
    trs.push(Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc)));
    const upMove = h - ph, downMove = pl - l;
    plusDMs.push(upMove > downMove && upMove > 0 ? upMove : 0);
    minusDMs.push(downMove > upMove && downMove > 0 ? downMove : 0);
  }
  const smooth = arr => {
    let s = arr.slice(0, period).reduce((a, b) => a + b, 0);
    const r = [s];
    for (let i = period; i < arr.length; i++) { s = s - s / period + arr[i]; r.push(s); }
    return r;
  };
  const sTR = smooth(trs), sPDM = smooth(plusDMs), sMDM = smooth(minusDMs);
  const DIs = sTR.map((tr, i) => ({
    plus:  tr ? 100 * sPDM[i] / tr : 0,
    minus: tr ? 100 * sMDM[i] / tr : 0,
  }));
  const DXs = DIs.map(d => { const s = d.plus + d.minus; return s ? 100 * Math.abs(d.plus - d.minus) / s : 0; });
  let adx = DXs.slice(0, period).reduce((a, b) => a + b, 0) / period;
  for (let i = period; i < DXs.length; i++) adx = (adx * (period - 1) + DXs[i]) / period;
  return { adx, plusDI: DIs[DIs.length - 1].plus, minusDI: DIs[DIs.length - 1].minus };
}

export function calcATR(candles, period = 14) {
  if (candles.length < period + 1) return null;
  const trs = [];
  for (let i = 1; i < candles.length; i++) {
    const h = candles[i].high, l = candles[i].low, pc = candles[i-1].close;
    trs.push(Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc)));
  }
  let atr = trs.slice(0, period).reduce((a, b) => a + b, 0) / period;
  for (let i = period; i < trs.length; i++) atr = (atr * (period - 1) + trs[i]) / period;
  return atr;
}

export function detectVBottom(candles) {
  if (candles.length < 6) return false;
  const avg = candles.slice(-6).map(c => (c.open + c.high + c.low + c.close) / 4);
  for (let i = 0; i < 4; i++) if (avg[i] <= avg[i + 1]) return false;
  return avg[5] > avg[4];
}

/* ── 打分系统 ───────────────────────────────────────────────── */
export function scoreRSI(v) {
  if (v === null) return { score: 0, vote: 0 };
  if (v <= 20) return { score: 25, vote: +1 }; if (v <= 30) return { score: 20, vote: +1 };
  if (v <= 38) return { score: 10, vote: +1 }; if (v <= 45) return { score: 4,  vote: +1 };
  if (v <  55) return { score: 0,  vote: 0  };
  if (v <  62) return { score: 4,  vote: -1 }; if (v <  70) return { score: 10, vote: -1 };
  if (v <  80) return { score: 20, vote: -1 }; return { score: 25, vote: -1 };
}
export function scoreBB(p) {
  if (p <= 0)   return { score: 25, vote: +1 }; if (p <= .1)  return { score: 22, vote: +1 };
  if (p <= .2)  return { score: 16, vote: +1 }; if (p <= .35) return { score: 7,  vote: +1 };
  if (p <= .65) return { score: 0,  vote: 0  };
  if (p <= .8)  return { score: 7,  vote: -1 }; if (p <= .9)  return { score: 16, vote: -1 };
  if (p <= 1.0) return { score: 22, vote: -1 }; return { score: 25, vote: -1 };
}
export function scoreVWAP(dev) {
  const a = Math.abs(dev), v = dev < 0 ? +1 : dev > 0 ? -1 : 0;
  const s = a >= 2 ? 25 : a >= 1.2 ? 20 : a >= .6 ? 14 : a >= .3 ? 7 : 2;
  return { score: s, vote: v };
}
export function scoreMFI(m) {
  if (m <= 20) return { score: 25, vote: +1 }; if (m <= 30) return { score: 20, vote: +1 };
  if (m <= 38) return { score: 10, vote: +1 }; if (m <= 45) return { score: 4,  vote: +1 };
  if (m <  55) return { score: 0,  vote: 0  };
  if (m <  62) return { score: 4,  vote: -1 }; if (m <  70) return { score: 10, vote: -1 };
  if (m <  80) return { score: 20, vote: -1 }; return { score: 25, vote: -1 };
}

/* ── 信号生成（回放模式，无消息面过滤）────────────────────────── */
export function generateSignalAt(candles, idx, cfg) {
  cfg = cfg || PRESETS.base;
  const slice   = candles.slice(0, idx + 1);
  const closes  = slice.map(c => c.close);
  const volumes = slice.map(c => c.volume);
  const last    = closes[closes.length - 1];

  const rsi  = calcRSI(closes);
  const bb   = calcBB(closes);
  const vwap = calcVWAP(slice);
  const ema20 = calcEMA(closes, cfg.EMA_SHORT);
  const ema50 = calcEMA(closes, cfg.EMA_LONG);
  const mfi  = calcMFI(slice);

  const vol30avg = volumes.length >= 31
    ? volumes.slice(-31, -1).reduce((s, v) => s + v, 0) / 30 : 0;
  if (vol30avg > 0 && volumes[volumes.length - 1] > vol30avg * 20) return null;

  const rsiR  = scoreRSI(rsi);
  const bbR   = scoreBB(bb ? bb.pct : 0.5);
  const vwapR = vwap ? scoreVWAP((last - vwap) / vwap * 100) : { score: 0, vote: 0 };
  const mfiR  = scoreMFI(mfi);
  const vBonus = detectVBottom(slice) ? 10 : 0;
  const total  = Math.min(100, rsiR.score + bbR.score + vwapR.score + mfiR.score + vBonus);

  const votes = rsiR.vote + bbR.vote + vwapR.vote + mfiR.vote;
  const dir   = votes > 0 ? 'BUY' : votes < 0 ? 'SELL' : null;
  if (!dir || total < cfg.SIG_THRESHOLD) return null;

  if (dir === 'BUY'  && ema20 < ema50) return null;
  if (dir === 'SELL' && ema20 > ema50) return null;

  const adxData = calcADX(slice);
  if (adxData && adxData.adx < cfg.ADX_MIN) return null;

  const atr = calcATR(slice);
  let stop, bbTarget;
  if (atr) {
    const slDist = Math.min(Math.max(atr * cfg.ATR_SL_MULT, last * 0.008), last * 0.03);
    const tpDist = slDist * (cfg.ATR_TP_MULT / cfg.ATR_SL_MULT);
    stop     = dir === 'BUY' ? last - slDist : last + slDist;
    bbTarget = dir === 'BUY' ? last + tpDist : last - tpDist;
  } else {
    stop     = dir === 'BUY' ? last * (1 - cfg.STOP_LOSS_PCT) : last * (1 + cfg.STOP_LOSS_PCT);
    bbTarget = dir === 'BUY' ? last * (1 + cfg.TAKE_PROFIT_PCT) : last * (1 - cfg.TAKE_PROFIT_PCT);
  }

  return {
    direction: dir,
    score:     total,
    price:     last,
    stop,
    bbTarget,
    strength:  total >= 85 ? '强信号' : '弱信号',
    rsi:       rsi  ? rsi.toFixed(1)          : '--',
    bbPct:     bb   ? (bb.pct * 100).toFixed(1) + '%' : '--',
    emaTrend:  ema20 > ema50 ? '多头' : '空头',
  };
}

/* ── 胜负判定：跟踪止损 ─────────────────────────────────────── */
/*
 * R 定义（双边成本完全统一）：
 *   effEntry  = entry * (1±COST)        — 入场含成本
 *   effInitSL = initSL * (1∓COST)       — 止损含出场成本
 *   R         = |effEntry - effInitSL|  — 固定单位，全程不变
 *
 * trailStop / highWater：市场价（直接与OHLC比较）
 * pnlR 计算：exit 时对称扣成本，不多不少
 * 单调性约束：trailStop 做多只能上移，做空只能下移
 */
export function judgeOutcome(entryTs, direction, entry, sl, tp, candles, cfg) {
  const isBuy = direction === 'BUY';
  const TRAIL_ACTIVATION = cfg.TRAIL_ACTIVATION ?? 0.5;
  const TRAIL_STEP       = cfg.TRAIL_STEP       ?? 0.35;

  const effEntry = isBuy ? entry * (1 + COST) : entry * (1 - COST);

  const maxSLDist = entry * 0.012;
  const slDist    = Math.min(Math.abs(entry - sl), maxSLDist);
  const initSL    = isBuy ? entry - slDist : entry + slDist;

  const effInitSL = isBuy ? initSL * (1 - COST) : initSL * (1 + COST);
  const R         = Math.abs(effEntry - effInitSL);
  if (R === 0) return { status: 'DRAW', pnlR: 0, closePrice: entry, closeTs: entryTs };

  let trailStop  = initSL;
  let highWater  = entry;
  let trailActive = false;

  const future = candles.filter(c => c.time > entryTs).slice(0, cfg.MAX_HOLD_HOURS * 4);

  for (const c of future) {
    if (isBuy) {
      if (c.low <= trailStop) {
        const exitEff = trailStop * (1 - COST);
        const pnlR    = (exitEff - effEntry) / R;
        return { status: pnlR >= 0 ? 'WIN' : 'LOSS', pnlR, closePrice: trailStop, closeTs: c.time };
      }
      if (c.high > highWater) highWater = c.high;
      const profit = (highWater * (1 - COST) - effEntry) / R;
      if (!trailActive && profit >= TRAIL_ACTIVATION) {
        trailActive = true;
        const initPush = entry - 0.2 * R;
        if (initPush > trailStop) trailStop = initPush;
      }
      if (trailActive) {
        const newStop = highWater - TRAIL_STEP * R;
        if (newStop > trailStop) trailStop = newStop;
      }
    } else {
      if (c.high >= trailStop) {
        const exitEff = trailStop * (1 + COST);
        const pnlR    = (effEntry - exitEff) / R;
        return { status: pnlR >= 0 ? 'WIN' : 'LOSS', pnlR, closePrice: trailStop, closeTs: c.time };
      }
      if (c.low < highWater) highWater = c.low;
      const profit = (effEntry - highWater * (1 + COST)) / R;
      if (!trailActive && profit >= TRAIL_ACTIVATION) {
        trailActive = true;
        const initPush = entry + 0.2 * R;
        if (initPush < trailStop) trailStop = initPush;
      }
      if (trailActive) {
        const newStop = highWater + TRAIL_STEP * R;
        if (newStop < trailStop) trailStop = newStop;
      }
    }
  }

  const lastPrice = future.length > 0 ? future[future.length - 1].close : entry;
  const exitEff   = isBuy ? lastPrice * (1 - COST) : lastPrice * (1 + COST);
  const pnlR      = isBuy ? (exitEff - effEntry) / R : (effEntry - exitEff) / R;
  const status    = pnlR >= cfg.TIMEOUT_R_RATIO ? 'WIN' : pnlR <= -cfg.TIMEOUT_R_RATIO ? 'LOSS' : 'DRAW';
  return { status, pnlR, closePrice: lastPrice, closeTs: entryTs + cfg.MAX_HOLD_HOURS * 3600 * 1000 };
}

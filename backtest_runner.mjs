/**
 * backtest_runner.mjs — Node.js 90天回测跑手
 * 复用 backtest_core.mjs，不重写任何策略逻辑。
 * 需要 Node.js 18+（内置 fetch）。
 * 用法：node backtest_runner.mjs [presetKey] [days]
 *   presetKey: base | A | B | C  (默认 base)
 *   days:      回测天数           (默认 90)
 */

import {
  PRESETS, CFG, COST, SLIPPAGE, FEE,
  generateSignalAt, judgeOutcome,
} from './backtest_core.mjs';

/* ── CLI 参数 ─────────────────────────────────────────────── */
const presetKey = process.argv[2] || 'base';
const DAYS      = parseInt(process.argv[3] || '90');

if (!PRESETS[presetKey]) {
  console.error(`未知参数组 "${presetKey}"，可用: ${Object.keys(PRESETS).join(', ')}`);
  process.exit(1);
}
const cfg = PRESETS[presetKey];

/* ── OKX K线拉取 ──────────────────────────────────────────── */
async function fetchAllCandles(days) {
  const endTime   = Date.now();
  const startTime = endTime - days * 86400 * 1000;
  const LIMIT     = 100;
  const STEP      = LIMIT * 15 * 60 * 1000;
  let   all       = [];
  let   winStart  = startTime;

  process.stdout.write(`正在拉取 OKX 15m K线（过去 ${days} 天）`);

  while (winStart < endTime) {
    const winEnd = Math.min(winStart + STEP, endTime);
    const url    = `https://www.okx.com/api/v5/market/history-candles?instId=BTC-USDT&bar=15m&limit=${LIMIT}&after=${winEnd}&before=${winStart}`;
    const resp   = await fetch(url);
    if (!resp.ok) throw new Error(`OKX HTTP ${resp.status}`);
    const json   = await resp.json();
    if (json.data && json.data.length) {
      all = all.concat(json.data.map(c => ({
        time:   parseInt(c[0]),
        open:   parseFloat(c[1]),
        high:   parseFloat(c[2]),
        low:    parseFloat(c[3]),
        close:  parseFloat(c[4]),
        volume: parseFloat(c[5]),
      })));
      process.stdout.write('.');
    }
    winStart = winEnd + 1;
    await new Promise(r => setTimeout(r, 300));
  }

  const seen = new Set();
  all = all.filter(c => seen.has(c.time) ? false : seen.add(c.time));
  all.sort((a, b) => a.time - b.time);
  console.log(`\n数据拉取完成：${all.length} 根 K线\n`);
  return all;
}

/* ── 主回测逻辑 ───────────────────────────────────────────── */
async function run() {
  console.log('═'.repeat(56));
  console.log(`BTC 跟踪止损回测  参数组: [${cfg.name}]  回测: ${DAYS}天`);
  console.log(`成本: 滑点${(SLIPPAGE*100).toFixed(2)}% + 手续费${(FEE*100).toFixed(2)}% = ${(COST*100).toFixed(2)}%`);
  console.log(`跟踪: 激活=${cfg.TRAIL_ACTIVATION}R  步长=${cfg.TRAIL_STEP}R  信号阈值=${cfg.SIG_THRESHOLD}`);
  console.log('═'.repeat(56));

  const candles = await fetchAllCandles(DAYS);

  const WARMUP  = 71;   // RSI=14, EMA=50, BB=20, MFI=14, VOL=20 → 71根
  const DEDUP_MS = CFG.DEDUP_MINUTES * 60 * 1000;

  let lastSigTs = { BUY: 0, SELL: 0 };
  let sigCount  = 0;
  const results = [];

  for (let i = WARMUP; i < candles.length - 1; i++) {
    const sig = generateSignalAt(candles, i, cfg);
    if (!sig) continue;

    const ts = candles[i].time;
    if (ts - lastSigTs[sig.direction] < DEDUP_MS) continue;
    lastSigTs[sig.direction] = ts;

    const res = judgeOutcome(ts, sig.direction, sig.price, sig.stop, sig.bbTarget, candles, cfg);
    sigCount++;

    const time = new Date(ts).toISOString().slice(0, 16).replace('T', ' ');
    const icon = res.status === 'WIN' ? '✓' : res.status === 'LOSS' ? '✗' : '⏸';
    console.log(`[${time}] ${sig.direction.padEnd(4)} @${sig.price.toFixed(0).padStart(6)} 分:${sig.score} → ${icon} ${res.status.padEnd(4)}  (${res.pnlR >= 0 ? '+' : ''}${res.pnlR.toFixed(2)}R)`);

    results.push({ ts, direction: sig.direction, score: sig.score, price: sig.price, pnlR: res.pnlR, status: res.status });
  }

  /* ── 统计 ─────────────────────────────────────────────── */
  const wins    = results.filter(r => r.status === 'WIN');
  const losses  = results.filter(r => r.status === 'LOSS');
  const draws   = results.filter(r => r.status === 'DRAW');
  const total   = wins.length + losses.length;   // 有效样本
  const wr      = total > 0 ? wins.length / total : 0;

  const avgWinR  = wins.length   > 0 ? wins.reduce((s,r)=>s+r.pnlR,0)              / wins.length   : 0;
  const avgLossR = losses.length > 0 ? losses.reduce((s,r)=>s+Math.abs(r.pnlR),0) / losses.length  : 0;
  const maxWinR  = wins.length   > 0 ? Math.max(...wins.map(r=>r.pnlR))            : 0;
  const maxLossR = losses.length > 0 ? Math.max(...losses.map(r=>Math.abs(r.pnlR))): 0;
  const ev       = total > 0 ? wr * avgWinR - (1 - wr) * avgLossR : null;

  console.log('\n' + '─'.repeat(56));
  console.log(`回测完成 [${cfg.name}]：共 ${sigCount} 笔信号`);
  console.log(`总信号: ${sigCount}   WIN: ${wins.length}   LOSS: ${losses.length}   DRAW: ${draws.length}`);
  console.log(`有效样本（WIN+LOSS）: ${total}${total < 20 ? '  ⚠️  样本不足，结果仅供参考' : ''}`);
  console.log(`胜率: ${total > 0 ? (wr*100).toFixed(1) : '--'}%   (仅计WIN+LOSS)`);
  console.log(`平均盈利R: +${avgWinR.toFixed(3)}   平均亏损R: -${avgLossR.toFixed(3)}`);
  console.log(`期望值: ${ev != null ? (ev >= 0 ? '+' : '') + ev.toFixed(3) : '--'} R   ${ev != null ? (ev > 0 ? '✅ 正期望' : '❌ 负期望') : ''}`);
  console.log(`最大单笔盈利R: +${maxWinR.toFixed(3)}`);
  console.log(`最大单笔亏损R: -${maxLossR.toFixed(3)}${maxLossR > 1.1 ? '  ⚠️  超过1.1R，检查SL宽度' : '  ✓'}`);
  console.log('─'.repeat(56));
}

run().catch(e => {
  console.error('致命错误:', e.message);
  process.exit(1);
});

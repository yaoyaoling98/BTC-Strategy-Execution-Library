# BTC量化信号系统 — 项目规范

## 核心策略哲学

> 市场大部分时间是平庸的，平庸时用均值回归积累，
> 牛熊来临时切换趋势跟随抓大行情，
> 系统要能自动识别市场状态并切换策略。

这条哲学决定了系统的架构方向：
- **震荡市**（EMA平行、BB带窄）→ 均值回归策略，当前已实现
- **趋势市**（EMA发散、BB带宽扩张）→ 趋势跟随策略，待开发
- **切换逻辑**：由市场状态检测模块自动判断，不依赖人工干预

---

## 项目说明

BTC/USD 均值回归信号系统，接入 Kraken 公开 API，纯前端单文件，无需服务器。

**正式版文件：** `btc-signal-v2.html`  
**开发历史：** btc-signal.html（Step 1-4A 测试版）→ btc-signal-v2.html（正式版）

---

## 算法来源

| 指标 | 来源 | 说明 |
|------|------|------|
| RSI (Wilder平滑) | Jesse | `jesse/indicators/rsi.py` |
| 布林带 (SMA±2σ) | Jesse | `jesse/indicators/bollinger_bands.py` |
| EMA | Jesse | `jesse/indicators/ema.py` |
| VWAP (每日重置) | Jesse | `jesse/indicators/vwap.py` |
| 信号触发逻辑 | Freqtrade | `freqtrade/templates/sample_strategy.py` |
| MFI 资金流量指数 | ReinforcedQuickie | 替代原始成交量比率，第4评分维度 |
| V型底识别 +10分 | ReinforcedQuickie | 5根连续下跌后反弹，BUY加速确认 |
| 异常成交量屏蔽 | ClucMay72018 | 超均量20倍→拦截信号，防操纵 |
| BB中轨动态目标 | ClucMay72018 | SMA20作为出场参考，替代固定+2% |

**打分系统：** RSI 25分 + BB 25分 + VWAP 25分 + MFI 25分 = 100分（V底+10上限至100）  
**信号阈值：** ≥70分才出信号；≥85分为强信号  
**方向投票：** RSI / BB / VWAP / MFI 四指标多数决定做多或做空

---

## 开发规范

1. **改文件前先备份**：`cp btc-signal-v2.html btc-signal-v2.backup.html`
2. **大改动分块进行**：每次改动不超过200行，改完验证再继续
3. **不动算法逻辑**：UI/CSS改动不得修改任何计算函数
4. **改完必须推送**：每次改动 commit + push 到 `claude/general-work-3znly` 分支
5. **注释算法来源**：新增指标代码必须注明来源（Jesse/Freqtrade/自研）

---

## 我的交易规则

- **品种：** Kraken BTC/USD
- **策略：** 均值回归（短期3-5%偏离后反转）
- **周期：** 日内交易，**睡前必须清仓**
- **止损：** 入场价 ±1.5%（系统自动计算并提示）
- **风控：** EMA20 < EMA50 时禁止做多；EMA20 > EMA50 时禁止做空
- **消息面：** 重大新闻期间手动开启屏蔽开关

---

## 文件结构

```
btc-signal-v2.html        # ★ 正式版 — 唯一维护对象（赛博朋克UI + 完整信号引擎）
backfill.html             # 冷启动工具 — 回填90天历史信号到localStorage
backtest.py               # 策略回测脚本 — OKX数据，MA200牛熊过滤
btc-signal.html           # 历史测试版，勿删勿改
archive/                  # 归档目录（已废弃文件，勿引用）
CLAUDE.md                 # 本文件
```

> **btc-monitor.html 已废弃**，已归档至 archive/。所有功能均已整合进 btc-signal-v2.html。

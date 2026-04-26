# BTC Signal v2

**正式版：`btc-signal-v2.html`**  
v1.0 已冻结，仅做 UI 重构和 bug 修复，不加新功能。

---

## 快速开始

用浏览器直接打开 `btc-signal-v2.html`，无需服务器，无需安装任何依赖。

首次使用建议先运行 `backfill.html` 冷启动 90 天历史数据，以便胜率统计有初始样本。

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `btc-signal-v2.html` | ★ 唯一正式版 — 完整信号引擎 + UI |
| `backfill.html` | 冷启动工具 — 回填历史信号至 localStorage |
| `backtest.py` | 策略回测脚本 — 拉取 OKX 数据，MA200 牛熊过滤 |
| `CLAUDE.md` | 项目规范（AI 开发指引） |
| `archive/` | 已废弃文件（勿引用） |

---

## 信号引擎

**打分系统：** RSI 25 + BB 25 + VWAP 25 + MFI 25 = 100分  
**信号阈值：** ≥ 70 出信号 · ≥ 85 强信号  
**V型底加分：** +10（上限 100）  
**风控层：** EMA20/50 趋势过滤 + 异常成交量硬屏蔽  

---

## 交易规则

- 品种：Kraken BTC/USD
- 策略：均值回归（短期 3-5% 偏离后反转）
- 周期：日内，睡前清仓
- 止损：±1.5%　目标：BB 中轨（SMA20）

---

## 算法来源

| 指标 | 来源 |
|------|------|
| RSI (Wilder) | Jesse |
| 布林带 | Jesse |
| EMA | Jesse |
| VWAP (每日重置) | Jesse |
| 信号触发结构 | Freqtrade |
| MFI 资金流量指数 | ReinforcedQuickie |
| V型底识别 | ReinforcedQuickie |
| 异常量屏蔽 | ClucMay72018 |
| BB中轨出场目标 | ClucMay72018 |

---

## 版本记录

| 版本 | 说明 |
|------|------|
| v1.0 | 首个稳定版（冻结），TradingView Pro 风 UI，6项核心功能锁定 |

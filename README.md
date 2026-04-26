# BTC Signal v2

![version](https://img.shields.io/badge/version-v1.0-2962ff?style=flat-square)
![status](https://img.shields.io/badge/status-stable-26a69a?style=flat-square)
![license](https://img.shields.io/badge/license-MIT-787b86?style=flat-square)

**正式版：`btc-signal-v2.html`** — 浏览器直开，无需服务器，无需安装。  
**v1.0 已冻结**：仅接受 UI 修复和 bug 修复，不加新功能。

---

## 快速开始

```bash
# 直接用浏览器打开，无需任何依赖
open btc-signal-v2.html
```

首次使用建议先运行 `backfill.html`，冷启动 90 天历史信号，让胜率统计有初始样本。

---

## v1.0 功能清单（已锁定）

| # | 功能 | 说明 |
|---|------|------|
| 1 | **四维打分引擎** | RSI 25 + BB 25 + VWAP 25 + MFI 25 = 100分 |
| 2 | **V型底识别** | 5根连续下跌后反弹 → +10分加成，上限100 |
| 3 | **异常成交量屏蔽** | 超30期均量20倍 → 拦截信号，防操纵 |
| 4 | **BB中轨动态目标** | SMA20 作为出场参考，替代固定 +2% |
| 5 | **WIN/LOSS 自动结算** | 每5s扫描持仓，触达 TP/SL 自动记录结果 |
| 6 | **双速刷新** | 5s Ticker（实时价格）+ 30s OHLC（信号计算）|

---

## UI 设计规范（TradingView Pro 风）

```
--bg-primary:    #0a0a0a   主背景
--bg-elevated:   #131722   卡片背景（TradingView 同款）
--accent:        #2962ff   唯一强调色（蓝）
--green:         #26a69a   做多 / 盈
--red:           #ef5350   做空 / 亏
--yellow:        #ffb74d   警告 / 拦截

字体: JetBrains Mono（数字）+ Inter（文字）
布局: 3栏 grid — 指标列 | 信号卡 | 历史列
```

---

## 已知限制

- 单币种：仅 Kraken BTC/USD
- 无后端：数据来自浏览器直连 Kraken 公开 API
- 胜率统计需累积样本：建议先用 `backfill.html` 冷启动
- 历史最多保留 50 条（localStorage 限制）

---

## 后续路线图

| 版本 | 计划功能 |
|------|---------|
| v1.1 | Telegram 推送（信号触发自动通知） |
| v1.2 | 多币种支持（ETH/SOL/BNB） |
| v2.0 | 趋势跟随策略（EMA发散 + BB带宽扩张切换） |

---

## 文件结构

```
btc-signal-v2.html   ★ 唯一正式版
backfill.html          冷启动工具
backtest.py            策略回测（OKX 数据 + MA200 过滤）
CLAUDE.md              项目规范（AI 开发指引）
archive/               已废弃文件（勿引用）
```

---

## 算法来源

| 指标 | 来源 |
|------|------|
| RSI (Wilder) | Jesse |
| 布林带 SMA±2σ | Jesse |
| EMA | Jesse |
| VWAP 每日重置 | Jesse |
| 信号触发结构 | Freqtrade |
| MFI 资金流量指数 | ReinforcedQuickie |
| V型底识别 | ReinforcedQuickie |
| 异常量屏蔽 | ClucMay72018 |
| BB中轨出场目标 | ClucMay72018 |

---

## 版本记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-04-26 | 首个稳定版，TradingView Pro 风 UI，6项核心功能 |

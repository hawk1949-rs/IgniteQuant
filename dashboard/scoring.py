# -*- coding: utf-8 -*-
"""回测表现打分与自动复盘建议。"""

from __future__ import annotations

from typing import Any


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def score_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """综合打分 0–100，并给出分项与复盘建议。

    家庭作坊默认权重：收益 25 / 回撤 25 / 夏普 20 / 胜率与盈亏比 20 / 样本量 10。
    """
    ror = float(metrics.get("ror") or 0.0)  # 区间收益率，小数
    annual = float(metrics.get("annual_yield") or 0.0)
    max_dd = abs(float(metrics.get("max_drawdown") or 0.0))
    sharpe = float(metrics.get("sharpe") or 0.0)
    win_rate = float(metrics.get("winning_rate") or 0.0)
    pl_ratio = float(metrics.get("profit_loss_ratio") or 0.0)
    trades = int(metrics.get("trade_count") or 0)

    # 分项（0–100）
    ret_score = _clip((ror / 0.10) * 100, 0, 100)  # 区间约 10% 拉满
    if annual and not ror:
        ret_score = _clip((annual / 0.20) * 100, 0, 100)

    dd_score = _clip((1.0 - max_dd / 0.15) * 100, 0, 100)  # 回撤 15% 打到 0
    sharpe_score = _clip(((sharpe + 0.5) / 2.0) * 100, 0, 100)  # -0.5→0，1.5→100
    edge_score = _clip(win_rate * 50 + _clip(pl_ratio / 2.0, 0, 1) * 50, 0, 100)
    sample_score = _clip(trades / 30 * 100, 0, 100)  # 约 30 笔以上较可信

    total = (
        ret_score * 0.25
        + dd_score * 0.25
        + sharpe_score * 0.20
        + edge_score * 0.20
        + sample_score * 0.10
    )
    total = round(total, 1)

    if total >= 80:
        grade = "A"
        label = "优秀"
    elif total >= 65:
        grade = "B"
        label = "良好"
    elif total >= 50:
        grade = "C"
        label = "一般"
    elif total >= 35:
        grade = "D"
        label = "偏弱"
    else:
        grade = "E"
        label = "较差"

    tips: list[str] = []
    if max_dd > 0.08:
        tips.append("回撤偏大：可收紧 ATR 止损倍数，或降低 LOT_SCALE / 仅强信号开仓。")
    if sharpe < 0.3:
        tips.append("夏普偏低：检查 RANGE 过滤是否生效，减少震荡市交易。")
    if win_rate < 0.4 and pl_ratio < 1.2:
        tips.append("胜率与盈亏比双弱：优先复盘止损触发是否过密，或信号冲突降权是否不足。")
    if trades < 10:
        tips.append("样本过少：拉长回测区间或换更多品种交叉验证，避免过拟合结论。")
    if ror <= 0:
        tips.append("区间收益为负：先对比同区间被动持有/仅趋势过滤版本，确认 alpha 来源。")
    if not tips:
        tips.append("结构尚可：建议做多品种、多区间稳健性检查，再考虑放大手数。")

    # 「优化回测性能」工程侧建议（跑得更快）
    perf_tips = [
        "批量对比时关闭 web_gui，避免 UI 保活占用事件循环。",
        "看板 runner 默认不写桌面 Excel；需要明细时再开 ENABLE_ARCHIVE。",
        "短区间试参 → 选定参数后再跑长区间，减少无效全量回测。",
    ]

    return {
        "score": total,
        "grade": grade,
        "label": label,
        "parts": {
            "return": round(ret_score, 1),
            "drawdown": round(dd_score, 1),
            "sharpe": round(sharpe_score, 1),
            "edge": round(edge_score, 1),
            "sample": round(sample_score, 1),
        },
        "review_tips": tips,
        "perf_tips": perf_tips,
    }

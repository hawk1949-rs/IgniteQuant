#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""IgniteQuant 家庭量化作坊 · 策略看板

启动：
    streamlit run dashboard/app.py --server.port 8501
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from dashboard.catalog import ENGINES, STRATEGIES, SYMBOLS
from dashboard.runners import run_falcon_local, run_falcon_v2, run_vwap_stub
from dashboard.scoring import score_metrics
from dashboard.store import delete_run, list_runs, save_run, update_run

RUNNERS = {
    "run_falcon_v2": run_falcon_v2,
    "run_falcon_local": run_falcon_local,
    "run_vwap_stub": run_vwap_stub,
}

st.set_page_config(
    page_title="IgniteQuant 策略看板",
    page_icon="◎",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": None,
        "Report a bug": None,
        "About": "IgniteQuant · 家庭量化作坊策略看板",
    },
)

# Apple HIG 取向：浅色、语义蓝、卡片分区、弱化 Streamlit 壳
st.markdown(
    """
<style>
  html, body, [data-testid="stAppViewContainer"] {
    background: #f5f5f7 !important;
    color: #1d1d1f !important;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI",
      "PingFang SC", "Microsoft YaHei", sans-serif !important;
  }
  [data-testid="stHeader"] {
    background: rgba(245,245,247,0.85) !important;
    backdrop-filter: saturate(180%) blur(12px);
  }
  .stAppDeployButton, [data-testid="stToolbar"] button[kind="header"],
  [data-testid="stDecoration"] { display: none !important; }
  #MainMenu { visibility: hidden; }
  footer { visibility: hidden; }

  [data-testid="stSidebar"] {
    background: #ffffff !important;
    border-right: 1px solid #d2d2d7;
  }
  [data-testid="stSidebar"] * { color: #1d1d1f !important; }

  .block-container {
    padding-top: 2rem !important;
    padding-bottom: 3rem !important;
    max-width: 980px !important;
  }

  h1 {
    font-size: 1.75rem !important;
    font-weight: 700 !important;
    letter-spacing: -0.02em !important;
    color: #1d1d1f !important;
    margin-bottom: 0.35rem !important;
  }
  .iq-sub {
    color: #6e6e73;
    font-size: 0.95rem;
    line-height: 1.45;
    margin: 0 0 1.25rem 0;
  }
  .iq-card {
    background: #ffffff;
    border: 1px solid #d2d2d7;
    border-radius: 16px;
    padding: 1.1rem 1.25rem 1.25rem;
    margin-bottom: 1rem;
  }
  .iq-card-title {
    font-size: 0.8rem;
    font-weight: 600;
    color: #6e6e73;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-bottom: 0.85rem;
  }
  .iq-hint {
    color: #6e6e73;
    font-size: 0.85rem;
    line-height: 1.4;
    margin: 0.5rem 0 0;
  }
  .iq-brand {
    font-size: 1.15rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    margin: 0.2rem 0 0;
  }
  .iq-brand-sub {
    color: #6e6e73;
    font-size: 0.8rem;
    margin: 0.15rem 0 1rem;
  }
  .iq-nav-label {
    font-size: 0.75rem;
    font-weight: 600;
    color: #86868b;
    margin-bottom: 0.35rem;
  }

  div[data-testid="stMetric"] {
    background: #f5f5f7;
    border: 1px solid #e8e8ed;
    border-radius: 14px;
    padding: 0.85rem 1rem;
  }
  div[data-testid="stMetric"] label { color: #6e6e73 !important; }
  div[data-testid="stMetric"] [data-testid="stMetricValue"] {
    color: #1d1d1f !important;
    font-weight: 600 !important;
  }

  /* 主按钮：语义蓝，不用默认红 */
  .stButton > button[kind="primary"],
  div[data-testid="stBaseButton-primary"] {
    background: #0071e3 !important;
    border: none !important;
    color: #fff !important;
    border-radius: 980px !important;
    font-weight: 600 !important;
    min-height: 2.6rem !important;
    padding: 0 1.4rem !important;
  }
  .stButton > button[kind="primary"]:hover {
    background: #0077ed !important;
  }
  .stButton > button[kind="secondary"],
  .stButton > button:not([kind="primary"]) {
    background: #ffffff !important;
    border: 1px solid #d2d2d7 !important;
    color: #1d1d1f !important;
    border-radius: 980px !important;
  }
  /* 危险操作 */
  .iq-danger button {
    border-color: #ff3b30 !important;
    color: #ff3b30 !important;
  }

  [data-baseweb="select"] > div,
  [data-baseweb="input"] > div,
  .stMultiSelect [data-baseweb="select"] > div {
    border-radius: 12px !important;
    border-color: #d2d2d7 !important;
    background: #fff !important;
  }
  /* 多选芯片：描边 + 字重，不只靠颜色 */
  span[data-baseweb="tag"] {
    background: #e8f1fc !important;
    color: #0071e3 !important;
    border: 1px solid #0071e3 !important;
    border-radius: 980px !important;
    font-weight: 600 !important;
  }

  .stProgress > div > div > div > div {
    background: #0071e3 !important;
  }
</style>
""",
    unsafe_allow_html=True,
)


def _fmt_pct(x) -> str:
    if x is None:
        return "—"
    try:
        return f"{float(x) * 100:.2f}%"
    except Exception:
        return "—"


def _fmt_num(x, digits=2) -> str:
    if x is None:
        return "—"
    try:
        return f"{float(x):.{digits}f}"
    except Exception:
        return "—"


def _money(x: float) -> str:
    return f"{x:,.0f}"


def page_run() -> None:
    st.markdown("# 跑回测")
    st.markdown(
        '<p class="iq-sub">选策略与品种，结果入库后可在「对比与打分」里横向复盘。'
        "批量模式关闭天勤 Web UI，跑得更快。</p>",
        unsafe_allow_html=True,
    )

    st.markdown('<div class="iq-card">', unsafe_allow_html=True)
    st.markdown('<div class="iq-card-title">回测配置</div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        strategy_id = st.selectbox(
            "策略",
            options=list(STRATEGIES.keys()),
            format_func=lambda k: STRATEGIES[k].name,
        )
        st.caption(STRATEGIES[strategy_id].description)
    with c2:
        symbol_ids = st.multiselect(
            "标的",
            options=list(SYMBOLS.keys()),
            default=["au"],
            format_func=lambda k: SYMBOLS[k].name,
            help="可多选排队回测；合约为对应主力连续。",
        )
        if symbol_ids:
            st.caption(
                " · ".join(f"{SYMBOLS[s].name} `{SYMBOLS[s].signal_symbol}`" for s in symbol_ids)
            )

    d1, d2, d3, d4 = st.columns(4)
    with d1:
        start = st.date_input("开始", value=dt.date(2025, 1, 1))
    with d2:
        end = st.date_input("结束", value=dt.date(2025, 2, 28))
    with d3:
        init_balance = st.number_input(
            "初始资金（元）",
            min_value=100_000,
            value=1_000_000,
            step=100_000,
            format="%d",
        )
        st.caption(f"约 {_money(float(init_balance))} 元")
    with d4:
        engine = st.selectbox(
            "引擎",
            options=list(ENGINES.keys()),
            format_func=lambda k: ENGINES[k],
            index=0,
        )

    st.markdown(
        '<p class="iq-hint">默认本地缓存回放（快）；天勤在线用于最终对照。缺缓存时 local 会尝试自动下载。</p>',
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    run = st.button("开始回测", type="primary", disabled=not symbol_ids, use_container_width=False)
    if not run:
        return
    if end <= start:
        st.error("结束日期必须晚于开始日期。")
        return

    strat = STRATEGIES[strategy_id]
    if engine == "local" and strat.runner == "run_falcon_v2":
        runner = RUNNERS["run_falcon_local"]
    else:
        runner = RUNNERS[strat.runner]
    progress = st.progress(0.0, text="准备中…")
    status = st.empty()
    results = []
    n = len(symbol_ids)
    for i, sid in enumerate(symbol_ids):
        sym = SYMBOLS[sid]
        status.info(f"正在计算 {strat.name} × {sym.name}（{i + 1}/{n} · {engine}）")

        def cb(p, msg, _i=i, _n=n, _name=sym.name):
            progress.progress(min((_i + p) / _n, 1.0), text=f"{_name} · {msg}")

        try:
            kwargs = {
                "signal_symbol": sym.signal_symbol,
                "start": start,
                "end": end,
                "init_balance": float(init_balance),
                "progress_cb": cb,
            }
            if engine == "local" and strat.runner == "run_falcon_v2":
                kwargs["auto_download"] = True
            out = runner(**kwargs)
        except NotImplementedError as e:
            st.warning(str(e))
            continue
        except Exception as e:
            st.error(f"{sym.name} 失败：{e}")
            continue

        scored = score_metrics(out.get("metrics") or {})
        record = {
            **out,
            "strategy_name": strat.name,
            "symbol_id": sid,
            "symbol_name": sym.name,
            "scorecard": scored,
            "notes": "",
        }
        path = save_run(record)
        results.append(record)
        st.success(
            f"{sym.name} 完成 · {scored['score']} 分（{scored['grade']}）· "
            f"{out.get('elapsed_sec')}s · {path.name}"
        )

    progress.progress(1.0, text="全部完成")
    status.empty()
    if results:
        st.session_state["last_runs"] = [r["run_id"] for r in results]
        st.info("可到侧栏「对比与打分」查看详情。")


def page_compare() -> None:
    st.markdown("# 对比与打分")
    st.markdown(
        '<p class="iq-sub">并排查看历史回测，结合自动建议写复盘笔记。</p>',
        unsafe_allow_html=True,
    )

    runs = list_runs()
    if not runs:
        st.info("还没有回测记录。请先在「跑回测」生成。")
        return

    st.markdown('<div class="iq-card">', unsafe_allow_html=True)
    st.markdown('<div class="iq-card-title">结果一览</div>', unsafe_allow_html=True)
    df = pd.DataFrame(
        [
            {
                "run_id": r.get("run_id"),
                "策略": r.get("strategy_name") or r.get("strategy_id"),
                "标的": r.get("symbol_name") or r.get("signal_symbol"),
                "区间": f"{r.get('start')} ~ {r.get('end')}",
                "收益": _fmt_pct((r.get("metrics") or {}).get("ror")),
                "年化": _fmt_pct((r.get("metrics") or {}).get("annual_yield")),
                "最大回撤": _fmt_pct((r.get("metrics") or {}).get("max_drawdown")),
                "夏普": _fmt_num((r.get("metrics") or {}).get("sharpe")),
                "胜率": _fmt_pct((r.get("metrics") or {}).get("winning_rate")),
                "盈亏比": _fmt_num((r.get("metrics") or {}).get("profit_loss_ratio")),
                "成交": (r.get("metrics") or {}).get("trade_count"),
                "得分": (r.get("scorecard") or {}).get("score"),
                "等级": (r.get("scorecard") or {}).get("grade"),
                "耗时s": r.get("elapsed_sec"),
            }
            for r in runs
        ]
    )
    st.dataframe(df.drop(columns=["run_id"]), use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)

    ids = [r["run_id"] for r in runs if r.get("run_id")]
    pick = st.multiselect(
        "选择要展开的记录",
        options=ids,
        default=ids[: min(3, len(ids))],
        format_func=lambda rid: next(
            (
                f"{x.get('symbol_name')} · {x.get('strategy_name')} · "
                f"{(x.get('scorecard') or {}).get('score')} 分"
                for x in runs
                if x.get("run_id") == rid
            ),
            rid,
        ),
    )
    selected = [r for r in runs if r.get("run_id") in pick]

    if len(selected) >= 2:
        st.markdown('<div class="iq-card">', unsafe_allow_html=True)
        st.markdown('<div class="iq-card-title">分项对比</div>', unsafe_allow_html=True)
        chart_df = pd.DataFrame(
            {
                r.get("symbol_name")
                or r.get("run_id"): {
                    "收益": (r.get("scorecard") or {}).get("parts", {}).get("return"),
                    "回撤": (r.get("scorecard") or {}).get("parts", {}).get("drawdown"),
                    "夏普": (r.get("scorecard") or {}).get("parts", {}).get("sharpe"),
                    "边缘": (r.get("scorecard") or {}).get("parts", {}).get("edge"),
                    "样本": (r.get("scorecard") or {}).get("parts", {}).get("sample"),
                }
                for r in selected
            }
        )
        st.bar_chart(chart_df.T, color="#0071e3")
        st.markdown("</div>", unsafe_allow_html=True)

    if not selected:
        return

    st.markdown("### 复盘")
    for r in selected:
        sc = r.get("scorecard") or {}
        with st.expander(
            f"{r.get('symbol_name')} · {r.get('strategy_name')} · "
            f"{sc.get('score')} 分（{sc.get('grade')} · {sc.get('label')}）",
            expanded=len(selected) == 1,
        ):
            m1, m2, m3, m4 = st.columns(4)
            m = r.get("metrics") or {}
            m1.metric("收益", _fmt_pct(m.get("ror")))
            m2.metric("最大回撤", _fmt_pct(m.get("max_drawdown")))
            m3.metric("夏普", _fmt_num(m.get("sharpe")))
            m4.metric("胜率", _fmt_pct(m.get("winning_rate")))

            st.markdown("**策略改进**")
            for tip in sc.get("review_tips") or []:
                st.markdown(f"- {tip}")
            st.markdown("**跑得更快**")
            for tip in sc.get("perf_tips") or []:
                st.markdown(f"- {tip}")

            note = st.text_area(
                "复盘笔记",
                value=r.get("notes") or "",
                key=f"note_{r.get('run_id')}",
                height=100,
            )
            b1, b2, b3 = st.columns([1, 1, 2])
            if b1.button("保存笔记", key=f"save_{r.get('run_id')}"):
                update_run(r["run_id"], notes=note)
                st.success("已保存")
            confirm = b2.checkbox("确认删除", key=f"cfm_{r.get('run_id')}")
            if b3.button("删除记录", key=f"del_{r.get('run_id')}", disabled=not confirm):
                delete_run(r["run_id"])
                st.rerun()


def page_lab() -> None:
    st.markdown("# 作坊说明")
    st.markdown(
        '<p class="iq-sub">家庭式量化：回测对比、打分复盘、再决定是否放大。</p>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="iq-card">', unsafe_allow_html=True)
    st.markdown(
        """
**能做什么**
1. 选策略（Falcon v2；VWAP 占位）
2. 选标的：沪金 / 沪银 / 螺纹 / 玻璃；引擎默认「本地缓存」
3. 跑回测 → 自动打分（收益 / 回撤 / 夏普 / 胜率盈亏比 / 样本量）
4. 对比 + 笔记，结果在 `data/backtest_runs/`

**和天勤**
- 看板回测关闭 web_gui，适合批量
- K 线细看：`python strategies/falcon_au_backtest.py`（9876）
- 模拟盘：`python strategies/falcon_au_sim.py`
"""
    )
    st.markdown("</div>", unsafe_allow_html=True)


def main() -> None:
    with st.sidebar:
        st.markdown('<p class="iq-brand">IgniteQuant</p>', unsafe_allow_html=True)
        st.markdown('<p class="iq-brand-sub">家庭量化作坊</p>', unsafe_allow_html=True)
        st.markdown('<p class="iq-nav-label">导航</p>', unsafe_allow_html=True)
        page = st.radio(
            "导航",
            ["跑回测", "对比与打分", "作坊说明"],
            label_visibility="collapsed",
        )
    if page == "跑回测":
        page_run()
    elif page == "对比与打分":
        page_compare()
    else:
        page_lab()


if __name__ == "__main__":
    main()

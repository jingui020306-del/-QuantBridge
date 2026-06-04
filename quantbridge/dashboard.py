"""
QuantBridge Dashboard — Streamlit 实时仪表盘。

显示：
  - Pipeline 状态（上次回环时间、各阶段状态）
  - 因子检验结果
  - 回测绩效（收益曲线、回撤图）
  - 当前信号
  - 风控指标
"""

import json
from datetime import datetime
from pathlib import Path

import streamlit as st

# 页面配置
st.set_page_config(
    page_title="QuantBridge Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📊 QuantBridge Dashboard")
st.caption("文件桥接 + 因子检验 lite + 回测降级 + 绩效摘要")

# ---- 侧边栏 ----

with st.sidebar:
    st.header("控制面板")

    # 配置路径
    config_path = st.text_input("配置文件", "config/default.yaml")
    watch_dir = st.text_input("监听目录", "outputs/watch")
    runtime_dir = st.text_input("运行状态目录", "outputs/runtime")

    st.divider()

    # 状态概览
    st.header("管线状态")

    heartbeat_path = Path(runtime_dir) / "heartbeat.json"
    if heartbeat_path.exists():
        hb = json.loads(heartbeat_path.read_text())
        st.success(f"运行中 — 上次回环: {hb.get('last_cycle', 'N/A')}")
    else:
        st.warning("Daemon 未启动或首次运行中")

    st.divider()

    # 手动触发
    if st.button("🔄 手动触发回环", use_container_width=True):
        trigger = {"event": "manual", "timestamp": datetime.now().isoformat()}
        (Path(watch_dir) / "trigger_manual.json").write_text(
            json.dumps(trigger, indent=2)
        )
        st.toast("已触发回环，等待 daemon 执行...")

# ---- 主区域 ----

tab1, tab2, tab3, tab4 = st.tabs([
    "📡 实时状态", "🔬 因子检验", "📈 回测绩效", "📋 交易信号"
])

with tab1:
    st.subheader("Pipeline 阶段状态")

    state_path = Path("outputs/pipeline_state.json")
    if state_path.exists():
        state = json.loads(state_path.read_text())
        cols = st.columns(4)
        stages = [
            ("数据更新", "data_updated"),
            ("因子计算", "factors_updated"),
            ("因子检验", "alphalens_updated"),
            ("LEAN回测", "lean_updated"),
        ]
        for col, (label, key) in zip(cols, stages):
            if state.get(key):
                col.success(f"✓ {label}")
            else:
                col.info(f"○ {label}")
    else:
        st.info("等待首次回环完成...")

with tab2:
    st.subheader("因子检验结果")

    signal_path = Path("outputs/signals.json")
    if signal_path.exists():
        signals = json.loads(signal_path.read_text())
        factors = signals.get("factors", {})

        if factors:
            import pandas as pd

            rows = []
            for name, info in factors.items():
                rows.append({
                    "因子": name,
                    "IC": info.get("ic_pearson", 0),
                    "ICIR": info.get("icir", 0),
                    "分层收益": info.get("quantile_spread", 0),
                    "覆盖标的": info.get("n_stocks", 0),
                })

            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)

            # 通过/未通过
            passed = signals.get("passed_factors", [])
            if passed:
                st.success(f"通过检验: {', '.join(passed)}")
            else:
                st.warning("无因子通过检验阈值")
        else:
            st.info("暂无因子检验结果")
    else:
        st.info("等待首次信号生成...")

with tab3:
    st.subheader("回测绩效")

    signal_path = Path("outputs/signals.json")
    if signal_path.exists():
        signals = json.loads(signal_path.read_text())
        metrics = signals.get("metrics", {})

        if metrics:
            cols = st.columns(5)
            cols[0].metric("总收益", f"{metrics.get('total_return', 0)}%")
            cols[1].metric("Sharpe", metrics.get("sharpe_ratio", "-"))
            cols[2].metric("最大回撤", f"{metrics.get('max_drawdown', 0)}%")
            cols[3].metric("交易次数", metrics.get("total_trades", 0))
            cols[4].metric("胜率", f"{metrics.get('win_rate', 0)}%")

            # 净值曲线
            trades = signals.get("trades", [])
            if trades:
                import pandas as pd

                trade_df = pd.DataFrame(trades)
                if "date" in trade_df.columns and "type" in trade_df.columns:
                    buys = trade_df[trade_df["type"] == "buy"]
                    sells = trade_df[trade_df["type"] == "sell"]
                    st.caption(f"买入: {len(buys)} 笔 | 卖出: {len(sells)} 笔")

            st.caption("完整净值曲线图表待 v0.4 添加 plotly 交互图")
        else:
            st.info("暂无回测结果")
    else:
        st.info("等待首次回测完成...")

with tab4:
    st.subheader("交易信号")

    signal_path = Path("outputs/signals.json")
    if signal_path.exists():
        signals = json.loads(signal_path.read_text())
        trades = signals.get("trades", [])

        if trades:
            import pandas as pd

            df = pd.DataFrame(trades)
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("暂无交易信号")
    else:
        st.info("等待首次信号生成...")

# ---- 底部状态栏 ----

st.divider()
st.caption(
    f"QuantBridge v0.1.0 | "
    f"file bridge | "
    f"factor-lite → backtest fallback → performance summary | "
    f"Dashboard refresh: {Path(watch_dir)}"
)

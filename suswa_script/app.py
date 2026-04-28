import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
from pathlib import Path

# ──────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────

LTRS_TOL = 0.01   # liters  — abs(LTRS − Volume (l)) must be ≤ this
RATE_TOL = 5.0    # KES/L   — abs(RATE − Price(KES)) must be ≤ this

_EXCEL_EPOCH = pd.Timestamp("1899-12-30")

# Default file paths (relative to repo root — works locally and on Streamlit Cloud)
_REPO_ROOT = Path(__file__).parent.parent
DEFAULT_MPESA_PATH = str(_REPO_ROOT / "suswa_data_csv" / "mpesa_28_02.csv")
DEFAULT_SHIFT_PATH = str(_REPO_ROOT / "suswa_data_csv" / "shift_report.csv")

# ──────────────────────────────────────────────────────────────
# SESSION STATE INITIALIZATION
# ──────────────────────────────────────────────────────────────

def _init_session_state():
    """Initialize session state for manual pump allocation and file tracking."""
    if "manual_allocations" not in st.session_state:
        st.session_state.manual_allocations = {}
    if "selected_txn_by_shift" not in st.session_state:
        st.session_state.selected_txn_by_shift = {}
    if "selected_volume_by_shift" not in st.session_state:
        st.session_state.selected_volume_by_shift = {}
    if "shift_file_path" not in st.session_state:
        st.session_state.shift_file_path = None

_init_session_state()

# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────

def _excel_serial_to_str(serial):
    """Convert an Excel date-serial float to a human-readable string."""
    try:
        ts = _EXCEL_EPOCH + pd.to_timedelta(float(serial), unit="D")
        return ts.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(serial)


def _to_numeric(series):
    """Strip non-numeric noise from a series and coerce to float."""
    return pd.to_numeric(
        series.astype(str)
              .str.replace(r"[^0-9.\-]", "", regex=True)
              .replace("", float("nan")),
        errors="coerce",
    )


def _join_unique(values, sep=" | "):
    """Join unique, non-empty string representations preserving first-seen order."""
    seen = set()
    result = []
    for v in values:
        s = str(v).strip()
        if s and s not in ("nan", "None") and s not in seen:
            seen.add(s)
            result.append(s)
    return sep.join(result) if result else "—"


def _join_all(values, sep=" | "):
    """Join every non-empty value (all occurrences, not deduplicated)."""
    parts = [str(v).strip() for v in values if str(v).strip() not in ("", "nan", "None")]
    return sep.join(parts) if parts else "—"


def _format_match_option(row):
    """Create a readable option label for selecting one matched 24hr row."""
    vol = row.get("Volume (l)")
    pump = str(row.get("Pump", "—"))
    attendant = str(row.get("Attendant", "—"))
    nozzle = str(row.get("Nozzle", "—"))
    date_str = str(row.get("Date_Str", "—"))
    vol_txt = f"{float(vol):.2f}" if pd.notna(vol) else "—"
    return f"{vol_txt} L | Pump {pump} | Attendant {attendant} | Nozzle {nozzle} | {date_str}"


def _parse_mpesa_invoice_no(inv_str):
    """Extract numeric invoice number from MPesa Inv No. field."""
    if pd.isna(inv_str) or inv_str == "":
        return None
    s = str(inv_str).strip()
    numeric_part = ''.join(c for c in s if c.isdigit())
    return int(numeric_part) if numeric_part else None


def _load_default_mpesa():
    """Load MPesa file from default workspace path if it exists."""
    if os.path.exists(DEFAULT_MPESA_PATH):
        return pd.read_csv(DEFAULT_MPESA_PATH)
    return None


def _load_default_shift():
    """Load Shift file from default workspace path if it exists."""
    if os.path.exists(DEFAULT_SHIFT_PATH):
        return pd.read_csv(DEFAULT_SHIFT_PATH)
    return None


# ──────────────────────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Suswa Shift vs 24hr Pump Reconciliation with MPesa",
    layout="wide",
)

st.title("Suswa Shift vs 24hr Pump Reconciliation with MPesa")
st.markdown(
    "**Task**: Match shift-report lines to pump transactions (24hr) "
    "using `LTRS ≈ Volume (l)` (±0.01 L) and `|RATE − Price(KES)| ≤ 5`. "
    "Also match shift invoices to MPesa payments."
)

# ──────────────────────────────────────────────────────────────
# SIDEBAR — FILE UPLOADERS & SETTINGS
# ──────────────────────────────────────────────────────────────

st.sidebar.header("📁 Data Inputs")

# Shift Report Upload
shift_file = st.sidebar.file_uploader("Upload Shift Report (CSV)", type="csv", key="shift_up")
if not shift_file:
    df_shift_default = _load_default_shift()
    if df_shift_default is not None:
        st.sidebar.success("✓ Loaded default shift report from workspace")
        shift_file = df_shift_default

# 24hr Pump Report Upload
hr24_file = st.sidebar.file_uploader("Upload 24hr Pump Report (CSV)", type="csv", key="hr24_up")

# MPesa Report Upload (with default)
mpesa_file = st.sidebar.file_uploader(
    "Upload MPesa Report (CSV)",
    type="csv",
    key="mpesa_up",
    help="Optional: Match shift invoices to MPesa payments"
)
if not mpesa_file:
    df_mpesa_default = _load_default_mpesa()
    if df_mpesa_default is not None:
        st.sidebar.success("✓ Loaded default MPesa report from workspace")
        mpesa_file = df_mpesa_default

st.sidebar.divider()
st.sidebar.caption(f"LTRS tolerance: ±{LTRS_TOL} L")
st.sidebar.caption(f"RATE tolerance: ±{RATE_TOL} KES/L")

st.sidebar.divider()

# ── DEBUG VISUALIZER OPTION ─────────────────────────────────
pause_after_reconcile = st.sidebar.checkbox(
    "Pause in debugger after reconciliation",
    value=False,
    help="When running app.py under the Python debugger, pause after reconciliation so you can inspect data in VS Code debug visualizer."
)

st.sidebar.divider()

# ── SAVE TO CSV BUTTON ───────────────────────────────────────
st.sidebar.header("💾 Save Results")
save_clicked = st.sidebar.button(
    "Save to shift_report.csv",
    help="Write enriched data back to the original shift file"
)

# ──────────────────────────────────────────────────────────────
# MAIN BODY
# ──────────────────────────────────────────────────────────────

if shift_file is not None and hr24_file is not None:

    # ── LOAD & CLEAN ──── SHIFT & 24HR ──────────────────────

    if isinstance(shift_file, pd.DataFrame):
        df_shift = shift_file.copy()
    else:
        df_shift = pd.read_csv(shift_file)
    
    df_hr24 = pd.read_csv(hr24_file)

    df_shift.columns = df_shift.columns.str.strip()
    df_hr24.columns = df_hr24.columns.str.strip()

    # Numeric conversion — shift
    df_shift["LTRS"] = _to_numeric(df_shift["LTRS"])
    df_shift["AMT"] = _to_numeric(df_shift["AMT"])
    df_shift["RATE"] = _to_numeric(df_shift["RATE"])

    # Numeric conversion — 24hr
    df_hr24["Volume (l)"] = _to_numeric(df_hr24["Volume (l)"])
    df_hr24["Price(KES)"] = _to_numeric(df_hr24["Price(KES)"])

    # Convert Excel serial date → readable string
    df_hr24["Date_Str"] = df_hr24["Date"].apply(_excel_serial_to_str)

    # Stable integer indices
    df_shift = df_shift.reset_index(drop=True)
    df_shift["_shift_idx"] = df_shift.index

    df_hr24 = df_hr24.reset_index(drop=True)
    df_hr24["_hr24_idx"] = df_hr24.index

    # ── LOAD & CLEAN ──── MPESA ─────────────────────────────

    df_mpesa = None
    if mpesa_file is not None:
        if isinstance(mpesa_file, pd.DataFrame):
            df_mpesa = mpesa_file.copy()
        else:
            df_mpesa = pd.read_csv(mpesa_file)
        
        df_mpesa.columns = df_mpesa.columns.str.strip()
        df_mpesa["Paid In"] = _to_numeric(df_mpesa["Paid In"])
        df_mpesa["_inv_no_numeric"] = df_mpesa["Inv No."].apply(_parse_mpesa_invoice_no)
        
        # Store file path for save operation
        st.session_state.shift_file_path = DEFAULT_SHIFT_PATH

    # ── MATCHING ALGORITHM: 24HR PUMP ────────────────────────

    df_cross = df_shift[["_shift_idx", "LTRS", "RATE"]].merge(
        df_hr24[[
            "_hr24_idx", "Volume (l)", "Price(KES)",
            "Attendant", "Pump", "Nozzle", "Date_Str",
        ]],
        how="cross",
    )

    df_cross["_ltrs_diff"] = (df_cross["LTRS"] - df_cross["Volume (l)"]).abs()
    df_cross["_rate_diff"] = (df_cross["RATE"] - df_cross["Price(KES)"]).abs()

    df_matches = df_cross[
        (df_cross["_ltrs_diff"] <= LTRS_TOL) &
        (df_cross["_rate_diff"] <= RATE_TOL)
    ].copy()

    # Aggregate all matching 24hr rows per shift index
    if not df_matches.empty:
        grp = df_matches.groupby("_shift_idx")
        df_agg = pd.DataFrame({
            "Match_Count": grp.size(),
            "Matched_Attendant": grp["Attendant"].apply(_join_unique),
            "Matched_Pump": grp["Pump"].apply(lambda s: _join_unique(s.astype(str))),
            "Matched_Nozzle": grp["Nozzle"].apply(lambda s: _join_unique(s.astype(str))),
            "Matched_Date": grp["Date_Str"].apply(lambda s: _join_all(s.sort_values())),
            "Rate_Diff": grp["_rate_diff"].mean().round(4),
            "Matched_Volumes": grp["Volume (l)"].apply(
                lambda s: _join_all([f"{v:.2f}" for v in s if pd.notna(v)])
            ),
        }).reset_index()
    else:
        df_agg = pd.DataFrame(
            columns=[
                "_shift_idx", "Match_Count", "Matched_Attendant",
                "Matched_Pump", "Matched_Nozzle", "Matched_Date", "Rate_Diff", "Matched_Volumes",
            ]
        )

    # Left-join aggregated matches back onto shift
    df_result = df_shift.merge(df_agg, on="_shift_idx", how="left")
    df_result["Match_Count"] = df_result["Match_Count"].fillna(0).astype(int)
    df_result["Matched"] = df_result["Match_Count"] > 0

    for col in ["Matched_Attendant", "Matched_Pump", "Matched_Nozzle", "Matched_Date", "Matched_Volumes"]:
        df_result[col] = df_result[col].fillna("—")

    # Build per-shift match options for manual volume selection.
    # Uses one option per matched 24hr row so the analyst can choose exact liters.
    match_options_by_shift = {}
    if not df_matches.empty:
        _cols = [
            "_shift_idx", "_hr24_idx", "Volume (l)",
            "Pump", "Attendant", "Nozzle", "Date_Str",
        ]
        for shift_idx, grp_rows in df_matches[_cols].sort_values(["_shift_idx", "_hr24_idx"]).groupby("_shift_idx"):
            options = []
            for _, mrow in grp_rows.iterrows():
                options.append(
                    {
                        "txn_id": int(mrow["_hr24_idx"]),
                        "volume": float(mrow["Volume (l)"]) if pd.notna(mrow["Volume (l)"]) else None,
                        "label": _format_match_option(mrow),
                    }
                )
            match_options_by_shift[int(shift_idx)] = options

    # ── MATCHING ALGORITHM: MPESA ────────────────────────────

    if df_mpesa is not None:
        df_result["_inv_no_numeric"] = pd.to_numeric(
            df_result["INV NO."].astype(str)
                                 .str.replace(r"[^0-9]", "", regex=True)
                                 .replace("", float("nan")),
            errors="coerce"
        )

        # Aggregate MPesa by invoice number to avoid duplicate rows on merge
        # If multiple MPesa transactions for same invoice, sum amounts and concatenate times
        df_mpesa_agg = df_mpesa.groupby("_inv_no_numeric").agg({
            "Paid In": "sum",
            "Completion Time": lambda x: " | ".join(x.astype(str).unique())
        }).reset_index()
        df_mpesa_agg = df_mpesa_agg.rename(columns={
            "Paid In": "MPesa_Amount",
            "Completion Time": "MPesa_Time"
        })

        df_result = df_result.merge(df_mpesa_agg, on="_inv_no_numeric", how="left")

        # Determine MPesa match status and calculate variance
        df_result["MPesa_Match"] = df_result["MPesa_Amount"].notna()
        df_result["MPesa_Match_Status"] = df_result["MPesa_Match"].map(
            {True: "Matched", False: "No Match"}
        )
        df_result["MPesa_Variance"] = df_result["AMT"] - df_result["MPesa_Amount"]
        df_result["MPesa_Amount"] = df_result["MPesa_Amount"].fillna(0).round(2)
        df_result["MPesa_Variance"] = df_result["MPesa_Variance"].fillna(0).round(2)
        df_result["MPesa_Time"] = df_result["MPesa_Time"].fillna("—")

        df_result = df_result.drop(columns=["_inv_no_numeric"])
    else:
        # MPesa columns as empty if no file uploaded
        df_result["MPesa_Match"] = False
        df_result["MPesa_Match_Status"] = "No Match"
        df_result["MPesa_Amount"] = 0.0
        df_result["MPesa_Variance"] = 0.0
        df_result["MPesa_Time"] = "—"

    # ── KPI METRICS ──────────────────────────────────────────

    st.header("📊 Dashboard Summary")

    total_rows = len(df_result)
    matched_rows = int(df_result["Matched"].sum())
    unmatched_rows = total_rows - matched_rows
    pct_coverage = (matched_rows / total_rows * 100) if total_rows > 0 else 0.0
    
    mpesa_matched = int(df_result["MPesa_Match"].sum()) if df_mpesa is not None else 0
    mpesa_pct = (mpesa_matched / total_rows * 100) if total_rows > 0 else 0.0
    
    total_ltrs = df_result["LTRS"].sum()
    matched_ltrs = df_result.loc[df_result["Matched"], "LTRS"].sum()
    unmatched_ltrs = total_ltrs - matched_ltrs

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Shift Rows", f"{total_rows:,}")
    c2.metric(
        "24hr Pump Matched",
        f"{matched_rows:,}",
        delta=f"{pct_coverage:.1f}% coverage",
    )
    c3.metric(
        "Unmatched",
        f"{unmatched_rows:,}",
        delta=f"-{100 - pct_coverage:.1f}%",
        delta_color="inverse",
    )
    c4.metric("Total LTRS", f"{total_ltrs:,.2f} L")
    if df_mpesa is not None:
        c5.metric(
            "MPesa Matched",
            f"{mpesa_matched:,}",
            delta=f"{mpesa_pct:.1f}%",
        )

    # ── DEBUG VISUALIZER BREAKPOINT ──────────────────────────
    # Pause execution if debug mode is enabled, allowing VS Code debug visualizer
    # to inspect df_result, agg_ligo, df_mpesa, and other reconciliation dataframes
    if pause_after_reconcile:
        breakpoint()

    # ── BAR CHART — coverage by invoice category ─────────────

    st.markdown("#### Match Coverage by Invoice Category")

    df_cat = (
        df_result
        .groupby(["GENERAL INVOICES", "Matched"])
        .size()
        .reset_index(name="Count")
    )
    df_cat["Status"] = df_cat["Matched"].map({True: "Matched", False: "Unmatched"})

    fig_bar = px.bar(
        df_cat,
        x="GENERAL INVOICES",
        y="Count",
        color="Status",
        color_discrete_map={"Matched": "#198754", "Unmatched": "#dc3545"},
        barmode="group",
        text="Count",
        labels={"GENERAL INVOICES": "Invoice Category", "Count": "Rows"},
    )
    fig_bar.update_traces(textposition="outside")
    fig_bar.update_layout(
        xaxis_tickangle=-30,
        legend_title_text="",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
        height=380,
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    st.divider()

    st.divider()

    # ── FILTERS ──────────────────────────────────────────────

    with st.expander("🔍 Filter Results", expanded=False):
        col_f1, col_f2, col_f3 = st.columns(3)

        with col_f1:
            categories = sorted(df_result["GENERAL INVOICES"].dropna().unique().tolist())
            sel_cats   = st.multiselect(
                "Invoice Category",
                options=categories,
                default=categories,
                key="filter_cats",
            )

        with col_f2:
            status_opts = ["All", "Matched only", "Unmatched only"]
            sel_status  = st.selectbox("Match Status", status_opts, key="filter_status")

        with col_f3:
            min_ltrs = st.number_input(
                "Minimum LTRS",
                min_value=0.0,
                value=0.0,
                step=0.1,
                key="filter_min_ltrs",
            )

    # Apply filters
    df_view = df_result.copy()
    if sel_cats:
        df_view = df_view[df_view["GENERAL INVOICES"].isin(sel_cats)]
    if sel_status == "Matched only":
        df_view = df_view[df_view["Matched"]]
    elif sel_status == "Unmatched only":
        df_view = df_view[~df_view["Matched"]]
    if min_ltrs > 0:
        df_view = df_view[df_view["LTRS"] >= min_ltrs]

    # ── RESULT TABLE ─────────────────────────────────────────

    st.header("📋 Reconciliation Result")

    # ── INVOICE MATCH-DELTA GRAPH ───────────────────────────
    st.markdown("#### Invoice Match-Delta View")
    st.caption(
        "Pick any invoice below to see how its shift-report entry compares against "
        "the 24hr pump transactions. The two flow diagrams tell the full story: "
        "**Context Flow** shows how many shift rows share the same litre volume "
        "(helping you spot if this litre value is unique or repeated), while "
        "**Match Flow** traces the invoice through to its 24hr matches and flags "
        "whether it is balanced, over-matched, or under-matched."
    )
    if not df_view.empty and "INV NO." in df_view.columns:
        invoice_options = [str(x) for x in df_view["INV NO."].dropna().astype(str).unique().tolist()]
        if invoice_options:
            selected_invoice = st.selectbox(
                "Select shift invoice",
                options=invoice_options,
                key="invoice_delta_selector",
            )

            selected_rows = df_result[df_result["INV NO."].astype(str) == selected_invoice]
            if not selected_rows.empty:
                selected_row = selected_rows.iloc[0]
                match_count_24hr = int(selected_row.get("Match_Count", 0) or 0)
                baseline_selected_row = 1

                selected_ltrs = selected_row.get("LTRS")
                if pd.notna(selected_ltrs):
                    similar_liters_in_shift = int(((df_shift["LTRS"] - float(selected_ltrs)).abs() <= LTRS_TOL).sum())
                else:
                    similar_liters_in_shift = 0

                txn_delta = match_count_24hr - baseline_selected_row

                # ── CONTEXT FLOW SANKEY ─────────────────────────────────
                st.markdown("##### Context: How Unique Is This Litre Volume?")
                st.caption(
                    f"This shift row records **{float(selected_ltrs):.2f} L** at rate **{float(selected_row.get('RATE', 0)):.2f} KES/L**. "
                    f"There are **{similar_liters_in_shift}** shift row(s) with a litre value within ±{LTRS_TOL} L of that. "
                    "If many shift rows share the same volume, 24hr matches will be ambiguous — the pump log cannot "
                    "tell them apart. A count of 1 means this invoice is uniquely identifiable."
                )

                _unique_label = "Unique volume ✓" if similar_liters_in_shift == 1 else f"Shared by {similar_liters_in_shift} shift rows"
                _unique_color = "#22c55e" if similar_liters_in_shift == 1 else "#f59e0b"

                _ctx_labels = [
                    f"All Shift Rows\n({len(df_shift):,})",
                    f"Same-Volume Rows\n(±{LTRS_TOL} L): {similar_liters_in_shift}",
                    _unique_label,
                    f"Other volumes\n({len(df_shift) - similar_liters_in_shift:,})",
                ]
                _ctx_colors = ["#4e6bff", "#0d6efd", _unique_color, "#64748b"]
                _ctx_src = [0, 1, 0]
                _ctx_tgt = [1, 2, 3]
                _ctx_val = [
                    max(similar_liters_in_shift, 1),
                    max(similar_liters_in_shift, 1),
                    max(len(df_shift) - similar_liters_in_shift, 1),
                ]
                _ctx_lc = [
                    "rgba(13,110,253,0.40)",
                    "rgba(34,197,94,0.40)" if similar_liters_in_shift == 1 else "rgba(245,158,11,0.40)",
                    "rgba(100,116,139,0.35)",
                ]

                fig_ctx = go.Figure(data=[go.Sankey(
                    arrangement="snap",
                    node=dict(
                        pad=20,
                        thickness=24,
                        label=_ctx_labels,
                        color=_ctx_colors,
                        line=dict(color="#0b1220", width=1),
                    ),
                    link=dict(source=_ctx_src, target=_ctx_tgt, value=_ctx_val, color=_ctx_lc),
                )])
                fig_ctx.update_layout(
                    title_text=f"Litre Context: Invoice {selected_invoice} ({float(selected_ltrs):.2f} L)",
                    font=dict(size=13, color="#f1f5f9"),
                    paper_bgcolor="#0d1b2a",
                    plot_bgcolor="#0d1b2a",
                    height=340,
                    margin=dict(l=10, r=10, t=48, b=10),
                )
                st.plotly_chart(fig_ctx, use_container_width=True)

                st.markdown("##### Invoice Match Flow")

                # Build Sankey nodes/links dynamically for all match scenarios
                if match_count_24hr > 0 and txn_delta == 0:
                    _sank_labels = [
                        f"Invoice {selected_invoice}\n(1 shift row)",
                        f"24hr Transactions\n({match_count_24hr} found)",
                        "Balanced ✓",
                    ]
                    _sank_colors = ["#4e6bff", "#0d6efd", "#22c55e"]
                    _sank_src = [0, 1]
                    _sank_tgt = [1, 2]
                    _sank_val = [1, 1]
                    _sank_lc  = ["rgba(78,107,255,0.40)", "rgba(34,197,94,0.40)"]
                elif match_count_24hr > 0 and txn_delta > 0:
                    _sank_labels = [
                        f"Invoice {selected_invoice}\n(1 shift row)",
                        f"24hr Transactions\n({match_count_24hr} found)",
                        "Expected (1)",
                        f"Excess (+{txn_delta})",
                    ]
                    _sank_colors = ["#4e6bff", "#0d6efd", "#ffc107", "#dc3545"]
                    _sank_src = [0, 1, 1]
                    _sank_tgt = [1, 2, 3]
                    _sank_val = [match_count_24hr, 1, txn_delta]
                    _sank_lc  = [
                        "rgba(78,107,255,0.40)",
                        "rgba(255,193,7,0.40)",
                        "rgba(220,53,69,0.40)",
                    ]
                elif match_count_24hr > 0 and txn_delta < 0:
                    _sank_labels = [
                        f"Invoice {selected_invoice}",
                        f"24hr Transactions\n({match_count_24hr} found)",
                        f"Gap\n({abs(txn_delta)} missing)",
                        "Matched",
                    ]
                    _sank_colors = ["#4e6bff", "#0d6efd", "#dc3545", "#ffc107"]
                    _sank_src = [0, 0, 1]
                    _sank_tgt = [1, 2, 3]
                    _sank_val = [match_count_24hr, abs(txn_delta), match_count_24hr]
                    _sank_lc  = [
                        "rgba(78,107,255,0.40)",
                        "rgba(220,53,69,0.40)",
                        "rgba(255,193,7,0.40)",
                    ]
                else:
                    _sank_labels = [
                        f"Invoice {selected_invoice}\n(1 shift row)",
                        "24hr Pool\n(0 found)",
                        "Unmatched",
                    ]
                    _sank_colors = ["#4e6bff", "#64748b", "#dc3545"]
                    _sank_src = [0, 1]
                    _sank_tgt = [1, 2]
                    _sank_val = [1, 1]
                    _sank_lc  = ["rgba(100,116,139,0.40)", "rgba(220,53,69,0.40)"]

                fig_sankey = go.Figure(data=[go.Sankey(
                    arrangement="snap",
                    node=dict(
                        pad=24,
                        thickness=28,
                        label=_sank_labels,
                        color=_sank_colors,
                        line=dict(color="#0b1220", width=1),
                    ),
                    link=dict(
                        source=_sank_src,
                        target=_sank_tgt,
                        value=_sank_val,
                        color=_sank_lc,
                    ),
                )])
                fig_sankey.update_layout(
                    title_text=f"Match Flow: Invoice {selected_invoice}",
                    font=dict(size=13, color="#f1f5f9"),
                    paper_bgcolor="#0d1b2a",
                    plot_bgcolor="#0d1b2a",
                    height=380,
                    margin=dict(l=10, r=10, t=48, b=10),
                )
                st.caption(
                    "The **Match Flow** traces this single invoice through the 24hr pump log. "
                    "Each band represents transaction volume flowing from the shift record into "
                    "the matching pump entries. "
                    "A green end-node means the invoice is exactly accounted for; "
                    "red means no pump record was found; "
                    "amber means multiple pump records matched — use the manual selector below to pick the correct one."
                )
                st.plotly_chart(fig_sankey, use_container_width=True)

                if txn_delta > 0:
                    st.info(
                        f"**Invoice {selected_invoice} — Over-matched ({txn_delta} excess).** "
                        f"The 24hr pump log contains {match_count_24hr} transaction(s) that all fit this "
                        f"invoice's litre/rate profile. Only one should belong to it. "
                        "Use the manual selector in the table below to assign the correct transaction "
                        "and exclude the duplicates."
                    )
                elif txn_delta < 0:
                    st.warning(
                        f"**Invoice {selected_invoice} — Under-matched ({abs(txn_delta)} missing).** "
                        f"Only {match_count_24hr} pump transaction(s) were found for this invoice. "
                        "The expected 1 was not located — the pump may have recorded a slightly different "
                        "litre or rate value. Check the 24hr diagnostics section below for unmatched pump rows."
                    )
                else:
                    st.success(
                        f"**Invoice {selected_invoice} — Balanced.** "
                        "Exactly one 24hr pump transaction matches this invoice's litre volume and rate. "
                        "No action required."
                    )
    else:
        st.caption("No filtered rows available for invoice delta graph.")

    # ── MERGED MANUAL SELECTION (IN RESULT FLOW) ────────────
    # Enforce one-to-one assignment: a chosen 24hr transaction is not selectable
    # in any other shift row until it is cleared.
    df_multiple_matches = df_view[df_view["Match_Count"] > 1].copy()

    valid_shift_ids = set(match_options_by_shift.keys())
    for s_idx in list(st.session_state.selected_txn_by_shift.keys()):
        if s_idx not in valid_shift_ids:
            st.session_state.selected_txn_by_shift.pop(s_idx, None)
            st.session_state.selected_volume_by_shift.pop(s_idx, None)

    for s_idx in list(st.session_state.selected_txn_by_shift.keys()):
        valid_txn_ids = {opt["txn_id"] for opt in match_options_by_shift.get(s_idx, [])}
        if st.session_state.selected_txn_by_shift.get(s_idx) not in valid_txn_ids:
            st.session_state.selected_txn_by_shift.pop(s_idx, None)
            st.session_state.selected_volume_by_shift.pop(s_idx, None)

    if not df_multiple_matches.empty:
        st.markdown("#### Manual 24hr Transaction Selection")
        st.caption(
            "Select one 24hr transaction per shift row. Selected transactions disappear from other rows and reappear when cleared."
        )

        for _, row in df_multiple_matches.iterrows():
            shift_idx = int(row["_shift_idx"])
            options_all = match_options_by_shift.get(shift_idx, [])
            current_txn = st.session_state.selected_txn_by_shift.get(shift_idx)

            used_by_others = {
                txn_id
                for s_id, txn_id in st.session_state.selected_txn_by_shift.items()
                if s_id != shift_idx and txn_id is not None
            }

            options_available = [
                opt
                for opt in options_all
                if opt["txn_id"] == current_txn or opt["txn_id"] not in used_by_others
            ]

            option_txn = [None] + [opt["txn_id"] for opt in options_available]
            label_by_txn = {None: "— Select matched transaction —"}
            for opt in options_available:
                label_by_txn[opt["txn_id"]] = opt["label"]

            current_index = 0
            if current_txn in option_txn:
                current_index = option_txn.index(current_txn)

            c1, c2, c3, c4 = st.columns([1, 2, 2, 3])
            with c1:
                st.write(str(row["INV NO."]))
            with c2:
                st.write(f"{row['Matched_Pump']} | {row['Matched_Attendant']} | {row['Matched_Nozzle']}")
            with c3:
                st.write(f"{row['LTRS']} L @ {row['RATE']} KES/L")
            with c4:
                selected_txn = st.selectbox(
                    "Select 24hr transaction",
                    options=option_txn,
                    index=current_index,
                    format_func=lambda t: label_by_txn.get(t, "— Select matched transaction —"),
                    key=f"volume_select_{shift_idx}",
                    label_visibility="collapsed",
                )

                if selected_txn is None:
                    st.session_state.selected_txn_by_shift.pop(shift_idx, None)
                    st.session_state.selected_volume_by_shift.pop(shift_idx, None)
                else:
                    st.session_state.selected_txn_by_shift[shift_idx] = selected_txn
                    selected_opt = next((opt for opt in options_all if opt["txn_id"] == selected_txn), None)
                    if selected_opt is not None and selected_opt["volume"] is not None:
                        st.session_state.selected_volume_by_shift[shift_idx] = float(selected_opt["volume"])
                    else:
                        st.session_state.selected_volume_by_shift.pop(shift_idx, None)

    # Selected liters/variance columns for table display and CSV export.
    df_result["Selected_24hr_Liters"] = pd.NA
    df_result["Selected_24hr_Variance"] = pd.NA

    for i, res_row in df_result.iterrows():
        s_idx = int(res_row["_shift_idx"])
        selected_val = st.session_state.selected_volume_by_shift.get(s_idx)
        if selected_val is not None and pd.notna(res_row["LTRS"]):
            df_result.at[i, "Selected_24hr_Liters"] = float(selected_val)
            df_result.at[i, "Selected_24hr_Variance"] = round(float(selected_val) - float(res_row["LTRS"]), 2)

    if df_mpesa is not None:
        st.caption(
            f"Showing {len(df_view):,} of {len(df_result):,} rows  •  "
            f"🟢 Green = 24hr matched, 🔴 Red = unmatched, 🔵 Blue = MPesa matched"
        )
    else:
        st.caption(f"Showing {len(df_view):,} of {len(df_result):,} rows  •  green = matched, red = unmatched")

    # Build display columns based on whether MPesa is available
    DISPLAY_COLS = [
        "GENERAL INVOICES", "INV NO.", "VEHICLE NO.", "LTRS", "AMT", "RATE",
        "Match_Count", "Matched_Attendant", "Matched_Pump",
        "Matched_Nozzle", "Matched_Date", "Matched_Volumes", "Selected_24hr_Liters", "Selected_24hr_Variance",
        "MPesa_Match_Status", "MPesa_Variance", "MPesa_Time",
    ]
    DISPLAY_COLS = [c for c in DISPLAY_COLS if c in df_view.columns]
    df_display = df_view[DISPLAY_COLS].reset_index(drop=True)

    # Row-level colour: green = 24hr matched, red = 24hr unmatched, blue = mpesa matched
    match_flags = df_view["Matched"].reset_index(drop=True)
    mpesa_match_flags = df_view["MPesa_Match"].reset_index(drop=True) if df_mpesa is not None else None

    def _row_color(row):
        idx = row.name
        # MPesa match takes precedence (blue)
        if mpesa_match_flags is not None and mpesa_match_flags.iloc[idx]:
            color = "#cfe2ff"  # Light blue
        # Then 24hr match (green)
        elif match_flags.iloc[idx]:
            color = "#d4edda"  # Light green
        # Otherwise unmatched (red)
        else:
            color = "#f8d7da"  # Light red
        return [f"background-color: {color}"] * len(row)

    styled = df_display.style.apply(_row_color, axis=1)
    styled = styled.format(
        {
            "LTRS": "{:,.2f}",
            "AMT": "{:,.2f}",
            "RATE": "{:,.4f}",
            "Selected_24hr_Liters": lambda x: f"{x:.2f}" if pd.notna(x) else "—",
            "Selected_24hr_Variance": lambda x: f"{x:.2f}" if pd.notna(x) else "—",
            "MPesa_Variance": lambda x: f"{x:.2f}" if pd.notna(x) and x != 0 else "—",
        },
        na_rep="—",
    )

    st.dataframe(styled, use_container_width=True, hide_index=True, height=520)

    st.divider()

    # ── DIAGNOSTICS ──────────────────────────────────────────

    with st.expander(
        "🔬 Diagnostics: 24hr Transactions Without a Shift Match",
        expanded=False,
    ):
        st.markdown(
            "These pump transactions appear in the 24-hour report but were **not claimed** "
            "by any shift-report row. They may represent unrecorded sales or pump test runs."
        )

        matched_hr24_idx = (
            set(df_matches["_hr24_idx"].tolist())
            if not df_matches.empty
            else set()
        )

        df_unmatched_hr24 = (
            df_hr24[~df_hr24["_hr24_idx"].isin(matched_hr24_idx)]
            .drop(columns=["_hr24_idx", "Date_Str"])
            .copy()
        )

        st.caption(f"{len(df_unmatched_hr24):,} unmatched 24hr transaction(s)")

        if not df_unmatched_hr24.empty:
            df_unmatched_hr24["Date"] = df_unmatched_hr24["Date"].apply(_excel_serial_to_str)
            st.dataframe(df_unmatched_hr24, use_container_width=True, hide_index=True)
        else:
            st.success("All 24hr transactions were claimed by at least one shift row.")

    # ── DIAGNOSTICS: MPESA ───────────────────────────────────

    if df_mpesa is not None:
        with st.expander(
            "🔬 Diagnostics: MPesa Transactions Without a Shift Match",
            expanded=False,
        ):
            st.markdown(
                "These MPesa payments were **not matched** to any shift invoice. "
                "They may represent unrecorded transactions or invoice number mismatches."
            )

            matched_mpesa_inv = set(df_result.loc[df_result["MPesa_Match"], "INV NO."].unique())
            df_unmatched_mpesa = df_mpesa[
                ~df_mpesa["_inv_no_numeric"].isin(
                    [_parse_mpesa_invoice_no(inv) for inv in matched_mpesa_inv]
                )
            ].copy()

            st.caption(f"{len(df_unmatched_mpesa):,} unmatched MPesa transaction(s)")

            if not df_unmatched_mpesa.empty:
                display_mpesa_cols = ["Receipt", "Completion Time", "Paid In", "Inv No."]
                display_mpesa_cols = [c for c in display_mpesa_cols if c in df_unmatched_mpesa.columns]
                st.dataframe(
                    df_unmatched_mpesa[display_mpesa_cols],
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.success("All MPesa transactions were matched to shift invoices.")

    st.divider()

    # ── SAVE TO CSV ──────────────────────────────────────────

    if save_clicked:
        if st.session_state.shift_file_path:
            try:
                # Prepare export dataframe (all columns)
                export_df = df_result.drop(columns=["_shift_idx"], errors="ignore")
                
                # Save to original file
                export_df.to_csv(st.session_state.shift_file_path, index=False)
                st.sidebar.success(
                    f"✅ Saved {len(export_df)} rows to {st.session_state.shift_file_path}",
                )
            except Exception as e:
                st.sidebar.error(f"❌ Error saving file: {str(e)}")
        else:
            st.sidebar.warning("⚠️ Shift file path not detected. Cannot save.")

    # ── DOWNLOAD ─────────────────────────────────────────────

    st.subheader("⬇️ Export")

    export_df = df_result.drop(columns=["_shift_idx"], errors="ignore")
    csv_bytes = export_df.to_csv(index=False).encode("utf-8")

    st.download_button(
        label="Download Full Reconciliation (CSV)",
        data=csv_bytes,
        file_name="suswa_reconciliation.csv",
        mime="text/csv",
    )

else:
    st.info(
        "Upload both the **Shift Report** and the **24hr Pump Report** CSV files "
        "using the sidebar to begin."
    )
    st.markdown(
        """
**Expected columns:**

| File | Required columns |
|---|---|
| Shift Report | `GENERAL INVOICES`, `INV NO.`, `VEHICLE NO.`, `LTRS`, `AMT`, `RATE` |
| 24hr Pump Report | `Date`, `Transaction`, `Attendant`, `Pump`, `Nozzle`, `Product`, `Price(KES)`, `Volume (l)`, `Sales (KES)` |
| MPesa Report (Optional) | `Receipt`, `Completion Time`, `Details`, `Paid In`, `Inv No.` |
        """
    )

import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, DataReturnMode, GridUpdateMode
from pathlib import Path
import re

LIGO_ROW_KEY_COL = "__ligo_row_key"


def _find_serial_no_col(df):
    """Return the first serial-number-like column name, if present."""
    preferred = ['Ser. No.', 'Ser No', 'Serial No', 'Serial Number', 'SerNo']
    for col in preferred:
        if col in df.columns:
            return col

    for col in df.columns:
        norm = ''.join(ch for ch in str(col).lower() if ch.isalnum())
        if norm in ('serno', 'serialno', 'serialnumber'):
            return col
    return None


def _normalize_text(value):
    """Return a clean string value with common empty markers removed."""
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none"} else text


def _normalize_invoice_value(value):
    """Normalize invoice-like values so joins survive whitespace and .0 suffixes."""
    text = _normalize_text(value)
    if not text:
        return ""
    return re.sub(r'\.0+$', '', text)


def _to_numeric_series(series):
    """Convert messy numeric strings like ' 1,000.00 ' or ' - ' into numbers."""
    cleaned = (
        series.fillna('')
        .astype(str)
        .str.replace(r'[^0-9.\-]', '', regex=True)
        .replace({'': pd.NA, '-': pd.NA, '.': pd.NA})
    )
    return pd.to_numeric(cleaned, errors='coerce').fillna(0)


def _join_unique(values, sep=', '):
    """Join non-empty values while preserving first-seen order."""
    seen = set()
    result = []
    for value in values:
        text = _normalize_text(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return sep.join(result)


def _extract_invoice_tokens(value):
    """Extract invoice tokens from free-form MPesa invoice fields."""
    text = _normalize_text(value)
    if not text:
        return []
    matches = re.findall(r'\d{3,}', text)
    if matches:
        return [_normalize_invoice_value(match) for match in matches if _normalize_invoice_value(match)]
    normalized = _normalize_invoice_value(text)
    return [normalized] if normalized else []


# Hardcoded workspace root — avoids Path.resolve() I/O on mounted filesystem.
_WORKSPACE_ROOT = Path('/media/izdixit/HIKSEMI/forensic/bonje/the_algorithmic')


def _resolve_uploaded_ligo_path(uploaded_file):
    """Find the on-disk path for an uploaded Ligo file by name match in workspace."""
    if uploaded_file is None:
        return None

    uploaded_name = Path(getattr(uploaded_file, 'name', '')).name
    if not uploaded_name:
        return None

    search_roots = [
        _WORKSPACE_ROOT / 'data_csv',
        _WORKSPACE_ROOT / 'data',
        _WORKSPACE_ROOT,
    ]

    for root in search_roots:
        try:
            if not root.exists():
                continue
            matches = [p for p in root.rglob(uploaded_name) if p.is_file()]
            if matches:
                return str(matches[0])
        except Exception:
            continue

    return None


# Fix compatibility issue between pandas 2.x and st_aggrid
pd.DataFrame.iteritems = pd.DataFrame.items
pd.Series.iteritems = pd.Series.items

# Configuration
st.set_page_config(page_title="Ultimate Fuel Forensic Workbench", layout="wide")

st.title("Ultimate Fuel Forensic Workbench")
st.markdown("**Role**: Expert Data Forensic Engineer  \n**Task**: Reconcile fuel station records (Ligo, Shift, and MPesa) with manual entry and variance analysis.")

# ---------------------------------------------------------
# 1. DATA INPUTS
# ---------------------------------------------------------
st.sidebar.header("Data Inputs")
ligo_file = st.sidebar.file_uploader("Upload Ligo Report (CSV)", type="csv")
shift_file = st.sidebar.file_uploader("Upload Shift Report (CSV)", type="csv")
mpesa_file = st.sidebar.file_uploader("Upload MPesa Report (CSV)", type="csv")
pause_after_reconcile = st.sidebar.checkbox(
    "Pause in debugger after reconciliation",
    value=False,
    help="When running app.py under the Python debugger, pause after the reconciliation tables are built so you can inspect the data in the debug visualizer."
)

if ligo_file and shift_file and mpesa_file:
    upload_fingerprint = (
        getattr(ligo_file, 'name', ''), getattr(ligo_file, 'size', 0),
        getattr(shift_file, 'name', ''), getattr(shift_file, 'size', 0),
        getattr(mpesa_file, 'name', ''), getattr(mpesa_file, 'size', 0)
    )

    # Read the data
    df_ligo = pd.read_csv(ligo_file)
    df_shift = pd.read_csv(shift_file)
    df_mpesa = pd.read_csv(mpesa_file)

    # Clean headers just in case of trailing spaces
    df_ligo.columns = df_ligo.columns.str.strip()
    df_shift.columns = df_shift.columns.str.strip()
    df_mpesa.columns = df_mpesa.columns.str.strip()

    # Clean Ligo: Remove rows where Transaction ID is empty
    if 'Transaction ID' in df_ligo.columns:
        df_ligo = df_ligo.dropna(subset=['Transaction ID'])
    
    # Prep Ligo: Add a new empty column: Physical_Invoice_No
    if 'Physical_Invoice_No' not in df_ligo.columns:
        df_ligo['Physical_Invoice_No'] = ""

    # Build a stable row key so saved Physical_Invoice_No values can be restored to exact rows.
    if 'Transaction ID' in df_ligo.columns:
        tx_series = df_ligo['Transaction ID'].fillna('').astype(str).str.strip()
        tx_series = tx_series.str.replace(r'\.0+$', '', regex=True)
        tx_series = tx_series.where(tx_series != '', 'ROW')
        tx_dup_idx = df_ligo.groupby(tx_series).cumcount().astype(str)
        df_ligo[LIGO_ROW_KEY_COL] = tx_series + "#" + tx_dup_idx
    else:
        df_ligo[LIGO_ROW_KEY_COL] = "ROW#" + df_ligo.index.astype(str)

    # Resolve and persist the on-disk path once per unique filename.
    uploaded_ligo_name = getattr(ligo_file, 'name', '')
    if st.session_state.get('ligo_source_path_name') != uploaded_ligo_name:
        resolved = _resolve_uploaded_ligo_path(ligo_file)
        st.session_state['ligo_source_path'] = resolved
        st.session_state['ligo_source_path_name'] = uploaded_ligo_name

    # Only reset working copy when the uploaded FILENAME changes (not on file-size
    # change, which happens after we save Physical_Invoice_No into the CSV).
    working_name_key = 'active_upload_name'
    if (
        'df_ligo_working' not in st.session_state
        or st.session_state.get(working_name_key) != uploaded_ligo_name
        or LIGO_ROW_KEY_COL not in st.session_state['df_ligo_working'].columns
    ):
        st.session_state['df_ligo_working'] = df_ligo.copy()
        st.session_state[working_name_key] = uploaded_ligo_name
        st.session_state['active_upload_fingerprint'] = upload_fingerprint

    # Sidebar: show / allow override of the Ligo save path.
    detected_path = st.session_state.get('ligo_source_path') or ''
    editable_path = st.sidebar.text_input(
        "Ligo CSV save path",
        value=detected_path,
        key='ligo_path_input',
        help="Auto-detected from uploaded filename. Edit if needed."
    )
    if editable_path != detected_path:
        st.session_state['ligo_source_path'] = editable_path

    # Download button always reads current session state (backup).
    try:
        _dl_df = st.session_state['df_ligo_working'].copy()
        if LIGO_ROW_KEY_COL in _dl_df.columns:
            _dl_df = _dl_df.drop(columns=[LIGO_ROW_KEY_COL])
        if 'Physical_Invoice_No' in _dl_df.columns:
            _dl_df['Physical_Invoice_No'] = _dl_df['Physical_Invoice_No'].fillna('').astype(str).str.strip().replace({'nan': '', 'None': ''})
        st.sidebar.download_button("Download edited Ligo CSV", data=_dl_df.to_csv(index=False).encode('utf-8'), file_name='ligo_edits_saved.csv', mime='text/csv')
    except Exception:
        pass

    # Clean Shift: Remove rows where Invoice is empty
    if 'Invoice' in df_shift.columns:
        df_shift = df_shift.dropna(subset=['Invoice'])
    # If 'Rate' column was lost in parsing, try to recover/rename the rightmost unnamed/numeric column to 'Rate'
    if 'Rate' not in df_shift.columns:
        # candidate unnamed columns (e.g., 'Unnamed: 6') or empty-string names
        candidates = [col for col in df_shift.columns if (str(col).strip()=='' or str(col).lower().startswith('unnamed'))]
        cand = None
        if candidates:
            cand = candidates[-1]
        else:
            # fallback: pick the last column
            cand = df_shift.columns[-1]
        try:
            ser = pd.to_numeric(df_shift[cand].astype(str).str.replace(r'[^0-9.-]','', regex=True), errors='coerce')
            if ser.notna().sum() > 0:
                df_shift = df_shift.rename(columns={cand: 'Rate'})
                st.sidebar.info(f"Renamed Shift column '{cand}' to 'Rate'.")
            else:
                # still rename as user requested
                df_shift = df_shift.rename(columns={cand: 'Rate'})
                st.sidebar.info(f"Forced rename of Shift column '{cand}' to 'Rate'.")
        except Exception:
            try:
                df_shift = df_shift.rename(columns={cand: 'Rate'})
                st.sidebar.info(f"Forced rename of Shift column '{cand}' to 'Rate'.")
            except Exception:
                pass

    # Drop trailing empty columns (often produced by malformed CSVs) after 'Rate'
    try:
        if 'Rate' in df_shift.columns:
            rate_idx = list(df_shift.columns).index('Rate')
            trailing = list(df_shift.columns)[rate_idx+1:]
        else:
            trailing = list(df_shift.columns)

        cols_to_drop = []
        for col in trailing:
            ss = df_shift[col].astype(str).str.strip()
            # Treat 'nan' and empty strings as empty
            ss_clean = ss.replace('nan', '').replace('None', '').str.strip()
            if not ss_clean.astype(bool).any():
                cols_to_drop.append(col)

        if cols_to_drop:
            df_shift = df_shift.drop(columns=cols_to_drop)
            st.sidebar.info(f"Dropped {len(cols_to_drop)} empty Shift column(s) after 'Rate'.")
    except Exception:
        pass

    # Preserve original Shift columns order for display in reconciliation
    original_shift_cols = df_shift.columns.tolist()

    # ---------------------------------------------------------
    # DASHBOARD SUMMARY
    # ---------------------------------------------------------
    st.header("📊 Dashboard Summary")
    
    shift_liters_col = 'Liters' if 'Liters' in df_shift.columns else df_shift.columns[0]
    ligo_qty_col = 'Quantity' if 'Quantity' in df_ligo.columns else df_ligo.columns[0]
    
    total_shift_liters = pd.to_numeric(df_shift[shift_liters_col], errors='coerce').sum()
    total_ligo_qty = pd.to_numeric(df_ligo[ligo_qty_col], errors='coerce').sum()
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Liters in Shift", f"{total_shift_liters:,.2f} L")
    col2.metric("Total Ligo Quantity", f"{total_ligo_qty:,.2f} L")
    
    variance_val = total_shift_liters - total_ligo_qty
    col3.metric("Shift vs Ligo Variance", f"{variance_val:,.2f} L", delta=f"{variance_val:,.2f}", delta_color="inverse")
    
    if 'Pump' in df_ligo.columns:
        st.markdown("#### Ligo Quantity by Pump")
        df_temp = df_ligo.copy()
        df_temp[ligo_qty_col] = pd.to_numeric(df_temp[ligo_qty_col], errors='coerce').fillna(0)
        pump_summary = df_temp.groupby("Pump")[ligo_qty_col].sum().reset_index()
        # Ensure Pump ID is a string for plotting categorical data
        pump_summary["Pump"] = "Pump " + pump_summary["Pump"].astype(str)
        
        c1, c2 = st.columns([2, 1])
        with c1:
            st.bar_chart(data=pump_summary, x="Pump", y=ligo_qty_col, use_container_width=True)
        with c2:
            st.dataframe(pump_summary, use_container_width=True, hide_index=True)

    st.divider()

    # ---------------------------------------------------------
    # 2. STEP 1: THE MANUAL KEY-IN (LIGO MAPPER)
    # ---------------------------------------------------------
    st.header("Step 1: The Manual Key-In (Ligo Mapper)")
    st.write("You can double-click cells to map `Physical_Invoice_No`, correct `Quantity` and `Pump`, or add bulk manual entries below.")

    # Manual bulk entry area: one entry per line -> Invoice,Quantity,Pump
    st.subheader("Manual Bulk Entry")
    st.write("Enter lines in the format: `Invoice,Quantity,Pump`. One entry per line. Example: `INV123,10,Pump1`")
    manual_text = st.text_area("Manual entries (Invoice,Quantity,Pump)", height=120, key='manual_text')
    if st.button("Add Manual Entries"):
        lines = [l.strip() for l in manual_text.splitlines() if l.strip()]
        rows = []
        for ln in lines:
            parts = [p.strip() for p in ln.split(',')]
            if len(parts) >= 2:
                inv = parts[0]
                try:
                    qty = float(parts[1]) if parts[1] != '' else 0
                except Exception:
                    qty = 0
                pump = parts[2] if len(parts) >=3 else ''
                rows.append({'Physical_Invoice_No':inv,'Quantity':qty,'Pump':pump})
        if rows:
            df_new = pd.DataFrame(rows)
            # assign stable keys to newly added manual rows
            if LIGO_ROW_KEY_COL not in st.session_state['df_ligo_working'].columns:
                st.session_state['df_ligo_working'][LIGO_ROW_KEY_COL] = "ROW#" + st.session_state['df_ligo_working'].index.astype(str)
            existing_keys = set(st.session_state['df_ligo_working'][LIGO_ROW_KEY_COL].fillna('').astype(str))
            manual_keys = []
            manual_idx = 1
            for _ in range(len(df_new)):
                candidate = f"MANUAL#{manual_idx}"
                while candidate in existing_keys:
                    manual_idx += 1
                    candidate = f"MANUAL#{manual_idx}"
                manual_keys.append(candidate)
                existing_keys.add(candidate)
                manual_idx += 1
            df_new[LIGO_ROW_KEY_COL] = manual_keys
            # ensure expected columns exist in working df
            for c in df_new.columns:
                if c not in st.session_state['df_ligo_working'].columns:
                    st.session_state['df_ligo_working'][c] = ""
            st.session_state['df_ligo_working'] = pd.concat([st.session_state['df_ligo_working'], df_new], ignore_index=True)
            st.success(f"Added {len(df_new)} manual entries to working Ligo dataset.")

    # Render from a copy so normalization does not mutate persisted state on every rerun.
    ligo_work = st.session_state['df_ligo_working'].copy()
    if 'Pump' in ligo_work.columns:
        ligo_work['Pump'] = ligo_work['Pump'].fillna('').astype(str)
    else:
        ligo_work['Pump'] = ''
    if 'Quantity' in ligo_work.columns:
        ligo_work['Quantity'] = pd.to_numeric(ligo_work['Quantity'], errors='coerce').fillna(0)
    else:
        ligo_work['Quantity'] = 0
    ligo_qty_col_edit = 'Quantity' if 'Quantity' in ligo_work.columns else ligo_work.columns[0]
    ligo_pump_col_edit = 'Pump' if 'Pump' in ligo_work.columns else ligo_work.columns[0]

    # AgGrid editor.
    # MODEL_CHANGED: Python receives updated data when a cell value is committed
    # (Enter / click away). reload_data=False keeps the grid stable between reruns.
    # We store each MODEL_CHANGED payload in ligo_grid_buffer so the Save button
    # always has the freshest edits regardless of subsequent reruns.
    display_cols = [col for col in ligo_work.columns if col != LIGO_ROW_KEY_COL]
    ligo_display = ligo_work[display_cols].copy()

    gb = GridOptionsBuilder.from_dataframe(ligo_display)
    gb.configure_default_column(editable=False, resizable=True, sortable=True, filter=True, wrapText=False)
    gb.configure_column("Physical_Invoice_No", editable=True, cellStyle={"backgroundColor": "#fffef0"})
    gb.configure_column(ligo_qty_col_edit, editable=True, type=["numericColumn"])
    gb.configure_column(ligo_pump_col_edit, editable=True)
    gb.configure_selection(selection_mode='single', use_checkbox=False)
    grid_options = gb.build()

    grid_response = AgGrid(
        ligo_display,
        gridOptions=grid_options,
        data_return_mode=DataReturnMode.AS_INPUT,
        update_mode=GridUpdateMode.MODEL_CHANGED,
        reload_data=False,
        height=400,
        fit_columns_on_grid_load=False,
        allow_unsafe_jscode=True,
        custom_css={
            ".ag-row-hover": {"background-color": "#ddeeff !important"},
            ".ag-row-selected": {"background-color": "#fff3cd !important"},
            ".ag-cell-focus": {"border": "2px solid #0078d4 !important"},
        },
        key='ligo_aggrid_editor',
        use_container_width=True,
    )

    # Every time AgGrid sends back data (MODEL_CHANGED), buffer it.
    # This means ligo_grid_buffer always has the latest edited state.
    _returned = grid_response['data']
    if _returned is not None:
        _as_df = _returned.copy() if isinstance(_returned, pd.DataFrame) else pd.DataFrame(_returned)
        if not _as_df.empty:
            st.session_state['ligo_grid_buffer'] = _as_df

    # Show the resolved save path clearly so user can verify before clicking save.
    _cur_save_path = st.session_state.get('ligo_source_path', '').strip()
    if _cur_save_path and Path(_cur_save_path).exists():
        st.info(f"Will save to: `{_cur_save_path}`")
    elif _cur_save_path:
        st.warning(f"Path set but file not found: `{_cur_save_path}` — check the path in the sidebar.")
    else:
        st.warning("Could not auto-detect Ligo file path. Paste the full path in the sidebar field, e.g.: `/media/izdixit/HIKSEMI/forensic/bonje/the_algorithmic/data_csv/ligo_20_03_N.csv`")

    save_status = st.empty()

    if st.button("Save Changes to Ligo File", type="primary"):
        # Use the buffered grid data (always the latest committed edits).
        raw = st.session_state.get('ligo_grid_buffer')
        if raw is None:
            save_status.error("No grid data captured yet. Edit at least one cell (press Enter to commit), then click Save.")
            st.stop()
        validated_df = raw.copy() if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)

        # Step 2: re-attach internal row-key column by index alignment
        if LIGO_ROW_KEY_COL in st.session_state['df_ligo_working'].columns:
            validated_df = validated_df.reset_index(drop=True)
            validated_df[LIGO_ROW_KEY_COL] = (
                st.session_state['df_ligo_working'].reset_index(drop=True)[LIGO_ROW_KEY_COL]
            )

        # Step 3: validate / clean
        if 'Physical_Invoice_No' in validated_df.columns:
            validated_df['Physical_Invoice_No'] = (
                validated_df['Physical_Invoice_No'].fillna('').astype(str).str.strip()
            )
            validated_df['Physical_Invoice_No'] = validated_df['Physical_Invoice_No'].replace({'nan': '', 'None': ''})

        if 'Quantity' in validated_df.columns:
            validated_df['Quantity'] = pd.to_numeric(validated_df['Quantity'], errors='coerce').fillna(0)

        if 'Pump' in validated_df.columns:
            validated_df['Pump'] = validated_df['Pump'].fillna('').astype(str)

        # Step 4: persist to session state
        st.session_state['df_ligo_working'] = validated_df
        st.session_state['last_ligo_autosave'] = pd.Timestamp.now().strftime('%H:%M:%S')

        # Step 5: write to file immediately, same rerun, same data
        export_df = validated_df.copy()
        if LIGO_ROW_KEY_COL in export_df.columns:
            export_df = export_df.drop(columns=[LIGO_ROW_KEY_COL])
        if 'Physical_Invoice_No' in export_df.columns:
            export_df['Physical_Invoice_No'] = export_df['Physical_Invoice_No'].fillna('').astype(str).str.strip().replace({'nan': '', 'None': ''})

        file_path = st.session_state.get('ligo_source_path', '').strip()
        if not file_path:
            # Last-resort: try to find the file now by uploaded filename.
            file_path = _resolve_uploaded_ligo_path(ligo_file) or ''
            if file_path:
                st.session_state['ligo_source_path'] = file_path

        if file_path:
            try:
                target = Path(file_path)
                if target.exists():
                    export_df.to_csv(target, index=False)
                    save_status.success(f"Written to file: `{file_path}` at {st.session_state['last_ligo_autosave']}")
                else:
                    save_status.error(f"File does not exist: `{file_path}` — paste the correct path in the sidebar.")
            except Exception as write_err:
                save_status.error(f"File write failed: {write_err}")
        else:
            save_status.error("No file path found. Paste the full path in the Ligo CSV save path field in the sidebar.")
    elif st.session_state.get('last_ligo_autosave'):
        save_status.caption(f"Last saved at {st.session_state['last_ligo_autosave']}.")

    # Always work from persisted state.
    df_ligo_edited = st.session_state['df_ligo_working'].copy()

    # ---------------------------------------------------------
    # 3. STEP 2: THE FORENSIC ALGORITHM (JOINS & VARIANCE)
    # ---------------------------------------------------------
    process_clicked = st.button("Process & Reconcile")
    if process_clicked:
        st.session_state['reconcile_ready'] = True

    if process_clicked or st.session_state.get('reconcile_ready', False):
        st.header("Step 2: Reconciliation Master Table")
        
        with st.spinner("Executing Forensic Algorithm..."):
            # Ensure invoice keys and numeric columns are normalized before matching.
            df_ligo_edited['Physical_Invoice_No'] = df_ligo_edited['Physical_Invoice_No'].apply(_normalize_invoice_value)
            
            # Filter out unmatched Ligo rows
            df_ligo_mapped = df_ligo_edited[df_ligo_edited['Physical_Invoice_No'] != ""].copy()

            # Resolve Shift key columns once so later diagnostics/joins can reuse them.
            shift_inv_col = 'Invoice' if 'Invoice' in df_shift.columns else df_shift.columns[0]
            shift_liters_col = 'Liters' if 'Liters' in df_shift.columns else df_shift.columns[0]
            shift_amt_col = 'Amount' if 'Amount' in df_shift.columns else df_shift.columns[0]

            # Identify column names securely
            ligo_qty_col = 'Quantity' if 'Quantity' in df_ligo_mapped.columns else df_ligo_mapped.columns[0]
            ligo_time_col = 'Time' if 'Time' in df_ligo_mapped.columns else df_ligo_mapped.columns[0]
            ligo_pump_col = 'Pump' if 'Pump' in df_ligo_mapped.columns else df_ligo_mapped.columns[0]
            
            df_ligo_mapped[ligo_qty_col] = _to_numeric_series(df_ligo_mapped[ligo_qty_col])
            df_ligo_mapped['Ligo_Invoice_Key'] = df_ligo_mapped['Physical_Invoice_No'].apply(_normalize_invoice_value)
            df_ligo_mapped['Ligo_Match_Component'] = df_ligo_mapped.apply(
                lambda row: f"Pump {_normalize_text(row.get(ligo_pump_col))}: {row[ligo_qty_col]:,.2f} L"
                if _normalize_text(row.get(ligo_pump_col))
                else f"{row[ligo_qty_col]:,.2f} L",
                axis=1,
            )

            # --- Aggregate Ligo by physical invoice mapped to Shift invoice ---
            agg_ligo = df_ligo_mapped.groupby('Ligo_Invoice_Key').agg(
                Ligo_Matched_Qty=(ligo_qty_col, 'sum'),
                Ligo_Match_Details=('Ligo_Match_Component', lambda x: ' | '.join([val for val in x if _normalize_text(val)])),
                Ligo_Pumps=(ligo_pump_col, _join_unique),
                Ligo_Times=(ligo_time_col, _join_unique),
                Ligo_Tx_Count=('Ligo_Invoice_Key', 'count')
            ).reset_index()

            # --- Aggregate MPesa ---
            mpesa_amt_col = 'Amount Paid' if 'Amount Paid' in df_mpesa.columns else (df_mpesa.columns[-1] if len(df_mpesa.columns)>0 else df_mpesa.columns[0])
            mpesa_time_col = 'Completion Time' if 'Completion Time' in df_mpesa.columns else (df_mpesa.columns[1] if len(df_mpesa.columns)>1 else df_mpesa.columns[0])

            # Find an invoice-like column in MPesa (accepts 'Invoice', 'Invoice No', etc.)
            mpesa_inv_cols = [col for col in df_mpesa.columns if 'Invoice' in col or 'invoice' in col or 'Invoice No' in col]
            mpesa_inv_col = mpesa_inv_cols[0] if mpesa_inv_cols else df_mpesa.columns[0]

            # Determine best amount column: prefer 'Paid In' then 'Amount Paid'
            amt_candidates = [c for c in df_mpesa.columns if c.lower().strip() in ('paid in','amount paid','paid','amount','paidin')]
            if 'Paid In' in df_mpesa.columns:
                chosen_amt_col = 'Paid In'
            elif 'Paid In'.lower() in [c.lower() for c in df_mpesa.columns]:
                # handle variants like ' Paid In '
                for c in df_mpesa.columns:
                    if c.lower().strip()=='paid in':
                        chosen_amt_col = c
                        break
            elif 'Amount Paid' in df_mpesa.columns:
                chosen_amt_col = 'Amount Paid'
            elif amt_candidates:
                chosen_amt_col = amt_candidates[0]
            else:
                chosen_amt_col = mpesa_amt_col

            # create a cleaned numeric amount column `mpesa_amount` from the chosen candidate
            df_mpesa['mpesa_amount'] = _to_numeric_series(df_mpesa[chosen_amt_col])
            # If mpesa_amount is all zero, try fallback to mpesa_amt_col
            if df_mpesa['mpesa_amount'].abs().sum() < 0.0001 and mpesa_amt_col in df_mpesa.columns and mpesa_amt_col!=chosen_amt_col:
                df_mpesa['mpesa_amount'] = _to_numeric_series(df_mpesa[mpesa_amt_col])

            df_mpesa['MPesa_Invoice_Key'] = df_mpesa[mpesa_inv_col].apply(_normalize_invoice_value)
            df_mpesa['parsed_invoices'] = df_mpesa[mpesa_inv_col].apply(_extract_invoice_tokens)
            df_mpesa_expl = df_mpesa.explode('parsed_invoices')
            df_mpesa_expl['MPesa_Invoice_Key'] = df_mpesa_expl['parsed_invoices'].apply(_normalize_invoice_value)
            df_mpesa_expl = df_mpesa_expl[df_mpesa_expl['MPesa_Invoice_Key'] != ''].copy()

            agg_mpesa = df_mpesa_expl.groupby('MPesa_Invoice_Key').agg(
                MPesa_Matched_Amount=('mpesa_amount', 'sum'),
                MPesa_Tx_Count=('MPesa_Invoice_Key', 'count'),
                MPesa_Times=(mpesa_time_col, _join_unique)
            ).reset_index()

            # --- Master Merge ---
            # Shift conversions
            df_shift[shift_inv_col] = df_shift[shift_inv_col].apply(_normalize_invoice_value)
            df_shift[shift_liters_col] = _to_numeric_series(df_shift[shift_liters_col])
            df_shift[shift_amt_col] = _to_numeric_series(df_shift[shift_amt_col])

            # Perform Joins
            master_df = df_shift.copy()
            master_df['Invoice_Key'] = master_df[shift_inv_col].apply(_normalize_invoice_value)
            master_df = pd.merge(master_df, agg_ligo, left_on='Invoice_Key', right_on='Ligo_Invoice_Key', how='left')
            master_df = pd.merge(master_df, agg_mpesa, left_on='Invoice_Key', right_on='MPesa_Invoice_Key', how='left')

            # Fill NaNs from missed joins
            master_df['Ligo_Matched_Qty'] = master_df['Ligo_Matched_Qty'].fillna(0)
            master_df['MPesa_Matched_Amount'] = master_df['MPesa_Matched_Amount'].fillna(0)
            master_df['Ligo_Match_Details'] = master_df['Ligo_Match_Details'].fillna('')
            master_df['Ligo_Pumps'] = master_df['Ligo_Pumps'].fillna("")
            master_df['Ligo_Tx_Count'] = master_df['Ligo_Tx_Count'].fillna(0).astype(int)
            master_df['MPesa_Tx_Count'] = master_df['MPesa_Tx_Count'].fillna(0).astype(int)
            master_df['MPesa_Times'] = master_df['MPesa_Times'].fillna("")

            # Rename for variance calculation readability and output formatting
            master_df = master_df.rename(columns={
                shift_liters_col: 'Shift_Liters',
                shift_amt_col: 'Shift_Amount',
                shift_inv_col: 'Invoice'
            })

            # --- Variance Calculation ---
            # We treat variance as: Ligo (dispensed via manual mapping) minus Shift (recorded liters)
            master_df['Shift_vs_Ligo_Variance'] = (master_df['Shift_Liters'] - master_df['Ligo_Matched_Qty']).round(2)

            # Payment variance: Shift amount minus MPesa reported paid amount (positive = shift overpaid)
            master_df['Shift_vs_MPesa_Variance'] = (master_df['Shift_Amount'] - master_df['MPesa_Matched_Amount']).round(2)

            # --- Quick Match Flags ---
            master_df['In_Ligo'] = master_df['Ligo_Tx_Count'] > 0
            master_df['In_MPesa'] = master_df['MPesa_Tx_Count'] > 0
            master_df['Discrepancy_Flag'] = (
                (master_df['Shift_vs_Ligo_Variance'].abs() > 0.001)
                | (master_df['Shift_vs_MPesa_Variance'].abs() > 0.01)
            )

            # ---------------------------------------------------------
            # 4. UI OUTPUT
            # ---------------------------------------------------------
            # Show all original Shift columns (but use renamed names where applicable)
            converted_shift_cols = []
            for c in original_shift_cols:
                if c == shift_liters_col:
                    converted_shift_cols.append('Shift_Liters')
                elif c == shift_amt_col:
                    converted_shift_cols.append('Shift_Amount')
                elif c == shift_inv_col:
                    converted_shift_cols.append('Invoice')
                else:
                    converted_shift_cols.append(c)

            ligo_analysis_cols = [
                'Ligo_Matched_Qty', 'Shift_vs_Ligo_Variance', 'Ligo_Tx_Count',
                'Ligo_Match_Details', 'Ligo_Pumps', 'Ligo_Times', 'In_Ligo'
            ]
            mpesa_analysis_cols = [
                'MPesa_Matched_Amount', 'Shift_vs_MPesa_Variance', 'MPesa_Tx_Count',
                'MPesa_Times', 'In_MPesa'
            ]
            status_cols = ['Discrepancy_Flag']

            display_cols = converted_shift_cols + ligo_analysis_cols + mpesa_analysis_cols + status_cols
            # Extract final columns securely
            actual_display_cols = [col for col in display_cols if col in master_df.columns]
            final_output_df = master_df[actual_display_cols]

            if pause_after_reconcile and process_clicked:
                breakpoint()

            # Color-code Ligo and MPesa analysis separately and flag variances clearly.
            def highlight_focus_columns(row):
                styles = [''] * len(row)
                
                # Calculate row-level conditions first to determine overlay priority.
                has_ligo_variance = abs(float(row.get('Shift_vs_Ligo_Variance', 0) or 0)) > 0.001
                has_mpesa_variance = abs(float(row.get('Shift_vs_MPesa_Variance', 0) or 0)) > 0.01
                has_any_variance = has_ligo_variance or has_mpesa_variance
                has_multi_ligo = int(row.get('Ligo_Tx_Count', 0) or 0) > 1
                has_multi_mpesa = int(row.get('MPesa_Tx_Count', 0) or 0) > 1
                
                # Determine semi-transparent row overlay (with priority: variance > multi_ligo > multi_mpesa).
                # Use very light overlays so column colors remain visible underneath.
                row_overlay = ''
                if has_any_variance:
                    row_overlay = '; box-shadow: inset 0 0 0 9999px rgba(239, 68, 68, 0.08)'  # red overlay, very light
                elif has_multi_ligo:
                    row_overlay = '; box-shadow: inset 0 0 0 9999px rgba(217, 119, 6, 0.07)'   # amber overlay, very light
                elif has_multi_mpesa:
                    row_overlay = '; box-shadow: inset 0 0 0 9999px rgba(2, 132, 199, 0.07)'   # blue overlay, very light
                
                for col in row.index:
                    idx = row.index.get_loc(col)
                    if col in converted_shift_cols:
                        styles[idx] = 'background-color: #f6f1e8' + row_overlay
                    elif col in ligo_analysis_cols:
                        styles[idx] = 'background-color: #fff4cc' + row_overlay
                    elif col in mpesa_analysis_cols:
                        styles[idx] = 'background-color: #dff1ff' + row_overlay
                    elif col in status_cols:
                        styles[idx] = 'background-color: #f2e8ff' + row_overlay

                if 'Shift_vs_Ligo_Variance' in row.index and abs(row['Shift_vs_Ligo_Variance']) > 0.001:
                    idx = row.index.get_loc('Shift_vs_Ligo_Variance')
                    styles[idx] = styles[idx] + '; color: #b42318; font-weight: bold'

                if 'Shift_vs_MPesa_Variance' in row.index and abs(row['Shift_vs_MPesa_Variance']) > 0.01:
                    idx = row.index.get_loc('Shift_vs_MPesa_Variance')
                    styles[idx] = styles[idx] + '; color: #0c4a6e; font-weight: bold'

                if 'Discrepancy_Flag' in row.index and row['Discrepancy_Flag']:
                    idx = row.index.get_loc('Discrepancy_Flag')
                    styles[idx] = styles[idx] + '; color: #7c2d12; font-weight: bold'
                return styles

            styled_df = final_output_df.style.format({
                'Shift_Liters': '{:,.2f}',
                'Shift_Amount': '{:,.2f}',
                'Ligo_Matched_Qty': '{:,.2f}',
                'Shift_vs_Ligo_Variance': '{:,.2f}',
                'MPesa_Matched_Amount': '{:,.2f}',
                'Shift_vs_MPesa_Variance': '{:,.2f}',
            }, na_rep='').apply(highlight_focus_columns, axis=1)

            st.caption(
                '**Row Highlighting:** Red tint = variance detected · Amber tint = 2+ Ligo transactions · Blue tint = 2+ MPesa transactions. '
                'Column zones: Shift (neutral), Ligo (amber), MPesa (blue).'
            )

            st.dataframe(styled_df, use_container_width=True, height=500)

            # --- Diagnostics: unmatched manual Ligo mappings and MPesa invoices ---
            # Ligo mappings that don't appear in Shift
            try:
                shift_invoices = set(master_df['Invoice_Key'].astype(str).str.strip())
                ligo_only = agg_ligo[~agg_ligo['Ligo_Invoice_Key'].astype(str).isin(shift_invoices)].copy()
                mpesa_only = agg_mpesa[~agg_mpesa['MPesa_Invoice_Key'].astype(str).isin(shift_invoices)].copy()
                if not ligo_only.empty:
                    st.markdown("#### ⚠️ Ligo mapped invoices not found in Shift")
                    st.dataframe(ligo_only, use_container_width=True, height=200)
                if not mpesa_only.empty:
                    st.markdown("#### ⚠️ MPesa invoices not found in Shift")
                    st.dataframe(mpesa_only, use_container_width=True, height=200)
            except Exception:
                pass

            # ---------------------------------------------------------
            # RECONCILIATION MAP (visual summary button)
            # ---------------------------------------------------------
            if 'recon_map_open' not in st.session_state:
                st.session_state['recon_map_open'] = True

            with st.expander("📊 View Reconciliation Map", expanded=st.session_state.get('recon_map_open', True)):
                # Keep map open across reruns triggered by widget changes (e.g., invoice selectbox).
                st.session_state['recon_map_open'] = True
                try:
                    import plotly.graph_objects as go
                    _plotly_ok = True
                except ImportError:
                    _plotly_ok = False
                    st.warning("plotly is not installed. Run: `pip install plotly`")

                _n_total = len(final_output_df)
                _in_ligo  = final_output_df.get('In_Ligo',  pd.Series([False] * _n_total)).fillna(False).astype(bool)
                _in_mpesa = final_output_df.get('In_MPesa', pd.Series([False] * _n_total)).fillna(False).astype(bool)
                _disc     = final_output_df.get('Discrepancy_Flag', pd.Series([False] * _n_total)).fillna(False).astype(bool)

                _n_ligo      = int(_in_ligo.sum())
                _n_mpesa     = int(_in_mpesa.sum())
                _n_both      = int((_in_ligo & _in_mpesa).sum())
                _n_ligo_only = _n_ligo  - _n_both
                _n_mpesa_only= _n_mpesa - _n_both
                _n_neither   = _n_total - _n_both - _n_ligo_only - _n_mpesa_only
                _n_disc      = int(_disc.sum())

                # KPI row
                kc1, kc2, kc3, kc4, kc5 = st.columns(5)
                kc1.metric("Shift Invoices", _n_total)
                kc2.metric("Matched in Ligo",  _n_ligo,  delta=f"{_n_total - _n_ligo} unmatched",  delta_color="inverse")
                kc3.metric("Matched in MPesa", _n_mpesa, delta=f"{_n_total - _n_mpesa} unmatched", delta_color="inverse")
                kc4.metric("Matched in Both",  _n_both)
                kc5.metric("⚠ Discrepancies", _n_disc,  delta_color="inverse")

                # Sankey: Shift → Ligo split → MPesa/neither
                if _plotly_ok:
                    _s_labels = [
                        f"Shift Invoices ({_n_total})",
                        f"✓ In Ligo ({_n_ligo})",
                        f"✗ Not in Ligo ({_n_total - _n_ligo})",
                        f"✓ Both Matched ({_n_both})",
                        f"Ligo Only ({_n_ligo_only})",
                        f"MPesa Only ({_n_mpesa_only})",
                        f"✗ Neither ({_n_neither})",
                    ]
                    _s_colors = ["#4e6bff", "#f59e0b", "#64748b", "#22c55e", "#fbbf24", "#38bdf8", "#ef4444"]
                    _raw_links = [
                        (0, 1, _n_ligo,               "rgba(245,158,11,0.40)"),
                        (0, 2, _n_total - _n_ligo,    "rgba(100,116,139,0.30)"),
                        (1, 3, _n_both,               "rgba(34,197,94,0.40)"),
                        (1, 4, _n_ligo_only,          "rgba(251,191,36,0.35)"),
                        (2, 5, _n_mpesa_only,         "rgba(56,189,248,0.40)"),
                        (2, 6, _n_neither,            "rgba(239,68,68,0.35)"),
                    ]
                    _valid = [(s, t, v, c) for s, t, v, c in _raw_links if v > 0]
                    if _valid:
                        _ls, _lt, _lv, _lc = zip(*_valid)
                    else:
                        _ls, _lt, _lv, _lc = [], [], [], []
                    _fig_sank = go.Figure(data=[go.Sankey(
                        arrangement="snap",
                        node=dict(
                            pad=24, thickness=28,
                            label=_s_labels, color=_s_colors,
                            line=dict(color="#0b1220", width=1),
                        ),
                        link=dict(source=list(_ls), target=list(_lt), value=list(_lv), color=list(_lc)),
                    )])
                    _fig_sank.update_layout(
                        title_text="Invoice Flow: Shift → Ligo → MPesa",
                        font=dict(size=13, color="#f1f5f9"),
                        paper_bgcolor="#0d1b2a", plot_bgcolor="#0d1b2a",
                        height=400, margin=dict(l=10, r=10, t=48, b=10),
                    )
                    st.plotly_chart(_fig_sank, use_container_width=True)

                st.divider()
                _map_left, _map_right = st.columns([1, 2])

                with _map_left:
                    st.markdown("**Category Breakdown**")
                    _cat_df = pd.DataFrame({
                        "Category": ["Both Matched", "Ligo Only", "MPesa Only", "Neither"],
                        "Invoices":  [_n_both, _n_ligo_only, _n_mpesa_only, _n_neither],
                    })
                    st.dataframe(_cat_df, hide_index=True, use_container_width=True)
                    if _plotly_ok:
                        _fig_bar = go.Figure(data=[go.Bar(
                            x=_cat_df["Category"], y=_cat_df["Invoices"],
                            marker_color=["#22c55e", "#f59e0b", "#38bdf8", "#ef4444"],
                            text=_cat_df["Invoices"], textposition="auto",
                        )])
                        _fig_bar.update_layout(
                            paper_bgcolor="#0d1b2a", plot_bgcolor="#0d1b2a",
                            font=dict(color="#f1f5f9", size=12),
                            margin=dict(l=4, r=4, t=24, b=4), height=240,
                            yaxis=dict(gridcolor="rgba(255,255,255,0.07)"),
                        )
                        st.plotly_chart(_fig_bar, use_container_width=True)

                with _map_right:
                    st.markdown("**Per-Invoice Match Overview**")
                    _match_ov = pd.DataFrame({
                        'Invoice':   final_output_df.get('Invoice', final_output_df.iloc[:, 0]).values,
                        'Shift L':   final_output_df.get('Shift_Liters',      pd.Series([0.0] * _n_total)).round(2).values,
                        'Ligo L':    final_output_df.get('Ligo_Matched_Qty',  pd.Series([0.0] * _n_total)).round(2).values,
                        'Ligo Txs':  final_output_df.get('Ligo_Tx_Count',     pd.Series([0]   * _n_total)).values,
                        'MPesa Txs': final_output_df.get('MPesa_Tx_Count',    pd.Series([0]   * _n_total)).values,
                        'Status': [
                            '✓ Both'   if l and m else
                            ('🟡 Ligo'  if l else
                            ('🔵 MPesa' if m else '✗ None'))
                            for l, m in zip(_in_ligo, _in_mpesa)
                        ],
                        '⚠': ['⚠' if d else '' for d in _disc],
                    })
                    st.dataframe(_match_ov, hide_index=True, use_container_width=True, height=360)

                # Detailed per-invoice logic map (replaces old variance-only chart)
                if _plotly_ok:
                    st.divider()
                    st.markdown("**Transaction Logic Map** — choose an invoice to see the reconciliation path and computed outcomes.")

                    _logic_cols = [
                        'Invoice', 'Shift_Liters', 'Shift_Amount', 'Ligo_Matched_Qty',
                        'MPesa_Matched_Amount', 'Ligo_Tx_Count', 'MPesa_Tx_Count',
                        'Shift_vs_Ligo_Variance', 'Shift_vs_MPesa_Variance',
                        'Discrepancy_Flag', 'Ligo_Match_Details', 'Ligo_Pumps',
                        'Ligo_Times', 'MPesa_Times'
                    ]
                    _logic_cols = [c for c in _logic_cols if c in final_output_df.columns]
                    _logic_df = final_output_df[_logic_cols].copy()
                    _logic_df['Invoice_str'] = _logic_df.get('Invoice', pd.Series([''] * len(_logic_df))).astype(str)
                    _logic_df = _logic_df.sort_values('Invoice_str', kind='stable').reset_index(drop=True)

                    if _logic_df.empty:
                        st.info("No invoice rows available for logic mapping.")
                    else:
                        _selected_invoice = st.selectbox(
                            "Invoice to map",
                            options=_logic_df['Invoice_str'].tolist(),
                            key='logic_map_invoice_selector',
                            help="Pick any invoice to visualize the logic that built this reconciliation row."
                        )

                        _row = _logic_df[_logic_df['Invoice_str'] == _selected_invoice].iloc[0]
                        _in_ligo = int(_row.get('Ligo_Tx_Count', 0)) > 0
                        _in_mpesa = int(_row.get('MPesa_Tx_Count', 0)) > 0
                        _is_disc = bool(_row.get('Discrepancy_Flag', False))

                        _labels = [
                            f"Invoice\n{_selected_invoice}",
                            f"Shift Liters\n{float(_row.get('Shift_Liters', 0)):.2f} L",
                            f"Shift Amount\n{float(_row.get('Shift_Amount', 0)):.2f}",
                            f"Ligo Tx Count\n{int(_row.get('Ligo_Tx_Count', 0))}",
                            f"Ligo Qty Matched\n{float(_row.get('Ligo_Matched_Qty', 0)):.2f} L",
                            f"MPesa Tx Count\n{int(_row.get('MPesa_Tx_Count', 0))}",
                            f"MPesa Amount Matched\n{float(_row.get('MPesa_Matched_Amount', 0)):.2f}",
                            f"Ligo Variance\n{float(_row.get('Shift_vs_Ligo_Variance', 0)):+.2f} L",
                            f"MPesa Variance\n{float(_row.get('Shift_vs_MPesa_Variance', 0)):+.2f}",
                            "Discrepancy Flag\nYES" if _is_disc else "Discrepancy Flag\nNO",
                        ]

                        _node_colors = [
                            "#4e6bff", "#f8fafc", "#f8fafc", "#f59e0b", "#f59e0b",
                            "#38bdf8", "#38bdf8", "#f97316", "#0ea5e9", "#ef4444" if _is_disc else "#22c55e"
                        ]

                        # Link values are structural (unitless), labels carry the numeric details.
                        _src = [0, 0, 0, 3, 5, 1, 4, 2, 6, 7, 8]
                        _dst = [1, 2, 3, 4, 6, 7, 7, 8, 8, 9, 9]
                        _val = [1] * len(_src)
                        _lnk_colors = [
                            "rgba(78,107,255,0.30)", "rgba(78,107,255,0.30)",
                            "rgba(245,158,11,0.30)", "rgba(245,158,11,0.35)",
                            "rgba(56,189,248,0.35)", "rgba(249,115,22,0.35)",
                            "rgba(249,115,22,0.35)", "rgba(14,165,233,0.35)",
                            "rgba(14,165,233,0.35)",
                            "rgba(239,68,68,0.40)" if _is_disc else "rgba(34,197,94,0.40)",
                            "rgba(239,68,68,0.40)" if _is_disc else "rgba(34,197,94,0.40)",
                        ]

                        _fig_logic = go.Figure(data=[go.Sankey(
                            arrangement="snap",
                            node=dict(
                                pad=20,
                                thickness=22,
                                label=_labels,
                                color=_node_colors,
                                line=dict(color="#0b1220", width=1),
                            ),
                            link=dict(source=_src, target=_dst, value=_val, color=_lnk_colors),
                        )])
                        _fig_logic.update_layout(
                            title="Invoice Reconciliation Logic Path",
                            paper_bgcolor="#0d1b2a",
                            plot_bgcolor="#0d1b2a",
                            font=dict(size=12, color="#f1f5f9"),
                            margin=dict(l=10, r=10, t=48, b=10),
                            height=430,
                        )
                        st.plotly_chart(_fig_logic, use_container_width=True)

                        _detail_table = pd.DataFrame(
                            {
                                "Field": [
                                    "Invoice", "Shift_Liters", "Shift_Amount", "Ligo_Matched_Qty",
                                    "MPesa_Matched_Amount", "Ligo_Tx_Count", "MPesa_Tx_Count",
                                    "Shift_vs_Ligo_Variance", "Shift_vs_MPesa_Variance",
                                    "In_Ligo", "In_MPesa", "Discrepancy_Flag",
                                    "Ligo_Match_Details", "Ligo_Pumps", "Ligo_Times", "MPesa_Times"
                                ],
                                "Value": [
                                    _selected_invoice,
                                    float(_row.get('Shift_Liters', 0)),
                                    float(_row.get('Shift_Amount', 0)),
                                    float(_row.get('Ligo_Matched_Qty', 0)),
                                    float(_row.get('MPesa_Matched_Amount', 0)),
                                    int(_row.get('Ligo_Tx_Count', 0)),
                                    int(_row.get('MPesa_Tx_Count', 0)),
                                    float(_row.get('Shift_vs_Ligo_Variance', 0)),
                                    float(_row.get('Shift_vs_MPesa_Variance', 0)),
                                    "Yes" if _in_ligo else "No",
                                    "Yes" if _in_mpesa else "No",
                                    "Yes" if _is_disc else "No",
                                    str(_row.get('Ligo_Match_Details', '')),
                                    str(_row.get('Ligo_Pumps', '')),
                                    str(_row.get('Ligo_Times', '')),
                                    str(_row.get('MPesa_Times', '')),
                                ]
                            }
                        )
                        st.dataframe(_detail_table, hide_index=True, use_container_width=True)

                        st.divider()
                        st.markdown("**Variance Deep Dive** — variance invoices only, with Shift/Ligo/MPesa values and transaction composition.")
                        _var_cols = [
                            'Invoice', 'Shift_Liters', 'Ligo_Matched_Qty', 'MPesa_Matched_Amount',
                            'Ligo_Tx_Count', 'MPesa_Tx_Count', 'Shift_vs_Ligo_Variance',
                            'Shift_vs_MPesa_Variance', 'Discrepancy_Flag', 'Ligo_Match_Details',
                            'Ligo_Pumps', 'Ligo_Times', 'MPesa_Times'
                        ]
                        _var_cols = [c for c in _var_cols if c in final_output_df.columns]
                        _var_df = final_output_df[_var_cols].copy()
                        _var_df['Invoice'] = _var_df.get('Invoice', pd.Series([''] * len(_var_df))).astype(str)
                        _var_df['Shift_vs_Ligo_Variance'] = pd.to_numeric(_var_df.get('Shift_vs_Ligo_Variance', 0), errors='coerce').fillna(0)
                        _var_df['Shift_vs_MPesa_Variance'] = pd.to_numeric(_var_df.get('Shift_vs_MPesa_Variance', 0), errors='coerce').fillna(0)
                        _var_df['Ligo_Tx_Count'] = pd.to_numeric(_var_df.get('Ligo_Tx_Count', 0), errors='coerce').fillna(0).astype(int)
                        _var_df['MPesa_Tx_Count'] = pd.to_numeric(_var_df.get('MPesa_Tx_Count', 0), errors='coerce').fillna(0).astype(int)
                        _var_df['multi_tx'] = _var_df['Ligo_Tx_Count'] >= 2

                        _var_only = _var_df[
                            (_var_df['Shift_vs_Ligo_Variance'].abs() > 0.001)
                            | (_var_df['Shift_vs_MPesa_Variance'].abs() > 0.01)
                        ].copy()

                        if _var_only.empty:
                            st.success("No variance rows found. Shift, Ligo, and MPesa are aligned for all invoices.")
                        else:
                            _sizes = ((_var_only['Ligo_Tx_Count'] + _var_only['MPesa_Tx_Count']).clip(lower=1) * 7).tolist()
                            _symbols = ['diamond' if mtx else 'circle' for mtx in _var_only['multi_tx'].tolist()]
                            _colors = ['#ef4444' if bool(v) else '#f59e0b' for v in _var_only.get('Discrepancy_Flag', pd.Series([False] * len(_var_only))).tolist()]
                            _hover = [
                                "<br>".join([
                                    f"Invoice: {inv}",
                                    f"Shift_Liters: {sl:,.2f}",
                                    f"Ligo_Matched_Qty: {lq:,.2f}",
                                    f"MPesa_Matched_Amount: {ma:,.2f}",
                                    f"Ligo_Tx_Count: {ltx}",
                                    f"MPesa_Tx_Count: {mtx}",
                                    f"Ligo Details: {ld}",
                                    f"Ligo Pumps: {lp}",
                                    f"Ligo Times: {lt}",
                                    f"MPesa Times: {mt}",
                                ])
                                for inv, sl, lq, ma, ltx, mtx, ld, lp, lt, mt in zip(
                                    _var_only['Invoice'],
                                    pd.to_numeric(_var_only.get('Shift_Liters', 0), errors='coerce').fillna(0),
                                    pd.to_numeric(_var_only.get('Ligo_Matched_Qty', 0), errors='coerce').fillna(0),
                                    pd.to_numeric(_var_only.get('MPesa_Matched_Amount', 0), errors='coerce').fillna(0),
                                    _var_only['Ligo_Tx_Count'],
                                    _var_only['MPesa_Tx_Count'],
                                    _var_only.get('Ligo_Match_Details', pd.Series([''] * len(_var_only))).astype(str),
                                    _var_only.get('Ligo_Pumps', pd.Series([''] * len(_var_only))).astype(str),
                                    _var_only.get('Ligo_Times', pd.Series([''] * len(_var_only))).astype(str),
                                    _var_only.get('MPesa_Times', pd.Series([''] * len(_var_only))).astype(str),
                                )
                            ]

                            _fig_var = go.Figure()
                            _fig_var.add_trace(go.Scatter(
                                x=_var_only['Shift_vs_Ligo_Variance'],
                                y=_var_only['Shift_vs_MPesa_Variance'],
                                mode='markers+text',
                                text=_var_only['Invoice'],
                                textposition='top center',
                                marker=dict(size=_sizes, color=_colors, symbol=_symbols, line=dict(color='#0b1220', width=1)),
                                hovertext=_hover,
                                hovertemplate='%{hovertext}<extra></extra>',
                                name='Variance Invoices'
                            ))
                            _fig_var.add_vline(x=0, line_color='rgba(148,163,184,0.6)', line_width=1)
                            _fig_var.add_hline(y=0, line_color='rgba(148,163,184,0.6)', line_width=1)
                            _fig_var.update_layout(
                                title='Variance Map: Shift vs Ligo and Shift vs MPesa (diamond = 2+ Ligo transactions)',
                                xaxis_title='Shift - Ligo Variance (Liters)',
                                yaxis_title='Shift - MPesa Variance (Amount)',
                                paper_bgcolor='#0d1b2a',
                                plot_bgcolor='#0d1b2a',
                                font=dict(size=12, color='#f1f5f9'),
                                margin=dict(l=10, r=10, t=56, b=10),
                                height=460,
                            )
                            st.plotly_chart(_fig_var, use_container_width=True)

                            _var_table_cols = [
                                'Invoice', 'Shift_Liters', 'Ligo_Matched_Qty', 'MPesa_Matched_Amount',
                                'Ligo_Tx_Count', 'MPesa_Tx_Count', 'Shift_vs_Ligo_Variance',
                                'Shift_vs_MPesa_Variance', 'Ligo_Match_Details'
                            ]
                            _var_table_cols = [c for c in _var_table_cols if c in _var_only.columns]
                            st.dataframe(
                                _var_only[_var_table_cols].sort_values(
                                    by=['Shift_vs_Ligo_Variance', 'Shift_vs_MPesa_Variance'],
                                    key=lambda s: s.abs() if s.name in ('Shift_vs_Ligo_Variance', 'Shift_vs_MPesa_Variance') else s,
                                    ascending=False
                                ),
                                hide_index=True,
                                use_container_width=True,
                                height=280,
                            )

                        st.divider()
                        st.markdown("**All Invoices Variance Overview** — includes invoices with and without variance.")
                        _all_cols = [
                            'Invoice', 'Shift_vs_Ligo_Variance', 'Shift_vs_MPesa_Variance',
                            'Ligo_Tx_Count', 'MPesa_Tx_Count', 'Discrepancy_Flag'
                        ]
                        _all_cols = [c for c in _all_cols if c in final_output_df.columns]
                        _all_df = final_output_df[_all_cols].copy()
                        _all_df['Invoice'] = _all_df.get('Invoice', pd.Series([''] * len(_all_df))).astype(str)
                        _all_df['Shift_vs_Ligo_Variance'] = pd.to_numeric(_all_df.get('Shift_vs_Ligo_Variance', 0), errors='coerce').fillna(0)
                        _all_df['Shift_vs_MPesa_Variance'] = pd.to_numeric(_all_df.get('Shift_vs_MPesa_Variance', 0), errors='coerce').fillna(0)
                        _all_df = _all_df.sort_values('Invoice', kind='stable')

                        _fig_all = go.Figure()
                        _fig_all.add_trace(go.Bar(
                            x=_all_df['Invoice'],
                            y=_all_df['Shift_vs_Ligo_Variance'],
                            name='Shift - Ligo Variance (L)',
                            marker_color=['#ef4444' if abs(v) > 0.001 else '#22c55e' for v in _all_df['Shift_vs_Ligo_Variance']],
                            opacity=0.8,
                        ))
                        _fig_all.add_trace(go.Scatter(
                            x=_all_df['Invoice'],
                            y=_all_df['Shift_vs_MPesa_Variance'],
                            name='Shift - MPesa Variance (Amount)',
                            mode='lines+markers',
                            marker=dict(color='#38bdf8', size=7),
                            line=dict(color='#38bdf8', width=2),
                            yaxis='y2',
                        ))
                        _fig_all.add_hline(y=0, line_color='rgba(148,163,184,0.6)', line_width=1)
                        _fig_all.update_layout(
                            barmode='overlay',
                            title='All Invoices: Variance Presence and Magnitude',
                            xaxis=dict(title='Invoice', tickangle=-45),
                            yaxis=dict(title='Shift - Ligo Variance (L)', gridcolor='rgba(255,255,255,0.07)'),
                            yaxis2=dict(
                                title='Shift - MPesa Variance (Amount)',
                                overlaying='y',
                                side='right',
                                showgrid=False,
                            ),
                            paper_bgcolor='#0d1b2a',
                            plot_bgcolor='#0d1b2a',
                            font=dict(size=12, color='#f1f5f9'),
                            margin=dict(l=10, r=10, t=56, b=10),
                            height=430,
                            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0),
                        )
                        st.plotly_chart(_fig_all, use_container_width=True)

            # Download CSV Button
            csv_data = final_output_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="Download Final Forensic Audit (CSV)",
                data=csv_data,
                file_name="forensic_audit_reconciliation.csv",
                mime="text/csv",
                key="download-csv"
            )

else:
    st.info("👋 Please upload your Ligo, Shift, and MPesa reports on the sidebar to begin the forensic analysis.")

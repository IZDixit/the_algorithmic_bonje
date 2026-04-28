# Suswa Shift vs 24hr Pump Reconciliation App — Features Guide

## ✅ Current Features

### 1. **Save to shift_report.csv Button** (Sidebar)

**Purpose**: Persist all enriched reconciliation data back to the original shift_report.csv file without rerunning the entire analysis.

**Location**: Sidebar → "💾 Save Results" section

**How to use**:
1. Upload Shift, 24hr Pump, and (optionally) MPesa CSV files
2. Run the reconciliation by viewing the dashboard
3. Click **"Save to shift_report.csv"** button
4. Confirmation message appears: ✅ Saved N rows to /path/to/shift_report.csv

**What gets saved**:
- All original shift columns
- Enriched columns: `Match_Count`, `Matched_Attendant`, `Matched_Pump`, `Matched_Nozzle`, `Matched_Date`, `Rate_Diff`
- MPesa columns: `MPesa_Match_Status`, `MPesa_Amount`, `MPesa_Variance`, `MPesa_Time`
- All manual pump allocations

**Note**: When MPesa is uploaded, the file path is auto-detected. If not uploaded, you may need to specify the path manually.

---

### 2. **Debug Visualizer Integration** (Sidebar Checkbox)

**Purpose**: Pause app execution at a critical point to inspect reconciliation dataframes in real-time using VS Code's debug visualizer panel.

**Location**: Sidebar → "Pause in debugger after reconciliation" checkbox

**How to use**:

#### Option A: Without Debugger (Normal)
- Checkbox is disabled by default → app runs normally
- Click through normally, no debugging

#### Option B: With VS Code Debugger

1. **Install the debug-visualizer extension** (already in your workspace):
   ```bash
   cd /media/izdixit/HIKSEMI/forensic/bonje/the_algorithmic/debug-visualizer-clone
   npm install
   npm run compile
   # Then in VS Code: Debug → "Run as VS Code Extension"
   ```

2. **Run app under debugger**:
   ```bash
   python -m debugpy.adapter --log-dir /tmp app.py
   # Or in VS Code: Debug → Start Debugging (configured for Python)
   ```

3. **In the app sidebar**:
   - Enable checkbox: ✓ "Pause in debugger after reconciliation"
   - Upload files and run reconciliation

4. **At breakpoint**:
   - VS Code pauses execution
   - Debug Visualizer panel (right sidebar) opens
   - You can inspect:
     - `df_result` — full reconciliation table
     - `agg_ligo` — aggregated Ligo matches
     - `agg_mpesa` — aggregated MPesa matches
     - `df_matches` — 24hr pump match candidates
     - All other working dataframes

5. **Inspect data**:
   - Type in search box: `df_result`
   - View rows, columns, data types
   - Drill down into nested data
   - Compare sync between different tables

6. **Resume execution**:
   - Press F5 or click "Continue" button
   - App renders normally with full results

---

### 3. **Manual Pump Allocation** (Interactive Table)

When a shift row matches **multiple pump transactions** (e.g., 3 pumps dispensed the same volume at the same price):

- Table appears: "🎯 Manual Pump Allocation"
- For each ambiguous row:
  - Shows: `INV NO.` | `Pump | Attendant | Nozzle` | `Volume @ Rate`
  - Dropdown: Select which pump to allocate
- Selection is tracked in session state
- Original concatenated details are preserved for audit trail

---

### 4. **Filters** (Expander)

Control what's displayed in the result table without affecting underlying data:

- **Invoice Category** — multiselect by payment method (Mpesa, Visa Card, etc.)
- **Match Status** — All, Matched only, Unmatched only
- **Minimum LTRS** — Show only rows where LTRS ≥ threshold

---

### 5. **Diagnostics** (Expandable Sections)

#### 24hr Transactions Without a Shift Match
- Pump activity not recorded in shift report
- Potential missing shift lines or pump test runs

#### MPesa Transactions Without a Shift Match
- MPesa payments not linked to shift invoices  
- May indicate invoice number mismatches or unrecorded sales

---

## 📊 Result Table Color Coding

- 🔵 **Light Blue** — MPesa matched (payment found)
- 🟢 **Light Green** — 24hr pump matched (pump transaction found)
- 🔴 **Light Red** — Unmatched (neither pump nor payment found)

---

## 🔄 Workflow: Typical Use Case

1. **Upload files** (sidebar)
   - Shift Report CSV
   - 24hr Pump Report CSV
   - MPesa Report CSV (optional)

2. **View dashboard** 
   - KPI metrics (total rows, coverage %)
   - Coverage chart by payment type

3. **Allocate ambiguous pump matches** (if any)
   - Use dropdown for rows with multiple candidates
   - Changes are session-local, not persisted until Save

4. **Review reconciliation table**
   - Apply filters if needed
   - Check color coding (blue/green/red)
   - Note variances in MPesa_Variance column

5. **Inspect diagnostics**
   - Expand "24hr Transactions..." to see unmatched pump activity
   - Expand "MPesa Transactions..." to see unmatched payments

6. **(Optional) Debug in visualizer**
   - Enable "Pause in debugger" checkbox
   - Re-run (reload app)
   - Hits breakpoint after KPI metrics
   - Inspect all dataframes in debug visualizer panel

7. **Save to shift_report.csv**
   - Click "Save to shift_report.csv" button
   - All enriched columns + allocations are written to disk
   - Upload the saved CSV next time to resume from enriched state

8. **Download (backup)**
   - Optional: Download as separate CSV export

---

## 📝 Notes

- **Session state** persists during app session (manual allocations, filters)
- **Saved state** persists across app restarts (written to shift_report.csv)
- **Debug visualizer** is optional; useful when investigating reconciliation logic
- **Save button** works even if MPesa file not uploaded (all columns still saved)
- **Breakpoint** only triggers if running under Python debugger; ignored otherwise

---

## 🚀 Running the App

```bash
source /home/izdixit/forensic_venv/bin/activate
streamlit run /media/izdixit/HIKSEMI/forensic/bonje/the_algorithmic/suswa_script/app.py
```

App will be available at: **http://localhost:8501** (or next available port)

---

## 🛠️ Troubleshooting

**"Shift file path not detected. Cannot save."**
- MPesa file was not auto-loaded or uploaded
- Manually specify path in sidebar before clicking Save

**"Error saving file: Permission denied"**
- Check file permissions on shift_report.csv
- Ensure CSV is not open in Excel or another program

**Breakpoint doesn't trigger**
- App must be running under Python debugger (not standalone)
- Ensure checkbox is enabled in sidebar
- Check terminal for `pdb>` prompt

**Debug visualizer panel not opening**
- Extension must be built: `npm run compile` in debug-visualizer-clone folder
- Ensure running as VS Code Extension (not standalone Python)


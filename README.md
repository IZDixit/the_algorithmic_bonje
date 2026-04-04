# Ultimate Fuel Forensic Workbench

A **forensic fuel reconciliation tool** built with Streamlit for reconciling Shift reports, Ligo dispenser logs, and MPesa payment records. Includes a VS Code debug visualizer extension for live DataFrame inspection during analysis.

## Overview

This application helps fuel station operators and forensic analysts reconcile three data sources:
- **Shift Reports**: Manual fuel shift records (invoice, liters, amount)
- **Ligo Logs**: Automated dispenser transaction records (pump, quantity, time)
- **MPesa Records**: Mobile payment confirmations (amount, time, invoice)

The tool performs intelligent multi-source joins, detects variances, and flags high-risk invoices for manual review. It includes detailed visualizations and transaction-level audit trails.

## Features

### Main App (Streamlit)
- **Ligo Mapper**: EditorGrid for manually mapping pump transactions to shift invoices
- **Forensic Algorithm**: Multi-source join with automatic variance detection
- **Reconciliation Master Table**: Color-coded output with row-level highlighting:
  - Red overlay: Variance detected (Shift ≠ Ligo or Shift ≠ MPesa)
  - Amber overlay: 2+ Ligo transactions on same invoice
  - Blue overlay: 2+ MPesa transactions on same invoice
- **Reconciliation Map**: Sankey flow diagram, KPI metrics, category breakdown
- **Transaction Logic Map**: Per-invoice deep dive with transaction composition details
- **Variance Analysis**:
  - Variance Deep Dive: X/Y scatter plot showing Shift vs Ligo vs MPesa relationships
  - All Invoices Overview: Bar + line chart across full dataset
- **CSV Export**: Download reconciliation results for external audit trail

### Debug Visualizer Extension (VS Code)
- Live DataFrame inspection during Streamlit debugging
- Quick-access buttons for key tables: `final_output_df`, `master_df`, `agg_ligo`, `agg_mpesa`, `df_shift`, `df_ligo_mapped`
- Sankey-style logic path graphs showing per-invoice reconciliation flow
- Auto-focus on reconciliation tables when breakpoint is hit
- One-click build + debug launch

## Installation

### Prerequisites
- Python 3.10+ (tested on 3.12)
- Node.js 18+ (for the VS Code extension)
- VS Code (optional, for debug visualizer)

### Setup

1. **Clone the repository**:
   ```bash
   git clone <your-repo-url>
   cd the_algorithmic
   ```

2. **Create and activate a Python virtual environment**:
   ```bash
   python3 -m venv ~/forensic_venv
   source ~/forensic_venv/bin/activate
   ```

3. **Install Python dependencies**:
   ```bash
   pip install -r script/requirements.txt
   ```

4. **Install VS Code extension dependencies** (optional):
   ```bash
   cd debug-visualizer-clone
   npm install
   npm run compile
   cd ..
   ```

## Usage

### Running the Streamlit App

```bash
source ~/forensic_venv/bin/activate
cd ~
streamlit run /media/izdixit/HIKSEMI/forensic/bonje/the_algorithmic/script/app.py
```

Then open [http://localhost:8501](http://localhost:8501) in your browser.

**Workflow**:
1. Upload your Ligo, Shift, and MPesa CSV files (sidebar)
2. (Optional) Enable "Pause in debugger after reconciliation" if using debug visualizer
3. Edit Ligo mappings in the **Step 1: Manual Key-In** grid (map pump transactions to invoices)
4. Click **Process & Reconcile** to run the forensic algorithm
5. Expand **View Reconciliation Map** to see Sankey, logic paths, and variance details
6. Review color-coded rows for variance and multi-transaction patterns
7. Download CSV for external audit

### Using the Debug Visualizer Extension

1. Open the `debug-visualizer-clone` folder in VS Code
2. Press **F5** to start the Extension Development Host
3. In the extension host window, open this workspace
4. Enable the "Pause in debugger after reconciliation" checkbox in Streamlit
5. Click **Process & Reconcile** to hit the breakpoint
6. Press **F1** → **Debug Visualizer Clone: Focus Reconciliation Tables**
7. Inspect `final_output_df`, `master_df`, and transaction aggregations as DataFrames or variable trees

## Project Structure

```
the_algorithmic/
├── script/
│   ├── app.py                              # Main Streamlit app
│   ├── requirements.txt                    # Python dependencies
│   ├── run_app_safe.sh                     # Safe run script
│   └── how_to_run.txt                      # Quick start guide
├── debug-visualizer-clone/
│   ├── src/
│   │   └── extension.ts                    # VS Code extension source
│   ├── package.json                        # Extension manifest and scripts
│   ├── tsconfig.json                       # TypeScript config
│   ├── .npmrc                              # npm config (symlink fix for external USB)
│   └── out/                                # Compiled extension (auto-generated)
├── data_csv/
│   ├── ligo_20_03_N.csv                    # Sample Ligo data
│   ├── mpesa_20_03_N.csv                   # Sample MPesa data
│   └── shift_20_03_N.csv                   # Sample Shift data
├── data/
│   └── 19-25-03-26/                        # Backup data folder
├── .vscode/
│   ├── launch.json                         # Debug launch config for Streamlit
│   ├── tasks.json                          # Build task for extension compilation
│   └── settings.json                       # (optional) workspace settings
├── .gitignore
├── README.md
└── LICENSE
```

## Column Mapping

The app auto-detects the following columns; adjust file headers if needed:

| Source | Key Columns |
|---|---|
| **Shift** | Invoice, Liters, Amount |
| **Ligo** | Transaction ID, Pump, Quantity, Time, Physical_Invoice_No (auto-fill) |
| **MPesa** | Invoice (or similar), Amount Paid / Paid In, Completion Time |

## Reconciliation Logic

1. **Ligo Mapping**: User manually enters Physical_Invoice_No to link pump transactions to shift invoices
2. **Aggregation**: Ligo transactions are grouped by invoice, summing quantities and collecting pump/time details
3. **Join**: Shift is left-joined to aggregated Ligo and MPesa using normalized invoice keys
4. **Variance Calculation**:
   - Ligo Variance: `Shift_Liters - Ligo_Matched_Qty`
   - MPesa Variance: `Shift_Amount - MPesa_Matched_Amount`
5. **Flags**: Discrepancy rows are marked if variance exceeds thresholds (0.001 L for Ligo, 0.01 for MPesa)
6. **Output**: Columns include all Shift cols + Ligo analysis (qty, variance, tx count, match details, pumps, times) + MPesa analysis + status flags

## Row Highlighting Rules

| Highlight | Condition | Color |
|---|---|---|
| **Variance** | `abs(Shift_vs_Ligo_Variance) > 0.001` OR `abs(Shift_vs_MPesa_Variance) > 0.01` | Red (8% opacity) |
| **Multi-Ligo Tx** | `Ligo_Tx_Count > 1` | Amber (7% opacity) |
| **Multi-MPesa Tx** | `MPesa_Tx_Count > 1` | Blue (7% opacity) |

Priority: If a row has multiple conditions, variance takes precedence (shows red).

## CSV Format Requirements

### Shift Report
```
Invoice, Liters, Amount, [other columns]
1234567, 100.00, 5000.00, ...
```

### Ligo Report
```
Transaction ID, Pump, Quantity, Time, [other columns]
TXN001, Pump 1, 50.00, 09:15:00, ...
TXN002, Pump 2, 50.00, 09:20:00, ...
```

### MPesa Report
```
Invoice, Amount Paid (or Paid In), Completion Time, [other columns]
1234567, 5000.00, 09:25:00, ...
```

## Troubleshooting

### Issue: `plotly` not found
**Solution**: `pip install plotly>=5.18.0`

### Issue: Streamlit not found in venv
**Solution**: `source ~/forensic_venv/bin/activate && pip install streamlit==1.32.2 pandas==2.2.1 streamlit-aggrid==0.3.1 plotly>=5.18.0`

### Issue: Extension won't compile (npm EPERM error on external USB)
**Solution**: `.npmrc` has `bin-links=false` to disable symlink creation. Rebuild with `npm run compile`.

### Issue: Extension doesn't auto-focus reconciliation tables
**Workaround**: Manually run command `Debug Visualizer Clone: Focus Reconciliation Tables` (F1 palette).

## Contributing

If you add features, please:
1. Update `script/requirements.txt` if adding Python packages
2. Update `debug-visualizer-clone/package.json` if adding JS/TS packages
3. Test thoroughly with provided sample CSVs
4. Update this README with usage/feature notes

## License

[Your License Here]

## Contact

For questions or bug reports, please open an issue on GitHub.

---

**Last Updated**: April 4, 2026

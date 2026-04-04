# Debug Visualizer Clone

This extension is a Python-first prototype inspired by debug visualizer workflows in VS Code.

## Features

- Opens a live webview panel for the active debug session.
- Shows the current frame, scope tree, and an optional focused expression.
- Refreshes automatically on debugger stop, continue, terminate, and active-session changes.
- Visualizes nested variables by walking the Debug Adapter Protocol variable tree.

## Commands

- `Debug Visualizer Clone: Open Panel`
- `Debug Visualizer Clone: Visualize Selection`
- `Debug Visualizer Clone: Refresh`

## Development

```bash
cd debug-visualizer-clone
npm install
npm run compile
```

This project includes `.npmrc` with `bin-links=false` because the workspace is on an external drive that rejects npm symlink creation.

Then press `F5` in VS Code from this extension folder to launch an Extension Development Host.

## Install npm on Linux

Ubuntu or Debian:

```bash
sudo apt update
sudo apt install -y nodejs npm
node --version
npm --version
```

If you want newer Node.js versions, use `nvm` instead:

```bash
curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.nvm/nvm.sh
nvm install --lts
node --version
npm --version
```

## Debugging app.py with the visualizer

1. Install the Python app requirements into your virtual environment.
2. Install Node.js and npm, then run the extension build commands above.
3. Open [../.vscode/launch.json](../.vscode/launch.json) and use the `Python: Streamlit app.py` launch configuration.
4. In the app sidebar, enable `Pause in debugger after reconciliation`.
5. Start debugging `app.py`, upload the CSV files, and click `Process & Reconcile`.
6. When execution pauses, open the visualizer panel and inspect these variables from the reconcile block:
	- `agg_ligo`
	- `agg_mpesa`
	- `master_df`
	- `final_output_df`
7. In the editor, select an expression like `master_df[['Invoice', 'Ligo_Matched_Qty', 'MPesa_Matched_Amount']]` and run `Debug Visualizer Clone: Visualize Selection`.

The pause is triggered after `final_output_df` is created, so the full merged reconciliation table is available in the debugger scope.

## Current scope

- Best effort support for Python debug sessions.
- Uses the active stopped stack frame to query scopes and evaluate expressions.
- Limits tree depth and child count to keep the panel responsive.
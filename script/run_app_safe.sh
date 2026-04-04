#!/usr/bin/env bash
set -euo pipefail

VENV_PATH="/home/izdixit/forensic_venv/bin/activate"
APP_PATH="/media/izdixit/HIKSEMI/forensic/bonje/the_algorithmic/script/app.py"

if [[ ! -f "$VENV_PATH" ]]; then
  echo "Virtual environment activation script not found: $VENV_PATH"
  echo "Create it with: python3 -m venv ~/forensic_venv"
  exit 1
fi

source "$VENV_PATH"
cd /home/izdixit
exec streamlit run "$APP_PATH"

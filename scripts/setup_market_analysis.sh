#!/bin/sh
# The generated code receives this small numerical environment, never app .venv.
set -eu
analysis_project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
"$analysis_project_root/.venv/bin/python" -m venv "$analysis_project_root/.analysis-venv"
"$analysis_project_root/.analysis-venv/bin/python" -m pip install \
  duckdb==1.5.5 pyarrow==25.0.1 pandas==2.3.3 numpy==2.5.3 matplotlib==3.11.2
cd "$analysis_project_root/backend"
../.venv/bin/python -c 'from pipeline.market_analysis.runtime import preflight; print(preflight())'

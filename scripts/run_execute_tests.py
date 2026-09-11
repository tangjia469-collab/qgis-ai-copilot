#!/usr/bin/env python3
"""Run Execute-mode native suites in isolated QGIS subprocesses."""

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SUITES = ("qgis_executor", "qgis_execution_flow", "qgis_execution_dock", "qgis_data_inspection", "qgis_read_only_chat", "qgis_everos", "qgis_everos_dock")


if __name__ == "__main__":
    environment = dict(os.environ)
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(ROOT), environment.get("PYTHONPATH")])
    )
    for suite in SUITES:
        print(f"Running {suite}", flush=True)
        subprocess.run(
            [sys.executable, "-m", f"tests.{suite}"],
            cwd=ROOT,
            env=environment,
            check=True,
            timeout=180,
        )
    print("All Execute native QGIS suites passed")

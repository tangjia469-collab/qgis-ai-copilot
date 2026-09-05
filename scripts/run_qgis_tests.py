#!/usr/bin/env python3
"""Run native suites with the interpreter supplied by the QGIS installation."""

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SUITES = (
    "qgis_network_smoke", "qgis_smoke", "qgis_attachment_smoke",
    "qgis_image_compression", "qgis_composer_layout",
    "qgis_request_progress",
    "qgis_activity",
)

if __name__ == "__main__":
    environment = dict(os.environ)
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, [str(ROOT), environment.get("PYTHONPATH")]))
    for suite in SUITES:
        print(f"Running {suite}", flush=True)
        subprocess.run([sys.executable, "-m", f"tests.{suite}"], cwd=ROOT, env=environment, check=True, timeout=180)
    print("All native QGIS suites passed")

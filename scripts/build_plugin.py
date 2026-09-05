#!/usr/bin/env python3
"""Create a reproducible, source-only QGIS plugin ZIP and checksum."""

import configparser
import hashlib
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(root=ROOT):
    package = root / "qgis_ai_copilot"
    metadata = configparser.ConfigParser()
    metadata.read(package / "metadata.txt", encoding="utf-8")
    version = metadata["general"]["version"]
    if not re.fullmatch(r"[0-9][0-9A-Za-z.+-]*", version):
        raise ValueError("Unsafe plugin version")
    constants = (package / "constants.py").read_text(encoding="utf-8")
    if f'PLUGIN_VERSION = "{version}"' not in constants:
        raise ValueError("metadata.txt and PLUGIN_VERSION differ")
    files = [(path, path.relative_to(root).as_posix()) for path in sorted(package.iterdir()) if path.is_file() and path.suffix in {".py", ".svg"}]
    files += [(package / "metadata.txt", "qgis_ai_copilot/metadata.txt")]
    files += [(root / name, f"qgis_ai_copilot/{name}") for name in ("LICENSE", "THIRD_PARTY_NOTICES.md")]
    if any(path.is_symlink() for path, _ in files):
        raise ValueError("Refusing symlinked package content")
    output = root / "dist"
    output.mkdir(exist_ok=True)
    target = output / f"qgis_ai_copilot-{version}.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, name in sorted(files, key=lambda item: item[1]):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP integrity failed")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (output / f"{target.name}.sha256").write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    return target, digest


if __name__ == "__main__":
    target, digest = build()
    print(f"{target.name}\nSHA-256: {digest}")

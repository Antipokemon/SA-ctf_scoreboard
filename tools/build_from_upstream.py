#!/usr/bin/env python3
"""Build the complete Splunk 10.4 app from the pinned upstream source + overlay."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile

UPSTREAM_COMMIT = "bef2d5cb254b0d6d4699f4f445e6fc914a35ceed"
UPSTREAM_ZIP = f"https://github.com/splunk/SA-ctf_scoreboard/archive/{UPSTREAM_COMMIT}.zip"
APP_NAME = "SA-ctf_scoreboard"


def patch_xml(root: Path) -> int:
    changed = 0
    views = root / "default" / "data" / "ui" / "views"
    for path in views.glob("*.xml"):
        text = path.read_text(encoding="utf-8")
        new = re.sub(r"<(dashboard|form)(?![^>]*\bversion=)", r'<\1 version="1.1"', text, count=1)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed += 1
    return changed


def overlay_tree(src: Path, dest: Path) -> None:
    for path in src.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(src)
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="dist", help="Output directory")
    parser.add_argument("--keep-vendored-libs", action="store_true", help="Keep upstream legacy Python libraries")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    overlay = repo / "overlay"
    if not overlay.exists():
        # Development checkout: app-owned files live at repo root.
        overlay = repo
    outdir = (repo / args.output).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="sa-ctf-build-") as td:
        tmp = Path(td)
        archive = tmp / "upstream.zip"
        print(f"Downloading pinned upstream {UPSTREAM_COMMIT}...")
        urllib.request.urlretrieve(UPSTREAM_ZIP, archive)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(tmp / "src")
        extracted = next((tmp / "src").iterdir())
        app = tmp / APP_NAME
        shutil.copytree(extracted, app)

        # The compatibility fork no longer imports these stale bundled Python
        # dependency trees. Removing them avoids Python 3.13 import/AppInspect
        # failures and reduces the package dramatically.
        if not args.keep_vendored_libs:
            shutil.rmtree(app / "bin" / "splunklib", ignore_errors=True)
            shutil.rmtree(app / "bin" / "sa_ctf_scoreboard", ignore_errors=True)

        # Never ship local credentials.
        (app / "appserver" / "controllers" / "scoreboard_controller.config").unlink(missing_ok=True)

        # Apply compatibility-owned files, excluding tooling/docs that do not
        # belong in the installed Splunk app.
        for top in ("appserver", "bin", "default"):
            src = overlay / top
            if src.exists():
                overlay_tree(src, app / top)

        patched = patch_xml(app)
        print(f"Certified {patched} Simple XML dashboards as version 1.1")

        # Remove source-control and dev-only artifacts from the installable app.
        for name in (".git", ".github", "tests", "tools", "dist"):
            target = app / name
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()

        tar_path = outdir / f"{APP_NAME}-10.4.1.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tf:
            tf.add(app, arcname=APP_NAME)
        print(tar_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

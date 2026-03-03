#!/usr/bin/env python3
"""Download open-source MobileNet-SSD model files and bundle them for packaging."""

from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path
from urllib import request

PROTO_URL = "https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/deploy.prototxt"
CAFFEMODEL_URL = "https://github.com/chuanqi305/MobileNet-SSD/raw/master/mobilenet_iter_73000.caffemodel"


def sha256sum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, out_path: Path, timeout: int = 180) -> None:
    req = request.Request(url, method="GET")
    with request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)


def bundle_model(proto_path: Path, caffemodel_path: Path, bundle_path: Path) -> None:
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(proto_path, arcname="deploy.prototxt")
        zf.write(caffemodel_path, arcname="mobilenet_iter_73000.caffemodel")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download MobileNet-SSD and produce single bundle zip")
    parser.add_argument(
        "--output",
        default="backend/app/uploads/open_models/mobilenet_ssd_bundle.zip",
        help="Output bundle path",
    )
    args = parser.parse_args()

    bundle_path = Path(args.output).resolve()
    model_dir = bundle_path.parent
    proto_path = model_dir / "deploy.prototxt"
    caffemodel_path = model_dir / "mobilenet_iter_73000.caffemodel"

    if not proto_path.exists():
        print(f"[info] downloading: {PROTO_URL}")
        download(PROTO_URL, proto_path)
    else:
        print(f"[ok] exists: {proto_path}")

    if not caffemodel_path.exists() or caffemodel_path.stat().st_size < 5 * 1024 * 1024:
        print(f"[info] downloading: {CAFFEMODEL_URL}")
        download(CAFFEMODEL_URL, caffemodel_path)
    else:
        print(f"[ok] exists: {caffemodel_path}")

    bundle_model(proto_path, caffemodel_path, bundle_path)
    print(f"[ok] bundle: {bundle_path}")
    print(f"[ok] sha256={sha256sum(bundle_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

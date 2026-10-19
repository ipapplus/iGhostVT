#!/usr/bin/env python3
"""Fetch and verify the exact Unicode 16 bidi conformance fixtures."""
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import urllib.request
import zipfile

ARCHIVE_SHA256 = "c86dd81f2b14a43b0cc064aa5f89aa7241386801e35c59c7984e579832634eb2"
FILES = {
    "BidiTest.txt": "93e5eb9d88ca89dcf895f5576486a3363762ad2aa8f2db2fa56fe60cb82b9520",
    "BidiCharacterTest.txt": "d04a51a90052dcd71c4e91ee5b3a9d973ee35c12406b5a99875ac8163c8f2804",
}


def fetch(destination):
    with urllib.request.urlopen("https://www.unicode.org/Public/zipped/16.0.0/UCD.zip", timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("Unicode archive checksum mismatch")
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BytesIO(data)) as archive:
        for name, expected in FILES.items():
            content = archive.read(name)
            if hashlib.sha256(content).hexdigest() != expected:
                raise ValueError("Unicode fixture checksum mismatch: " + name)
            (destination / name).write_bytes(content)
    return {"unicode_version": "16.0.0", "archive_sha256": ARCHIVE_SHA256, "fixtures": FILES}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(fetch(args.destination), indent=2))

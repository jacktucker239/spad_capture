"""Vendored stm32duino sketch for the VL53L8CH, and the same sketch prebuilt.

The sketch and the ST VL53LMZ ULD it drives are in ``vl53l8ch_cnh/``. ``vl53l8ch_cnh.bin`` is that
sketch compiled for the NUCLEO-F401RE, so flashing needs no toolchain. ``prebuilt()`` returns it only
while the sketch is unchanged since it was built (``vl53l8ch_cnh.json`` records the sources' digest).
"""

import hashlib
import json
from pathlib import Path
from typing import Optional

BINARY = Path(__file__).parent / "vl53l8ch_cnh.bin"
MANIFEST = BINARY.with_suffix(".json")


def firmware_dir() -> Path:
    """Path to the VL53L8CH sketch directory."""
    return Path(__file__).parent / "vl53l8ch_cnh"


def sketch_path() -> Path:
    """Path to the .ino sketch file itself."""
    return firmware_dir() / "vl53l8ch_cnh.ino"


SOURCES = (".ino", ".c", ".cpp", ".h")


def sources_digest() -> str:
    """SHA-256 of the sketch's sources (not stray files like .DS_Store), line endings normalized
    (a Windows checkout may rewrite them)."""
    h = hashlib.sha256()
    for f in sorted(p for p in firmware_dir().iterdir() if p.suffix in SOURCES):
        h.update(f.name.encode())
        h.update(f.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def prebuilt() -> Optional[Path]:
    """The bundled firmware binary, if it was built from the sketch as it is now."""
    try:
        built_from = json.loads(MANIFEST.read_text())["sources_sha256"]
    except (OSError, ValueError, KeyError):
        return None
    return BINARY if BINARY.is_file() and built_from == sources_digest() else None

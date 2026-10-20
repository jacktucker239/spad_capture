"""Compile and upload the bundled TMF8828 sketch."""

from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Optional

from spad_capture import arduino
from spad_capture.sensors.tmf.firmware import sketch_path
from spad_capture.sensors.tmf.sensor import find_arduino_port

_FQBN = "arduino:avr:uno"
_CORE = "arduino:avr"
_ROSETTA = Path("/Library/Apple/usr/libexec/oah/libRosettaRuntime")


def flash(port: Optional[str] = None, *, arduino_cli: Optional[Path] = None,
          verbose: bool = False) -> None:
    """Compile and upload the bundled TMF8828 sketch to the Arduino."""
    port = port or find_arduino_port()
    _require_rosetta()
    cli = arduino.ensure_cli(arduino_cli)
    arduino.ensure_core(cli, _CORE)
    arduino.upload(cli, sketch_path(), fqbn=_FQBN, port=port, verbose=verbose)


def _require_rosetta() -> None:
    """The AVR core's tools (compiler, avrdude) are Intel-only: on Apple silicon they need Rosetta 2."""
    if sys.platform == "darwin" and platform.machine() == "arm64" and not _ROSETTA.exists():
        raise RuntimeError("Setting up the TMF8828 board needs Rosetta on this Mac: its Arduino tools are built for Intel.\n"
                           "  Fix: install Rosetta (in Terminal: softwareupdate --install-rosetta --agree-to-license), then try again.")

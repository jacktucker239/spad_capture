"""Program the NUCLEO board with the VL53L8CH firmware through its ST-LINK drive.

The firmware ships prebuilt (``firmware/vl53l8ch_cnh.bin``), so flashing is a file copy: no
arduino-cli, no STM32 core, nothing downloaded. Only a changed sketch is compiled, with arduino-cli.

    python -m spad_capture.sensors.st.flash      rebuild the bundled binary after changing the sketch
"""

from __future__ import annotations

import json
import os
import shutil
import string
import tempfile
import time
from pathlib import Path
from typing import Optional

from rich.console import Console

from spad_capture import arduino
from spad_capture.sensors.st.config import Config, SensorConfig
from spad_capture.sensors.st.firmware import BINARY, MANIFEST, prebuilt, sketch_path, sources_digest
from spad_capture.sensors.st.transport import VL53L8CHTransport, require_port

_FQBN = "STMicroelectronics:stm32:Nucleo_64:pnum=NUCLEO_F401RE"
_CORE = "STMicroelectronics:stm32"
_INDEX = ("https://github.com/stm32duino/BoardManagerFiles/raw/main/"
          "package_stmicroelectronics_index.json")
_console = Console()


def flash(port: Optional[str] = None, *, arduino_cli: Optional[Path] = None,
          verbose: bool = False) -> None:
    """Program the NUCLEO-F401RE with the VL53L8CH firmware.

    The ST-LINK programs whatever firmware is copied onto its USB drive. The
    core's own upload script copies with a tool some ST-LINK versions misread,
    so the firmware is written here with a plain copy.
    """
    require_port(port)     # the board is attached
    drive = _st_link_drive()
    with tempfile.TemporaryDirectory() as out:
        firmware = prebuilt() or _compile(Path(out), arduino_cli, verbose)
        _console.print(f"[bold]Writing[/bold] [cyan]{firmware.name}[/cyan] to the ST-LINK drive [cyan]{drive}[/cyan]")
        _program(firmware, drive)
    _wait_until_running(port)
    _console.print("[bold green]Flash complete.[/bold green]")


def _compile(out: Path, arduino_cli: Optional[Path], verbose: bool) -> Path:
    """Compile the sketch with arduino-cli and the STM32 core, installing them if needed."""
    cli = arduino.ensure_cli(arduino_cli)
    arduino.ensure_core(cli, _CORE, index_url=_INDEX)
    _console.print(f"[bold]Flashing[/bold]: building [cyan]{sketch_path().name}[/cyan] ({_FQBN})")
    return arduino.build(cli, sketch_path(), fqbn=_FQBN, out=out, verbose=verbose)


def prebuild(arduino_cli: Optional[Path] = None) -> Path:
    """Rebuild the bundled binary and its manifest from the sketch as it is now."""
    with tempfile.TemporaryDirectory() as out:
        shutil.copyfile(_compile(Path(out), arduino_cli, False), BINARY)
    cli = arduino.ensure_cli(arduino_cli)
    MANIFEST.write_text(json.dumps({"sources_sha256": sources_digest(), "fqbn": _FQBN,
                                    "core": f"{_CORE} {arduino.core_version(cli, _CORE)}",
                                    "arduino_cli": arduino.version(cli)}, indent=1) + "\n")
    return BINARY


def _st_link_drive() -> Path:
    """The ST-LINK's USB drive, recognised by the files it always carries."""
    if os.name == "nt":
        roots = [Path(f"{letter}:/") for letter in string.ascii_uppercase]
    else:
        roots = [*Path("/Volumes").glob("*"), *Path("/media").glob("*/*"), *Path("/run/media").glob("*/*")]
    drive = next((r for r in roots if (r / "DETAILS.TXT").is_file() and (r / "MBED.HTM").is_file()), None)
    if drive is None:
        raise RuntimeError("The NUCLEO board's ST-LINK drive was not found.\n"
                           "  Fix: unplug the board and plug it back in.")
    return drive


def _program(firmware: Path, drive: Path, timeout_s: float = 30.0) -> None:
    """Copy the firmware onto the drive; the ST-LINK programs the board and then drops the file."""
    target = drive / firmware.name
    with open(target, "wb") as f:
        f.write(firmware.read_bytes())
        f.flush()
        os.fsync(f.fileno())
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if (drive / "FAIL.TXT").is_file():
            raise RuntimeError(f"The ST-LINK could not program the board: {(drive / 'FAIL.TXT').read_text().strip()}")
        if not target.exists():
            return
        time.sleep(0.25)
    raise RuntimeError("The ST-LINK did not finish programming the board.\n"
                       "  Fix: unplug the board and plug it back in.")


def _wait_until_running(port: Optional[str], timeout_s: float = 30.0) -> None:
    """Wait for the new firmware to answer its handshake."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with VL53L8CHTransport(Config(sensor=SensorConfig(port=port))) as transport:
                transport.handshake(retries=1)
            return
        except (RuntimeError, OSError):     # the board is still restarting
            time.sleep(1)
    raise RuntimeError("The NUCLEO board did not start its new firmware.\n"
                       "  Fix: unplug the board and plug it back in.")


if __name__ == "__main__":
    print(prebuild())

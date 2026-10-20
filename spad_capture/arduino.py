"""Shared arduino-cli plumbing: locate or install the CLI, install a core, upload a sketch.

Both backends flash through here; each supplies only its core, FQBN and sketch.
"""

from __future__ import annotations

import ctypes
import io
import os
import platform
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

import certifi
from rich.console import Console

_console = Console()

# Fallback search paths for arduino-cli when not on PATH.
_CLI_CANDIDATES = [
    Path("/usr/local/bin/arduino-cli"),
    Path("/opt/homebrew/bin/arduino-cli"),   # Homebrew on Apple silicon
    Path("~/.local/bin/arduino-cli").expanduser(),
]
_EXE = "arduino-cli.exe" if os.name == "nt" else "arduino-cli"
_RELEASE_URL = "https://downloads.arduino.cc/arduino-cli/arduino-cli_1.5.1_{}"     # pinned stable release
# No console window means we run inside an app; Windows would open one for every tool.
_WINDOWLESS = os.name == "nt" and not ctypes.windll.kernel32.GetConsoleWindow()


def _tool(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """Run arduino-cli. Inside a windowless app it stays hidden, its output in ours."""
    kw.setdefault("env", {"TMPDIR": tempfile.gettempdir(), **os.environ})     # its ctags step needs a TMPDIR
    if _WINDOWLESS:
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
        if not kw.get("capture_output"):
            kw.setdefault("stdout", sys.stdout)
            kw.setdefault("stderr", sys.stderr)
    return subprocess.run(cmd, **kw)


def _bootstrap_dir() -> Path:
    """Where to drop arduino-cli. Prefers the active conda env's bin so the
    binary is scoped to the env."""
    prefix = os.environ.get("CONDA_PREFIX")
    return Path(prefix) / "bin" if prefix else Path("~/.local/bin").expanduser()


def version(binary: Path) -> Optional[str]:
    """First line of ``arduino-cli version``, or None if it cannot be executed."""
    try:
        p = _tool([str(binary), "version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    return p.stdout.strip().splitlines()[0] if p.stdout.strip() else ""


def find_cli(override: Optional[Path] = None) -> Optional[Path]:
    """Locate the arduino-cli binary, or None if missing."""
    if override:
        if not override.exists():
            raise FileNotFoundError(f"--arduino-cli path does not exist: {override}")
        return override
    on_path = shutil.which("arduino-cli")
    if on_path:
        return Path(on_path)
    return next((c for c in [*_CLI_CANDIDATES, _bootstrap_dir() / _EXE] if c.exists()), None)


def _release() -> str:
    """The official arduino-cli archive name for this machine."""
    system = {"Darwin": "macOS", "Linux": "Linux", "Windows": "Windows"}[platform.system()]
    arm = platform.machine().lower() in ("arm64", "aarch64") and system != "Windows"
    return f"{system}_{'ARM64' if arm else '64bit'}.{'zip' if system == 'Windows' else 'tar.gz'}"


def _unpack(archive: bytes, zipped: bool) -> bytes:
    """The arduino-cli binary out of a release archive."""
    if zipped:
        return zipfile.ZipFile(io.BytesIO(archive)).read(_EXE)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        return tar.extractfile(_EXE).read()


def bootstrap_cli() -> Path:
    """Download the official arduino-cli release into the active environment.

    Reuses an existing binary if it runs.
    """
    target = _bootstrap_dir()
    binary = target / _EXE
    if binary.exists():
        v = version(binary)
        if v:
            _console.print(f"[dim]arduino-cli already installed: {v}[/dim]")
            return binary
        _console.print(f"[yellow]arduino-cli at {binary} did not run; reinstalling.[/yellow]")

    target.mkdir(parents=True, exist_ok=True)
    _console.print(f"Installing arduino-cli into [cyan]{target}[/cyan] ...")
    release = _release()
    try:
        tls = ssl.create_default_context(cafile=certifi.where())     # a packaged app has no system CA bundle
        with urllib.request.urlopen(_RELEASE_URL.format(release), timeout=60, context=tls) as r:
            binary.write_bytes(_unpack(r.read(), release.endswith(".zip")))
    except Exception as e:
        raise RuntimeError(f"Could not download arduino-cli: {e}\n  Fix: check the internet connection, then try again.")
    binary.chmod(0o755)
    v = version(binary)
    if v is None:
        raise RuntimeError(f"arduino-cli installed at {binary} but does not run.")
    _console.print(f"[green]Installed[/green] {v}")
    return binary


def ensure_cli(override: Optional[Path] = None) -> Path:
    """Return a usable arduino-cli, installing it if necessary."""
    return find_cli(override) or bootstrap_cli()


def core_version(cli: Path, core: str) -> Optional[str]:
    """The installed version of a board core, or None if it is not installed."""
    for line in _tool([str(cli), "core", "list"], capture_output=True, text=True).stdout.splitlines():
        fields = line.split()
        if len(fields) > 1 and fields[0] == core:
            return fields[1]
    return None


def ensure_core(cli: Path, core: str, *, index_url: Optional[str] = None) -> None:
    """Install a board core if it is not already registered.

    ``index_url`` adds a third-party board-manager index first (stm32duino).
    """
    if core_version(cli, core):
        return
    if index_url:
        _tool([str(cli), "config", "init"], capture_output=True, check=False)
        _tool([str(cli), "config", "add", "board_manager.additional_urls", index_url],
                       capture_output=True, check=False)
    _console.print(f"Installing {core} core ...")
    try:
        _tool([str(cli), "core", "update-index"], check=True, capture_output=True)
        _tool([str(cli), "core", "install", core], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Could not install the {core} core: {e.stderr.decode(errors='replace').strip()}") from None
    _console.print(f"[green]{core} core installed[/green]")


def build(cli: Path, sketch: Path, *, fqbn: str, out: Path, verbose: bool = False) -> Path:
    """Compile a sketch into ``out``; returns the firmware binary."""
    if not sketch.exists():
        raise FileNotFoundError(f"Bundled firmware missing: {sketch}")
    cmd = [str(cli), "compile", "--fqbn", fqbn, "--output-dir", str(out), str(sketch)]
    if verbose:
        cmd.insert(1, "-v")
    if _tool(cmd).returncode != 0:
        raise RuntimeError("arduino-cli compile failed")
    return next(out.glob("*.bin"))


def upload(cli: Path, sketch: Path, *, fqbn: str, port: str, verbose: bool = False) -> None:
    """Compile and upload a sketch."""
    if not sketch.exists():
        raise FileNotFoundError(f"Bundled firmware missing: {sketch}")
    _console.print(f"[bold]Flashing[/bold] [cyan]{sketch.name}[/cyan] on [cyan]{port}[/cyan] ({fqbn})")
    cmd = [str(cli), "compile", "--upload", "--port", port, "--fqbn", fqbn, str(sketch)]
    if verbose:
        cmd.insert(1, "-v")
    if _tool(cmd).returncode != 0:
        raise RuntimeError("arduino-cli flash failed")
    _console.print("[bold green]Flash complete.[/bold green]")

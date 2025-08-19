"""
Application entry point for Foundry Local Desktop Chat.

Runs a synchronous GPU detection with nvidia-smi before launching the UI.

Authors:
    - Benjamin Dourthe (benjamin@adonamed.com)
"""
# Standard library imports
import os
import re
import subprocess
import sys

# Third-party libraries
from PySide6.QtWidgets import QApplication

# Local application imports
from gui.app import MainWindow

def _try_nvidia_smi_model() -> str:
    """Return first NVIDIA GPU model via nvidia-smi, or empty string if unavailable."""
    try:
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
        cp = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', timeout=3, check=False, creationflags=flags)
        out = (cp.stdout or '').strip()
        if out:
            return out.splitlines()[0].strip()
    except Exception:
        return ''
    return ''

def _try_nvidia_smi_cuda_version() -> str:
    """Return CUDA version string like 'CUDA 12.1' parsed from nvidia-smi, else empty string."""
    try:
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
        cp = subprocess.run(["nvidia-smi"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', timeout=3, check=False, creationflags=flags)
        txt = (cp.stdout or '') + "\n" + (cp.stderr or '')
        m = re.search(r"CUDA\s+Version\s*:\s*([0-9]+\.[0-9]+)", txt, re.IGNORECASE)
        if m:
            return f"CUDA {m.group(1)}"
    except Exception:
        return ''
    return ''

def _detect_accelerator() -> tuple[str, str]:
    """Detect accelerator via nvidia-smi and return (backend, model). Backend is 'CUDA GPU' on success or 'CPU' otherwise."""
    model = _try_nvidia_smi_model()
    if model:
        return 'CUDA GPU', model
    return 'CPU', ''

def run_app() -> None:
    """Start the Qt application, printing GPU INFO if available before showing the UI."""
    backend, model = _detect_accelerator()
    if backend != 'CPU' and model:
        cuda = _try_nvidia_smi_cuda_version()
        extra = f" ({cuda})" if cuda else ''
        print(f"[INFO] GPU acceleration available: {model}{extra}")
    app = QApplication(sys.argv)
    w = MainWindow(init_backend=backend, init_model=model)
    w.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    run_app()

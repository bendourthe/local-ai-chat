"""
Lightweight wrapper around the Foundry Local CLI to install, list models, and run chats.

Provides process management and minimal output parsing for assistant messages.

Authors:
    - Benjamin Dourthe (benjamin@adonamed.com)
"""
import os
import re
import subprocess
import threading
import queue
import time
from typing import Callable, List, Optional, Tuple

_ASSISTANT_BLOCK_RE = re.compile(r"<\|start\|>assistant<\|channel\|>final<\|message\|>(.*?)<\|return\|>", re.DOTALL)

class FoundryCLI:
    """Wrap Foundry Local CLI operations (install, list, run)."""
    def __init__(self) -> None:
        """Initialize CLI wrapper without side effects."""
        self._proc: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stdout_q: "queue.Queue[str]" = queue.Queue()
        self._stop_event = threading.Event()
        self._buffer = ""
        self._device_backend: Optional[str] = None

    def is_installed(self) -> bool:
        """Return True if the `foundry` command is available."""
        try:
            flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
            subprocess.run(["foundry", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, creationflags=flags)
            return True
        except FileNotFoundError:
            return False
    def install_foundry(self, on_output: Optional[Callable[[str], None]] = None, elevated: bool = False) -> int:
        """
        Install Foundry Local using winget. When elevated=True, runs via PowerShell Start-Process with -Verb RunAs (UAC).

        Parameters:
            - on_output (Callable[[str], None]): Callback for each output chunk
            - elevated (bool): Run install with admin elevation (UAC)

        Returns:
            - int: Exit code
        """
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        if elevated and os.name == 'nt':
            ps = (
                "Start-Process winget "
                "-ArgumentList 'install --exact --id Microsoft.FoundryLocal --accept-package-agreements --accept-source-agreements' "
                "-Verb RunAs -Wait -WindowStyle Hidden"
            )
            cp = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', creationflags=flags)
            if on_output:
                out = (cp.stdout or '').strip()
                err = (cp.stderr or '').strip()
                if out:
                    on_output(out)
                if err:
                    on_output(err)
            return cp.returncode or 0
        cmd = [
            "winget", "install", "--exact", "--id", "Microsoft.FoundryLocal",
            "--accept-package-agreements", "--accept-source-agreements"
        ]
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', creationflags=flags) as p:
            for line in p.stdout:  # type: ignore[arg-type]
                if on_output:
                    on_output(line.rstrip('\n'))
            p.wait()
            return p.returncode or 0
    def list_models(self) -> List[str]:
        """
        Return a best-effort parsed list of available model names from `foundry model list`.

        Returns:
            - list[str]: Model identifiers
        """
        try:
            cp = subprocess.run(["foundry", "model", "list"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', check=False, creationflags=subprocess.CREATE_NO_WINDOW)
        except FileNotFoundError:
            return []
        out = cp.stdout.splitlines()
        models: List[str] = []
        seen: set[str] = set()
        for raw in out:
            s = raw.strip()
            if not s:
                continue
            # Skip obvious headers or separators
            if 'Model ID' in s or s.startswith('Alias') or s.startswith('Device') or s.startswith('Task'):
                continue
            if set(s) <= set('-─—_=· '):
                continue
            # Extract the last whitespace-separated token (the Model ID column)
            m = re.search(r'([A-Za-z0-9][A-Za-z0-9._-]+)\s*$', s)
            if not m:
                continue
            token = m.group(1).rstrip('-')
            # Basic sanity: must contain at least one letter or digit and a dash or dot typical of model ids
            if not re.search(r'[A-Za-z0-9]', token):
                continue
            if token not in seen:
                seen.add(token)
                models.append(token)
        return models
    def model_size_hint(self, name: str) -> Optional[str]:
        """Return a best-effort size hint like '4.2 GB' for a model from `foundry model list`.

        Tries to find a table row matching the alias or model id and extract an 'XX [KMG]B' token.
        """
        try:
            cp = subprocess.run(["foundry", "model", "list"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', check=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except FileNotFoundError:
            return None
        target = name.strip().lower()
        size_re = re.compile(r"(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)", re.IGNORECASE)
        for raw in (cp.stdout or '').splitlines():
            s = raw.strip()
            if not s or 'Model ID' in s or s.startswith('Alias'):
                continue
            if set(s) <= set('-─—_=· '):
                continue
            low = s.lower()
            if target not in low:
                continue
            m = size_re.search(s)
            if m:
                return f"{m.group(1)} {m.group(2).upper()}"
        return None
    def start_chat(self, model: str, on_raw_output: Optional[Callable[[str], None]] = None, on_assistant: Optional[Callable[[str], None]] = None, flush_secs: float = 0.4) -> None:
        """
        Start an interactive chat session `foundry model run <model>` and begin reading stdout on a background thread.

        Parameters:
            - model (str): Model name to run
            - on_raw_output (Callable[[str], None]): Callback for each raw line
            - on_assistant (Callable[[str], None]): Callback when an assistant final block is parsed
            - flush_secs (float): Debounce interval for streaming assistant text flushes (default 0.4s)
        """
        self.stop_chat()
        self._stop_event.clear()
        self._buffer = ""
        self._device_backend = None
        args = ["foundry", "model", "run", model]
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        self._proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1, creationflags=flags)
        def _reader() -> None:
            acc: list[str] = []
            ignore_res = [
                re.compile(r"^Interactive Chat", re.IGNORECASE),
                re.compile(r"^Interactive mode", re.IGNORECASE),
                re.compile(r"^Enter /\? or /help", re.IGNORECASE),
                re.compile(r"^Model .* (loaded|found) ", re.IGNORECASE),
                re.compile(r"^Fetching ", re.IGNORECASE),
                re.compile(r"^Press Ctrl", re.IGNORECASE),
                re.compile(r"loading model", re.IGNORECASE),
                re.compile(r"found in the local cache", re.IGNORECASE),
                re.compile(r"^downloading", re.IGNORECASE),
                re.compile(r"^extracting", re.IGNORECASE),
                re.compile(r"^verifying", re.IGNORECASE),
                re.compile(r"^(starting|started) ", re.IGNORECASE),
                re.compile(r"(server|service).*(listening|ready)", re.IGNORECASE),
                re.compile(r"^(device|task|alias|model id)\b", re.IGNORECASE),
                # Skip any raw markup tokens so we don't render unformatted content
                re.compile(r"<\|(start|channel|message|return)\|>", re.IGNORECASE),
                # Heuristics: drop obvious chain-of-thought style lines in fallback mode
                re.compile(r"^\s*\".*?\"\s*$"),  # pure quoted line
                re.compile(r"\b(thinking|analysis|reasoning|plan|scratchpad)\b", re.IGNORECASE),
            ]
            prompt_res = re.compile(r"Interactive mode|enter your prompt|^\s*>\s*$", re.IGNORECASE)
            start_res = re.compile(r"Interactive Chat|Interactive mode|Enter /\?|^\s*>\s*$", re.IGNORECASE)
            last_flush = time.time()
            use_fallback = True  # Fallback only until we detect structured assistant blocks
            def flush_acc() -> None:
                # Only flush fallback content if we're still in fallback mode
                if not use_fallback:
                    acc.clear()
                    return
                if acc and on_assistant:
                    on_assistant("\n".join(acc).strip())
                acc.clear()
            def maybe_flush_by_time() -> None:
                nonlocal last_flush
                now = time.time()
                try:
                    interval = float(flush_secs)
                except Exception:
                    interval = 0.4
                if interval <= 0:
                    interval = 0.4
                if acc and (now - last_flush) >= interval:
                    flush_acc()
                    last_flush = now
            ready = False
            while not self._stop_event.is_set() and self._proc and self._proc.stdout:
                line = self._proc.stdout.readline()
                if not line:
                    break
                if on_raw_output:
                    on_raw_output(line.rstrip("\n"))
                self._buffer += line
                for m in _ASSISTANT_BLOCK_RE.finditer(self._buffer):
                    # Switch off fallback: trust structured assistant blocks exclusively
                    if use_fallback:
                        acc.clear()
                        use_fallback = False
                    content = m.group(1)
                    if on_assistant:
                        on_assistant(content)
                if "<|return|>" in self._buffer:
                    parts = self._buffer.split("<|return|>")
                    self._buffer = parts[-1]
                s = line.strip("\n")
                # Best-effort device backend detection from startup lines
                try:
                    if self._device_backend is None:
                        name = self._detect_device_backend(s)
                        if name:
                            self._device_backend = name
                except Exception:
                    pass
                if s.strip() == "":
                    flush_acc()
                    continue
                # Skip pure progress-bar lines composed of bracket/hash/dash/space characters
                if set(s) <= set("#-=.[]()<>| "):
                    continue
                # Detect readiness of interactive prompt and gate assistant accumulation until then
                if start_res.search(s):
                    ready = True
                    flush_acc()
                    continue
                if not ready:
                    # Ignore everything until the chat session is ready
                    continue
                if any(r.search(s) for r in ignore_res):
                    flush_acc()
                    continue
                if prompt_res.search(s):
                    flush_acc()
                    continue
                if use_fallback:
                    acc.append(s)
                    maybe_flush_by_time()
            flush_acc()
            if self._proc:
                self._proc.wait()
        self._reader_thread = threading.Thread(target=_reader, daemon=True)
        self._reader_thread.start()
    def get_device_backend(self) -> Optional[str]:
        """Return the last detected device backend name (e.g., 'CUDA GPU', 'DirectML GPU', 'CPU')."""
        return self._device_backend
    def _detect_device_backend(self, s: str) -> Optional[str]:
        """Return a normalized accelerator name if a line indicates device backend."""
        txt = (s or '').strip()
        low = txt.lower()
        m = re.match(r"\s*device\s*[:=]\s*(.+)$", txt, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            return self._normalize_backend_name(val)
        if any(k in low for k in ('accelerator', 'backend', 'runtime')) and any(k in low for k in ('cuda','directml','dml','rocm','mps','metal','openvino','cpu','gpu')):
            return self._normalize_backend_name(txt)
        if 'model id' in low and any(x in low for x in ('-cuda-gpu','-dml-gpu','-rocm-gpu','-cpu','-metal-gpu','-mps')):
            return self._normalize_backend_name(txt)
        if any(k in low for k in ('cuda','directml',' dml ','rocm','mps','metal','openvino')):
            return self._normalize_backend_name(txt)
        return None
    def _normalize_backend_name(self, raw: str) -> Optional[str]:
        """Map arbitrary device strings into a concise label."""
        low = (raw or '').lower()
        if 'cuda' in low or 'nvidia' in low:
            return 'CUDA GPU'
        if 'directml' in low or re.search(r"\bdml\b", low):
            return 'DirectML GPU'
        if 'rocm' in low or 'amd' in low:
            return 'ROCm GPU'
        if 'mps' in low or 'metal' in low:
            return 'Metal GPU'
        if 'openvino' in low:
            return 'OpenVINO'
        if re.search(r"\bcpu\b", low):
            return 'CPU'
        if 'gpu' in low:
            return 'GPU'
        return None
    def list_cached_pairs(self) -> List[Tuple[str, str]]:
        """Return a list of (alias, model_id) for models present in the local cache."""
        try:
            cp = subprocess.run(["foundry", "cache", "list"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', check=False, creationflags=subprocess.CREATE_NO_WINDOW)
        except FileNotFoundError:
            return []
        pairs: List[Tuple[str, str]] = []
        for raw in (cp.stdout or '').splitlines():
            s = raw.strip()
            if not s or 'Models cached on device' in s or s.startswith('Alias'):
                continue
            if set(s) <= set('-─—_=· '):
                continue
            # Lines may look like: "💾 gpt-oss-20b                   gpt-oss-20b-cuda-gpu"
            m = re.match(r"^\s*(?:💾\s*)?(.+?)\s{2,}([A-Za-z0-9][A-Za-z0-9._-]+)\s*$", s)
            if not m:
                continue
            alias = m.group(1).strip()
            model_id = m.group(2).strip()
            pairs.append((alias, model_id))
        return pairs
    def remove_cached_model(self, name: str) -> bool:
        """Remove a cached model by model id or alias using `foundry cache remove`.

        Tries the provided name first; on failure, resolves via alias↔id pairs and retries.
        """
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
        def _rm(target: str) -> bool:
            # Try with explicit non-interactive flags first; fall back to piping "y" to handle confirmation prompts.
            cmds = [
                ["foundry", "cache", "remove", "--yes", target],
                ["foundry", "cache", "remove", "-y", target],
                ["foundry", "cache", "remove", target],
            ]
            for cmd in cmds:
                try:
                    cp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', input='y\n', timeout=120, check=False, creationflags=flags)
                    if (cp.returncode or 0) == 0:
                        return True
                except subprocess.TimeoutExpired:
                    return False
                except FileNotFoundError:
                    return False
            return False
        if _rm(name):
            return True
        # Try to resolve alias<->id
        pairs = self.list_cached_pairs()
        alias_to_id = {a: mid for a, mid in pairs}
        id_to_alias = {mid: a for a, mid in pairs}
        candidate = alias_to_id.get(name) or id_to_alias.get(name)
        if candidate and _rm(candidate):
            return True
        return False
    def remove_cached_model_stream(self, name: str, on_output: Optional[Callable[[str], None]] = None) -> bool:
        """Remove a cached model by id or alias while streaming CLI output to a callback."""
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
        def _emit(s: str) -> None:
            try:
                if on_output:
                    on_output(s)
            except Exception:
                pass
        def _rm_stream(target: str) -> bool:
            cmds = [
                ["foundry", "cache", "remove", "--yes", target],
                ["foundry", "cache", "remove", "-y", target],
                ["foundry", "cache", "remove", target],
            ]
            for cmd in cmds:
                try:
                    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1, creationflags=flags)
                except FileNotFoundError:
                    return False
                assert p.stdout is not None
                try:
                    for line in p.stdout:
                        s = line.rstrip('\n')
                        if s:
                            _emit(s)
                        # Best-effort: auto-confirm if we see a prompt
                        try:
                            if p.stdin and re.search(r"(y/n|yes/no|confirm)", s, re.IGNORECASE):
                                p.stdin.write('y\n')
                                p.stdin.flush()
                        except Exception:
                            pass
                except Exception:
                    pass
                try:
                    p.wait()
                except Exception:
                    pass
                if p.returncode == 0:
                    return True
            return False
        if _rm_stream(name):
            return True
        pairs = self.list_cached_pairs()
        alias_to_id = {a: mid for a, mid in pairs}
        id_to_alias = {mid: a for a, mid in pairs}
        candidate = alias_to_id.get(name) or id_to_alias.get(name)
        if candidate and _rm_stream(candidate):
            return True
        return False
    def ensure_model_downloaded(self, model: str, on_output: Optional[Callable[[str], None]] = None) -> bool:
        """
        Ensure a model is downloaded by launching `foundry model run <model>` until the model loads, then terminate.

        Parameters:
            - model (str): Model name to fetch
            - on_output (Callable[[str], None]): Optional callback for progress lines

        Returns:
            - bool: True if model loaded successfully; False otherwise
        """
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
        try:
            p = subprocess.Popen(["foundry", "model", "run", model], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', creationflags=flags)
        except FileNotFoundError:
            return False
        ok = False
        ready_res = [
            re.compile(r"loaded successfully", re.IGNORECASE),
            re.compile(r"found in the local cache", re.IGNORECASE),
            re.compile(r"interactive mode.*enter your prompt", re.IGNORECASE),
            re.compile(r"interactive chat", re.IGNORECASE),
        ]
        deadline = time.time() + 300
        assert p.stdout is not None
        for line in p.stdout:
            s = line.rstrip('\n')
            if on_output:
                on_output(s)
            if any(r.search(s) for r in ready_res):
                ok = True
                try:
                    if p.stdin:
                        p.stdin.write('/exit\n')
                        p.stdin.flush()
                except Exception:
                    pass
                break
            if time.time() > deadline:
                break
        try:
            if p and p.poll() is None:
                p.terminate()
        except Exception:
            pass
        try:
            p.wait(timeout=5)
        except Exception:
            pass
        return ok
    def send_prompt(self, prompt: str) -> None:
        """Send a user prompt to the running chat session."""
        if not self._proc or not self._proc.stdin:
            return
        try:
            self._proc.stdin.write(prompt + "\n")
            self._proc.stdin.flush()
        except Exception:
            pass
    def stop_chat(self) -> None:
        """Stop the chat session and background reader if running."""
        self._stop_event.set()
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.5)
        self._proc = None
        self._reader_thread = None

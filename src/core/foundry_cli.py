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
import select
import gc
import fcntl
import io
from typing import Callable, List, Optional, Tuple, Dict
from .token_tracker import get_token_tracker, TokenMetrics
from .gpu_monitor import get_gpu_monitor, GPUMemoryInfo

_ASSISTANT_BLOCK_RE = re.compile(r"<\|start\|>assistant<\|channel\|>final<\|message\|>(.*?)<\|return\|>", re.DOTALL)

class FoundryCLI:
    """Wrap Foundry Local CLI operations (install, list, run)."""
    def __init__(self) -> None:
        """Initialize CLI wrapper with proper session tracking."""
        self._proc: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stdout_q: "queue.Queue[str]" = queue.Queue()
        self._stop_event = threading.Event()
        self._buffer = ""
        self._device_backend: Optional[str] = None
        self._device_model: Optional[str] = None
        self._token_tracker = get_token_tracker()
        self._current_request_id: Optional[str] = None
        self._current_chat_id: Optional[str] = None
        self._current_model: Optional[str] = None
        self._gpu_monitor = get_gpu_monitor()
        self._model_loaded: bool = False
        # NEW ATTRIBUTES FOR MEMORY AND SESSION MANAGEMENT
        self._chat_sessions: Dict[str, List[Dict]] = {}  # Track messages per chat
        self._process_cleanup_lock = threading.Lock()  # Thread-safe cleanup
        self._memory_baseline: Optional[int] = None  # Track baseline memory
        self._context_cache: Dict[str, str] = {}  # Cache formatted contexts
        self._on_raw_output: Optional[Callable[[str], None]] = None
        self._on_assistant: Optional[Callable[[str], None]] = None
        self._flush_secs: float = 0.4

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

    def start_chat(self, model: str, on_raw_output: Optional[Callable[[str], None]] = None,
                on_assistant: Optional[Callable[[str], None]] = None, 
                flush_secs: float = 0.4) -> None:
        """Start chat with proper process management."""
        # Clean up any existing session first
        if self._proc:
            self.stop_chat()
            time.sleep(1.0)  # Wait for cleanup
        # Kill any orphaned processes before starting
        self._kill_orphaned_processes()
        # Record baseline memory
        if self._gpu_monitor:
            info = self._gpu_monitor.get_gpu_memory_usage()
            if info:
                self._memory_baseline = info.used_mb
                print(f"GPU memory baseline: {self._memory_baseline}MB", flush=True)
        self.ensure_model_downloaded(model)
        self._on_raw_output = on_raw_output
        self._on_assistant = on_assistant
        self._flush_secs = flush_secs
        self._stop_event.clear()        
        try:
            # Platform-specific process creation
            if os.name == 'nt':
                # Windows: Use binary mode for pipes
                flags = subprocess.CREATE_NO_WINDOW
                self._proc = subprocess.Popen(
                    ["foundry", "chat", model],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=0,  # Unbuffered
                    creationflags=flags
                )
            else:
                # Unix: Use text mode
                self._proc = subprocess.Popen(
                    ["foundry", "chat", model],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=0
                )
            if not self._proc:
                raise RuntimeError("Failed to start Foundry process")            
            self._model_loaded = True
            self._current_model = model
            # Start reader thread
            self._reader_thread = threading.Thread(
                target=self._read_output,
                name="FoundryReaderThread",
                daemon=True
            )
            self._reader_thread.start()
            # Wait for model to be ready
            ready_timeout = 60
            ready_start = time.time()
            while time.time() - ready_start < ready_timeout:
                if self._proc.poll() is not None:
                    raise RuntimeError(f"Process terminated unexpectedly with code {self._proc.returncode}")
                # Check if model is ready (you may need to adjust this based on Foundry's output)
                time.sleep(0.5)
                # For now, assume ready after a brief delay
                if time.time() - ready_start > 3:
                    break
            print(f"Chat started with model: {model}", flush=True)
        except Exception as e:
            self._model_loaded = False
            if self._proc:
                try:
                    self._proc.terminate()
                except:
                    pass
                self._proc = None
            raise RuntimeError(f"Failed to start chat: {e}")

    def get_device_backend(self) -> Optional[str]:
        """Return the last detected device backend name (e.g., 'CUDA GPU', 'DirectML GPU', 'CPU')."""
        return self._device_backend

    def get_device_model(self) -> Optional[str]:
        """Return the detected GPU model string if available (e.g., 'NVIDIA GeForce RTX 3080')."""
        return self._device_model

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

    def _detect_device_model(self, s: str) -> Optional[str]:
        """Attempt to extract a detailed GPU model name from CLI output lines."""
        txt = (s or '').strip()
        if not txt:
            return None
        low = txt.lower()
        # Common patterns that include explicit adapter/device label
        pats = [
            re.compile(r"(?:selected|using)\s+(?:d3d12\s+)?(?:adapter|device)\s*[:=]\s*['\"]?(.+?)['\"]?$", re.IGNORECASE),
            re.compile(r"(?:cuda|nvidia).*(?:device|gpu)\s*[:=]\s*['\"]?(.+?)['\"]?$", re.IGNORECASE),
            re.compile(r"(?:directml|dml).*(?:device)\s*[:=]\s*['\"]?(.+?)['\"]?$", re.IGNORECASE),
            re.compile(r"(?:adapter|device)\s*[:=]\s*(NVIDIA.+|AMD.+|Intel.+)$", re.IGNORECASE),
        ]
        for r in pats:
            m = r.search(txt)
            if m:
                val = m.group(1).strip()
                return self._clean_model_name(val)
        # Heuristic: if a line mentions a known vendor and GPU context, capture substring from vendor
        if any(k in low for k in ('nvidia','geforce','quadro','tesla','amd','radeon','vega','intel','arc','iris')) and any(k in low for k in ('gpu','adapter','device','directml','dml','cuda','rocm','metal','mps')):
            m2 = re.search(r"(NVIDIA\s+.+|AMD\s+.+|Intel\s+.+)", txt, re.IGNORECASE)
            if m2:
                return self._clean_model_name(m2.group(1))
        return None

    def _clean_model_name(self, val: str) -> str:
        """Normalize a raw adapter string to a concise GPU model name."""
        s = (val or '').strip().strip('\"\'')
        # Cut off trailing descriptors like memory, driver, or brackets/parentheses
        s = re.split(r"\s*[\[(]|\s\|\s|\s-\s|\s@\s", s)[0].strip()
        # Remove trademark symbols
        s = s.replace('(TM)', '').replace('(R)', '').replace('®', '').replace('™', '').strip()
        # Collapse whitespace
        s = re.sub(r"\s+", " ", s)
        return s

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

    def send_prompt(self, prompt: str, chat_id: Optional[str] = None) -> Optional[str]:
        """Send prompt with robust error handling and process state validation."""
        # Check process state before attempting to write
        if not self._proc or self._proc.poll() is not None:
            print(f"Warning: Process not running, cannot send prompt", flush=True)
            return None
        # Check stdin state
        if not self._proc.stdin or self._proc.stdin.closed:
            print(f"Warning: Process stdin is closed, cannot send prompt", flush=True)
            return None
        # Initialize chat session if needed
        if chat_id:
            if chat_id not in self._chat_sessions:
                self._chat_sessions[chat_id] = []
            # Store the message in session history
            self._chat_sessions[chat_id].append({
                "role": "user",
                "content": prompt,
                "timestamp": time.time()
            })
            self._current_chat_id = chat_id
            # Build context from session history
            context = self._build_context_for_chat(chat_id)
            # Send context + prompt to model
            full_prompt = context + prompt if context else prompt
        else:
            full_prompt = prompt
        # Generate request ID for tracking
        req_id = f"req_{int(time.time() * 1000)}"
        self._current_request_id = req_id
        # Track tokens
        if self._current_chat_id:
            self._token_tracker.start_request(req_id, full_prompt, self._current_chat_id)
        try:
            # Encode properly for Windows
            if os.name == 'nt':
                # Windows requires specific encoding handling
                encoded_prompt = (full_prompt + "\n").encode('utf-8', errors='replace')
                self._proc.stdin.buffer.write(encoded_prompt)
                self._proc.stdin.buffer.flush()
            else:
                # Unix systems can use text mode
                self._proc.stdin.write(full_prompt + "\n")
                self._proc.stdin.flush()
            return req_id
        except (OSError, IOError, BrokenPipeError) as e:
            print(f"Error sending prompt (pipe broken): {e}", flush=True)
            # Mark process as dead and attempt cleanup
            self._handle_process_death()
            return None
        except Exception as e:
            print(f"Unexpected error sending prompt: {e}", flush=True)
            return None
    def _read_output(self) -> None:
        """Read output with proper non-blocking I/O and timeout handling."""
        import select
        acc = []
        last_flush = time.time()
        last_activity_time = time.time()
        timeout_duration = 30 if os.environ.get('PYTEST_CURRENT_TEST') else 60
        # Set non-blocking mode for Unix systems
        if os.name != 'nt' and self._proc and self._proc.stdout:
            try:
                import fcntl
                fd = self._proc.stdout.fileno()
                flags = fcntl.fcntl(fd, fcntl.F_GETFL)
                fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            except ImportError:
                pass  # fcntl not available on Windows        
        while not self._stop_event.is_set():
            try:
                if not self._proc or not self._proc.stdout:
                    break
                # Check if process is still alive
                if self._proc.poll() is not None:
                    # Process terminated, read any remaining output
                    try:
                        if os.name == 'nt':
                            # Windows: read remaining binary data
                            remaining = self._proc.stdout.buffer.read()
                            if remaining:
                                text = remaining.decode('utf-8', errors='replace')
                                for line in text.splitlines():
                                    self._process_line(line)
                        else:
                            # Unix: read remaining text
                            remaining = self._proc.stdout.read()
                            if remaining:
                                for line in remaining.splitlines():
                                    self._process_line(line)
                    except:
                        pass
                    break
                # Platform-specific non-blocking read
                if os.name == 'nt':
                    # Windows: Use threading with timeout
                    import queue as q
                    import threading
                    line_queue = q.Queue()
                    def read_line():
                        try:
                            # Read binary data on Windows
                            raw_line = self._proc.stdout.buffer.readline()
                            if raw_line:
                                line = raw_line.decode('utf-8', errors='replace')
                                line_queue.put(line)
                        except:
                            pass
                    reader = threading.Thread(target=read_line)
                    reader.daemon = True
                    reader.start()
                    try:
                        line = line_queue.get(timeout=0.5)
                        self._process_line(line.rstrip('\n'))
                        last_activity_time = time.time()
                    except q.Empty:
                        # No data available
                        if time.time() - last_activity_time > timeout_duration:
                            print(f"Reader thread timeout after {timeout_duration}s", flush=True)
                            break
                else:
                    # Unix: Use select for non-blocking read
                    try:
                        ready, _, _ = select.select([self._proc.stdout], [], [], 0.5)
                        
                        if ready:
                            try:
                                line = self._proc.stdout.readline()
                                if line:
                                    self._process_line(line.rstrip('\n'))
                                    last_activity_time = time.time()
                            except (IOError, OSError) as e:
                                if e.errno != 11:  # EAGAIN
                                    print(f"Read error: {e}", flush=True)
                                    break
                        else:
                            # Check for timeout
                            if time.time() - last_activity_time > timeout_duration:
                                print(f"Reader thread timeout after {timeout_duration}s", flush=True)
                                break
                    except Exception as e:
                        print(f"Select error: {e}", flush=True)
                        time.sleep(0.1)
                # Sleep briefly to prevent CPU spinning
                time.sleep(0.01)
            except Exception as e:
                if not self._stop_event.is_set():
                    print(f"Reader thread error: {e}", flush=True)
                break
        print("Reader thread exiting", flush=True)

    def _process_line(self, line: str) -> None:
        """Process a single line of output."""
        if not line:
            return
        # Queue the line
        try:
            self._stdout_q.put(line)
        except:
            pass
        # Call raw output handler
        if self._on_raw_output:
            try:
                self._on_raw_output(line)
            except Exception:
                pass        
        # Detect device backend
        backend = self._detect_device_backend(line)
        if backend:
            self._device_backend = backend
        # Detect device model
        model = self._detect_device_model(line)
        if model:
            self._device_model = model
        # Buffer for assistant messages
        self._buffer += line + "\n"
        # Check for assistant message pattern
        match = _ASSISTANT_BLOCK_RE.search(self._buffer)
        if match:
            # Extract and process assistant message
            content = match.group(1).strip()
            if content:
                self._on_assistant_msg(content)
            # Clear the processed part from buffer
            self._buffer = self._buffer[match.end():]
        # Flush buffer periodically
        self._flush_buffer_if_needed()

    def _flush_buffer_if_needed(self) -> None:
        """Flush buffer if timeout reached or buffer is large."""
        now = time.time()
        # Check if we should flush based on time
        if hasattr(self, '_last_flush_time'):
            if now - self._last_flush_time >= self._flush_secs:
                self._flush_buffer()
                self._last_flush_time = now
        else:
            self._last_flush_time = now
        # Also flush if buffer is getting large
        if len(self._buffer) > 4096:
            self._flush_buffer()

    def _flush_buffer(self) -> None:
        """Flush any remaining content in the buffer."""
        if self._buffer and self._on_assistant:
            # Only flush if it looks like content (not just whitespace)
            content = self._buffer.strip()
            if content and not content.startswith('<|'):
                # This might be fallback content
                try:
                    self._on_assistant(content)
                except:
                    pass
            self._buffer = ""

    def _handle_process_death(self) -> None:
        """Handle unexpected process termination."""
        print("Handling unexpected process termination...", flush=True)
        self._model_loaded = False
        # Stop the reader thread
        self._stop_event.set()
        # Clean up the dead process
        if self._proc:
            try:
                self._proc.terminate()
            except:
                pass
            try:
                self._proc.wait(timeout=1)
            except:
                pass
            self._proc = None
        # Clean up reader thread
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1)
        self._reader_thread = None

    def _build_context_for_chat(self, chat_id: str) -> str:
        """Build context from chat history with intelligent truncation."""
        if chat_id not in self._chat_sessions:
            return ""
        # Check cache first
        cache_key = f"{chat_id}_{len(self._chat_sessions[chat_id])}"
        if cache_key in self._context_cache:
            return self._context_cache[cache_key]
        messages = self._chat_sessions[chat_id]
        if not messages:
            return ""
        # Use context manager for intelligent truncation
        from .context_manager import ContextManager
        context_mgr = ContextManager(max_tokens=4096, reserve_tokens=512)
        # Convert to format expected by context manager
        formatted_messages = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in messages[:-1]  # Exclude current message
        ]
        # Get truncated messages that fit in context window
        truncated = context_mgr.truncate_messages(formatted_messages)
        # Build context string
        context_parts = []
        for msg in truncated:
            if msg["role"] == "user":
                context_parts.append(f"User: {msg['content']}")
            elif msg["role"] == "assistant":
                context_parts.append(f"Assistant: {msg['content']}")
        context = "\n".join(context_parts)
        if context:
            context += "\n\n"
        # Cache the context
        self._context_cache[cache_key] = context
        return context

    def _on_assistant_msg(self, txt: str) -> None:
        """Handle assistant messages with proper tracking."""
        if self._on_assistant:
            self._on_assistant(txt)
        # Store assistant response in session
        if self._current_chat_id:
            self._chat_sessions[self._current_chat_id].append({
                "role": "assistant",
                "content": txt,
                "timestamp": time.time()
            })
            
            # Complete token tracking
            if self._current_request_id:
                self._token_tracker.complete_request(
                    self._current_request_id,
                    txt,
                    self._current_chat_id
                )
        # Clear context cache for this chat as it's now stale
        cache_keys_to_remove = [
            k for k in self._context_cache.keys() 
            if k.startswith(f"{self._current_chat_id}_")
        ]
        for key in cache_keys_to_remove:
            del self._context_cache[key]

    def restore_chat_context(self, chat_id: str, messages: List[Dict]) -> None:
        """Restore context for a specific chat session."""
        if chat_id not in self._chat_sessions:
            self._chat_sessions[chat_id] = []
        
        # Clear existing messages and replace with provided ones
        self._chat_sessions[chat_id].clear()
        self._chat_sessions[chat_id].extend(messages)
        # Clear context cache for this chat
        cache_keys_to_remove = [
            k for k in self._context_cache.keys() 
            if k.startswith(f"{chat_id}_")
        ]
        for key in cache_keys_to_remove:
            del self._context_cache[key]

    def switch_chat(self, new_chat_id: str) -> None:
        """Switch to a different chat session."""
        self._current_chat_id = new_chat_id
        # Initialize session if it doesn't exist
        if new_chat_id not in self._chat_sessions:
            self._chat_sessions[new_chat_id] = []

    def clear_chat_session(self, chat_id: str) -> None:
        """Clear all messages for a specific chat."""
        if chat_id in self._chat_sessions:
            self._chat_sessions[chat_id].clear()        
        # Clear context cache
        cache_keys_to_remove = [
            k for k in self._context_cache.keys() 
            if k.startswith(f"{chat_id}_")
        ]
        for key in cache_keys_to_remove:
            del self._context_cache[key]

    def restart_with_context(self, model: str, messages: List[Dict], 
                         on_raw_output: Optional[Callable] = None,
                         on_assistant: Optional[Callable] = None) -> None:
        """Restart chat session with full conversation history."""
        # Stop existing session
        self.stop_chat()
        # Start new session  
        self.start_chat(model, on_raw_output, on_assistant)
        # Wait a moment for session to initialize
        time.sleep(0.5)
        # Replay conversation history (all except the last user message)
        for msg in messages[:-1]:
            if msg['role'] == 'user':
                self.send_prompt(msg['content'])
                # Wait for response to complete before next message
                time.sleep(1.0)
    
    def get_context_usage(self) -> Tuple[int, int]:
        """Return (used_tokens, max_tokens) for current context."""
        # Estimate based on current chat's token usage
        if self._current_chat_id:
            used_tokens = self._token_tracker.get_chat_total_tokens(self._current_chat_id)
            # Default context window size (can be made configurable)
            max_tokens = 4096
            return (used_tokens, max_tokens)
        return (0, 4096)
    
    def unload_model(self) -> None:
        """Aggressively unload model and release ALL resources."""
        print("Unloading model and cleaning up resources...", flush=True)
        with self._process_cleanup_lock:
            self._model_loaded = False
            # Set stop event first
            self._stop_event.set()
            # Kill process hierarchy (Windows)
            if os.name == 'nt' and self._proc:
                try:
                    # Use taskkill to kill process tree
                    pid = self._proc.pid
                    subprocess.run(
                        ['taskkill', '/F', '/T', '/PID', str(pid)],
                        capture_output=True,
                        timeout=5,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                except Exception as e:
                    print(f"Failed to kill process tree: {e}", flush=True)
            # Standard process termination
            if self._proc:
                try:
                    # Close stdin first to signal we're done
                    if self._proc.stdin and not self._proc.stdin.closed:
                        try:
                            self._proc.stdin.close()
                        except:
                            pass
                    # Try graceful termination
                    self._proc.terminate()
                    try:
                        self._proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        # Force kill if still running
                        self._proc.kill()
                        self._proc.wait(timeout=2)
                except Exception as e:
                    print(f"Error during process cleanup: {e}", flush=True)
                finally:
                    self._proc = None
            # Clean up reader thread
            if self._reader_thread and self._reader_thread.is_alive():
                self._reader_thread.join(timeout=3)
                if self._reader_thread.is_alive():
                    print("Warning: Reader thread did not terminate cleanly", flush=True)
            self._reader_thread = None
            # Clear all data structures
            self._chat_sessions.clear()
            self._context_cache.clear()
            self._current_chat_id = None
            self._current_request_id = None
            self._buffer = ""            
            # Force Python garbage collection
            import gc
            gc.collect()
            # Kill any orphaned Foundry processes
            self._kill_orphaned_processes()
            # Wait for GPU memory to be released
            time.sleep(1.0)
            # Verify cleanup
            if self._gpu_monitor:
                info = self._gpu_monitor.get_gpu_memory_usage()
                if info:
                    print(f"GPU memory after cleanup: {info.used_mb}MB", flush=True)

    def _kill_orphaned_processes(self) -> None:
        """Kill any orphaned Foundry processes not tracked by this instance."""
        try:
            if os.name == 'nt':
                # Windows: Kill all foundry.exe processes
                result = subprocess.run(
                    ['taskkill', '/F', '/IM', 'foundry.exe', '/T'],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                if result.returncode == 0:
                    print("Killed orphaned Foundry processes", flush=True)
            else:
                # Unix: Kill all foundry processes
                result = subprocess.run(
                    ['pkill', '-9', '-f', 'foundry'],
                    capture_output=True
                )
                if result.returncode == 0:
                    print("Killed orphaned Foundry processes", flush=True)
        except Exception as e:
            print(f"Could not kill orphaned processes: {e}", flush=True)
        
    def reload_model(self, model: str) -> None:
        """Reload model into GPU memory."""
        self.ensure_model_downloaded(model)
        # Model will be loaded when start_chat is called
        
    def is_model_loaded(self) -> bool:
        """Check if a model is currently loaded."""
        return self._model_loaded and self._proc is not None
        
    def get_gpu_memory_info(self) -> Optional[GPUMemoryInfo]:
        """Get current GPU memory usage information."""
        return self._gpu_monitor.get_gpu_memory_usage()
        
    def setup_gpu_monitoring(self, threshold_mb: int = 2048, 
                           on_threshold_exceeded: Optional[Callable[[GPUMemoryInfo], None]] = None) -> None:
        """Setup GPU memory monitoring with automatic model unloading."""
        self._gpu_monitor.set_threshold(threshold_mb)
        
        if on_threshold_exceeded:
            self._gpu_monitor.register_callback("foundry_cli", on_threshold_exceeded)
        else:
            # Default behavior: unload model when threshold exceeded
            def _default_threshold_handler(info: GPUMemoryInfo) -> None:
                if self.is_model_loaded():
                    self.unload_model()
            self._gpu_monitor.register_callback("foundry_cli", _default_threshold_handler)
        
        # Start monitoring if not already running
        if not self._gpu_monitor.is_monitoring():
            self._gpu_monitor.start_monitoring()

    def stop_chat(self) -> None:
        """Stop chat session with proper cleanup."""
        with self._process_cleanup_lock:
            self._stop_event.set()
            
            if self._proc and self._proc.poll() is None:
                try:
                    # Send exit command first
                    if self._proc.stdin and not self._proc.stdin.closed:
                        self._proc.stdin.write("exit\n")
                        self._proc.stdin.flush()
                    # Wait briefly for graceful exit
                    self._proc.wait(timeout=1)
                except (subprocess.TimeoutExpired, Exception):
                    # Force terminate
                    try:
                        self._proc.terminate()
                        self._proc.wait(timeout=1)
                    except (subprocess.TimeoutExpired, Exception):
                        self._proc.kill()
                        self._proc.wait()
            
            self._proc = None
            
            # Clean up reader thread
            if self._reader_thread and self._reader_thread.is_alive():
                self._reader_thread.join(timeout=2)
            self._reader_thread = None
            
            # Don't clear chat sessions on stop - they should persist
            self._model_loaded = False

    def get_chat_sessions(self) -> Dict[str, List[Dict]]:
        """Get all chat sessions (for testing compatibility)."""
        return self._chat_sessions

    def get_memory_usage(self) -> int:
        """Get current GPU memory usage in MB."""
        if self._gpu_monitor:
            info = self._gpu_monitor.get_gpu_memory_usage()
            return info.used_mb if info else 0
        return 0

    def force_garbage_collection(self) -> None:
        """Force garbage collection and memory cleanup."""
        # Clear all caches
        self._context_cache.clear()
        
        # Force Python garbage collection
        gc.collect()
        
        # If CUDA is available, clear CUDA cache
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

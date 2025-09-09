"""
Common utilities and classes for test suites.

Authors:
    - Benjamin Dourthe (benjamin@adonamed.com)
"""
import os
import sys
import time
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable, Union, Tuple
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
try:
    from core.foundry_cli import FoundryCLI
except ImportError:
    # Fallback for when core module is not available
    FoundryCLI = None

# Console formatting constants
WIDTH = 100
LABEL_WIDTH = 24
SEPARATOR = "─" * WIDTH
THICK_SEPARATOR = "=" * WIDTH
BOX_TOP_LEFT = "┌"
BOX_TOP_RIGHT = "┐"
BOX_BOTTOM_LEFT = "└"
BOX_BOTTOM_RIGHT = "┘"
BOX_HORIZONTAL = "─"
BOX_VERTICAL = "│"
BOX_CROSS = "┼"
BOX_T_DOWN = "┬"
BOX_T_UP = "┴"
BOX_T_RIGHT = "├"
BOX_T_LEFT = "┤"

class GPUMemoryInfo:
    """Mock GPU memory information for testing."""
    def __init__(self, used_mb: int = 0, total_mb: int = 8192, free_mb: Optional[int] = None):
        """Initialize GPU memory info with realistic values for testing."""
        self.used_mb = used_mb
        self.total_mb = total_mb
        self.free_mb = free_mb or (total_mb - used_mb)
        self.utilization_pct = (used_mb / total_mb) * 100 if total_mb > 0 else 0

class MockFoundryCLI:
    """Mock implementation of FoundryCLI for controlled testing."""
    def __init__(self):
        """Initialize mock CLI with controllable responses."""
        self._model_loaded = False
        self._current_model = None
        self._chat_sessions = {}  # ENSURE THIS EXISTS
        self._gpu_memory_base = 1024
        self._gpu_memory_current = self._gpu_memory_base
        self._response_delay = 0.1
        self._context_messages = []
        self._context_cache = {}
        self._process_cleanup_lock = threading.Lock()
        self._memory_baseline = None
        self._buffer = ""
        self._stop_event = threading.Event()
        self._current_request_id = None
        self._current_chat_id = None
        
    def is_installed(self) -> bool:
        """Always return True for testing."""
        return True
        
    def list_models(self) -> List[str]:
        """Return predefined test model list."""
        return getattr(self, '_available_models', ["gpt-oss-20b-cuda-gpu", "test-model-4b", "test-model-8b", "test-model-16b"])
        
    def start_chat(self, model: str, on_raw_output: Optional[Callable] = None, 
                   on_assistant: Optional[Callable] = None, flush_secs: float = 0.4) -> None:
        """Mock chat start with controllable memory usage."""
        self._current_model = model
        self._model_loaded = True
        # Simulate model loading memory increase
        model_size_map = {"gpt-oss-20b-cuda-gpu": 2560, "test-model-4b": 512, "test-model-8b": 1024, "test-model-16b": 2048}
        self._gpu_memory_current = self._gpu_memory_base + model_size_map.get(model, 512)
        
    def stop_chat(self) -> None:
        """Mock chat stop with memory cleanup."""
        self._model_loaded = False
        self._current_model = None
        self._gpu_memory_current = self._gpu_memory_base
        
    def send_prompt(self, prompt: str, chat_id: Optional[str] = None) -> Optional[str]:
        """Mock prompt sending with context tracking."""
        if chat_id:
            if chat_id not in self._chat_sessions:
                self._chat_sessions[chat_id] = []
            self._chat_sessions[chat_id].append({"role": "user", "content": prompt})
            # Simulate memory increase for context
            self._gpu_memory_current += len(prompt) // 10
        return f"req_{int(time.time()*1000)}"
        
    def get_gpu_memory_info(self) -> GPUMemoryInfo:
        """Return current mock GPU memory state."""
        return GPUMemoryInfo(
            used_mb=self._gpu_memory_current,
            total_mb=8192,
            free_mb=8192 - self._gpu_memory_current
        )
        
    def is_model_loaded(self) -> bool:
        """Return current model loading state."""
        return self._model_loaded
        
    def unload_model(self) -> None:
        """Mock model unloading with memory cleanup."""
        self._model_loaded = False
        self._gpu_memory_current = self._gpu_memory_base
        
    def get_context_usage(self) -> Tuple[int, int]:
        """Return mock context usage."""
        total_tokens = sum(len(msg["content"]) // 4 for session in self._chat_sessions.values() 
                          for msg in session)
        return (total_tokens, 4096)
    
    def _kill_orphaned_processes(self) -> None:
        """Mock implementation - no actual processes to kill."""
        pass
    
    def _handle_process_death(self) -> None:
        """Mock implementation - no actual process."""
        pass
    
    def _read_output(self) -> None:
        """Mock implementation - no actual output to read."""
        pass
    
    def _process_line(self, line: str) -> None:
        """Mock implementation - no actual processing."""
        pass
    
    def _flush_buffer_if_needed(self) -> None:
        """Mock implementation - no buffer to flush."""
        pass
    
    def _flush_buffer(self) -> None:
        """Mock implementation - no buffer to flush."""
        pass
    
    def _build_context_for_chat(self, chat_id: str) -> str:
        """Mock implementation - return empty context."""
        return ""
    
    def _on_assistant_msg(self, txt: str) -> None:
        """Mock implementation - no assistant message handling."""
        pass
    
    def restore_chat_context(self, chat_id: str, messages: List[Dict]) -> None:
        """Mock implementation - restore chat context."""
        if chat_id not in self._chat_sessions:
            self._chat_sessions[chat_id] = []
        self._chat_sessions[chat_id].clear()
        self._chat_sessions[chat_id].extend(messages)
    
    def switch_chat(self, new_chat_id: str) -> None:
        """Mock implementation - switch to different chat."""
        self._current_chat_id = new_chat_id
        if new_chat_id not in self._chat_sessions:
            self._chat_sessions[new_chat_id] = []
    
    def clear_chat_session(self, chat_id: str) -> None:
        """Mock implementation - clear chat session."""
        if chat_id in self._chat_sessions:
            self._chat_sessions[chat_id].clear()
    
    def get_chat_sessions(self) -> Dict[str, List[Dict]]:
        """Mock implementation - return chat sessions for testing."""
        return self._chat_sessions.copy()
    
    def get_memory_usage(self) -> int:
        """Mock implementation - return mock memory usage."""
        return self._gpu_memory_current
    
    def reload_model(self, model: str) -> None:
        """Mock implementation - reload model."""
        self.unload_model()
        time.sleep(0.1)
        self._model_loaded = True
        self._current_model = model
        self._gpu_memory_current = self._gpu_memory_base + 2048

class MockStorage:
    """Mock storage implementation for testing."""
    def __init__(self):
        """Initialize mock storage with in-memory data."""
        self._chats = {}
        self._settings = {"gpu_memory_threshold_mb": 2048, "idle_timeout_minutes": 5}
        
    def create_chat(self, title: str) -> str:
        """Create mock chat and return ID."""
        chat_id = f"test_chat_{len(self._chats)}"
        self._chats[chat_id] = {"id": chat_id, "title": title, "messages": []}
        return chat_id
        
    def load_chat(self, chat_id: str) -> Optional[Dict]:
        """Load mock chat data."""
        return self._chats.get(chat_id)
        
    def save_messages(self, chat_id: str, messages: List[Dict]) -> None:
        """Save messages to mock chat."""
        if chat_id in self._chats:
            self._chats[chat_id]["messages"] = messages
            
    def delete_chat(self, chat_id: str) -> None:
        """Delete mock chat."""
        if chat_id in self._chats:
            del self._chats[chat_id]
            
    def get_app_settings(self) -> Dict:
        """Return mock app settings."""
        return self._settings.copy()

class PerformanceTimer:
    """Utility for precise performance timing."""
    def __init__(self):
        """Initialize timer with high-resolution counter."""
        self.start_time = None
        self.end_time = None
        
    def start(self) -> None:
        """Start timing measurement."""
        self.start_time = time.perf_counter()
        
    def stop(self) -> float:
        """Stop timing and return elapsed seconds."""
        self.end_time = time.perf_counter()
        if self.start_time is None:
            return 0.0
        return self.end_time - self.start_time
        
    def elapsed(self) -> float:
        """Return current elapsed time without stopping."""
        if self.start_time is None:
            return 0.0
        return time.perf_counter() - self.start_time

class TestResultAggregator:
    """Aggregate and format test results."""
    def __init__(self, suite_name: str):
        """Initialize result aggregator for a test suite."""
        self.suite_name = suite_name
        self.results = []
        self.start_time = datetime.now()
        
    def add_result(self, test_name: str, status: str, performance: str, 
                   metrics: Dict[str, Any], passed: bool) -> None:
        """Add a test result to the aggregator."""
        self.results.append({
            "name": test_name,
            "status": status,
            "performance": performance,
            "metrics": metrics,
            "passed": passed
        })
        
    def get_summary_table(self) -> str:
        """Generate formatted summary table with proper column alignment."""
        if not self.results:
            return "No test results to display."
        header = f"┌{'─' * 38}┬{'─' * 10}┬{'─' * 8}┐"
        separator = f"├{'─' * 38}┼{'─' * 10}┼{'─' * 8}┤"
        footer = f"└{'─' * 38}┴{'─' * 10}┴{'─' * 8}┘"
        title_row = f"│ {'Test Name':<36} │ {'Result':^8} │ {'Status':^5} │"
        rows = [header, title_row, separator]
        for result in self.results:
            name = result["name"][:36]
            status_icon = "✅" if result["passed"] else "❌"
            perf = result["performance"][:12]
            result_text = f"{len([r for r in self.results if r['passed']])}/{len(self.results)}"[:8]
            row = f"│ {name:<36} │ {result_text:^8} │ {status_icon:^5} │"
            rows.append(row)
        rows.append(footer)
        return "\n".join(rows)
        
    def get_pass_rate(self) -> float:
        """Calculate overall pass rate."""
        if not self.results:
            return 0.0
        passed = sum(1 for r in self.results if r["passed"])
        return (passed / len(self.results)) * 100

def format_console_output(test_num: int, test_name: str, description: str, 
                         metrics: Dict[str, Any], result: str, passed: bool) -> str:
    """Format test output with proper alignment."""
    lines = []
    lines.append("")
    lines.append(f"[TEST {test_num}] {test_name}")
    lines.append(SEPARATOR)
    lines.append(f"{'Description:':<{LABEL_WIDTH}}{description}")
    
    # Print all metrics with consistent alignment
    for key, value in metrics.items():
        lines.append(f"{key + ':':<{LABEL_WIDTH}}{value}")
    
    # Print result line with dots
    result_prefix = f"{'Result:':<{LABEL_WIDTH}}{result} "
    dots_needed = max(1, WIDTH - len(result_prefix) - 3)
    dots = "." * dots_needed
    status_icon = "✅" if passed else "❌"
    lines.append(f"{result_prefix}{dots} {status_icon}")
    
    return "\n".join(lines)

def print_suite_header(suite_name: str) -> None:
    """Print standardized test suite header."""
    print(THICK_SEPARATOR, flush=True)
    print(f"{suite_name:^{WIDTH}}", flush=True)
    print(SEPARATOR, flush=True)
    print(f"Test started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)

def print_suite_footer(aggregator: TestResultAggregator) -> None:
    """Print standardized test suite footer."""
    print("", flush=True)
    print(SEPARATOR, flush=True)
    print(f"{'TEST SUITE SUMMARY':^{WIDTH}}", flush=True)
    print(SEPARATOR, flush=True)
    print("", flush=True)
    print(aggregator.get_summary_table(), flush=True)
    print("", flush=True)
    passed_count = sum(1 for r in aggregator.results if r["passed"])
    total_count = len(aggregator.results)
    pass_rate = aggregator.get_pass_rate()
    duration = (datetime.now() - aggregator.start_time).total_seconds()
    print(f"Tests Passed:        {passed_count}/{total_count}", flush=True)
    print(f"Pass Threshold:      80%", flush=True)
    print(f"Test Duration:       {duration:.0f} seconds", flush=True)
    print(SEPARATOR, flush=True)
    final_status = "✅" if pass_rate >= 80.0 else "❌"
    print(f"TEST STATUS: {final_status}  with {pass_rate:.0f}% tests passed", flush=True)
    print(THICK_SEPARATOR, flush=True)

def create_test_conversations() -> List[Dict]:
    """Create standardized test conversation data."""
    return [
        {
            "messages": [
                {"role": "user", "content": "What is the capital of France?"},
                {"role": "assistant", "content": "The capital of France is Paris."},
                {"role": "user", "content": "What about Germany?"},
                {"role": "assistant", "content": "The capital of Germany is Berlin."},
                {"role": "user", "content": "Which city did we discuss first?"},
            ],
            "expected_facts": ["Paris", "France", "Berlin", "Germany"],
            "context_test": "Which city did we discuss first?"
        },
        {
            "messages": [
                {"role": "user", "content": "My name is Alice and I like chocolate."},
                {"role": "assistant", "content": "Nice to meet you, Alice! Chocolate is delicious."},
                {"role": "user", "content": "I also have a cat named Whiskers."},
                {"role": "assistant", "content": "That's wonderful! Whiskers sounds like a great companion."},
                {"role": "user", "content": "What do you remember about me?"},
            ],
            "expected_facts": ["Alice", "chocolate", "cat", "Whiskers"],
            "context_test": "What do you remember about me?"
        }
    ]

_cached_test_model = None

def detect_downloaded_models() -> List[str]:
    """Detect actually downloaded Foundry Local models with fallbacks."""
    # Check environment variable for testing mode
    use_real = os.environ.get('USE_REAL_FOUNDRY', 'false').lower() == 'true'
    
    if not use_real:
        # In mock mode, return a default test model to allow tests to run
        return ["gpt-oss-20b-cuda-gpu"]
    
    try:
        # Import here to avoid circular imports
        if FoundryCLI is None:
            return []
            
        real_cli = FoundryCLI()
        
        # Check if Foundry is installed
        if not hasattr(real_cli, 'is_installed') or not callable(real_cli.is_installed):
            return []
            
        if not real_cli.is_installed():
            return []
        
        # Get models from Foundry CLI with proper error handling
        if not hasattr(real_cli, 'list_models') or not callable(real_cli.list_models):
            return []
            
        available_models = real_cli.list_models()
        if not available_models:
            return []
        
        # Prioritize gpt-oss-20b models first
        prioritized = []
        other_models = []
        
        for model in available_models:
            if "gpt-oss-20b" in model.lower():
                prioritized.append(model)
            else:
                other_models.append(model)
        
        return prioritized + other_models
        
    except Exception as e:
        # Don't spam the console with warnings - just return empty list
        return []

def get_test_model() -> str:
    """Get the best available model for testing, with fallback."""
    global _cached_test_model
    
    # Return cached result to avoid repeated detection
    if _cached_test_model is not None:
        return _cached_test_model
    
    # Check if we're in mock mode first
    use_real = os.environ.get('USE_REAL_FOUNDRY', 'false').lower() == 'true'
    
    if not use_real:
        # In mock mode, always return a default model
        _cached_test_model = "gpt-oss-20b-cuda-gpu"
        return _cached_test_model
    
    downloaded_models = detect_downloaded_models()
    
    if not downloaded_models:
        # Fall back to mock mode if no real models available
        print("Warning: No Foundry models detected, falling back to mock mode", flush=True)
        os.environ['USE_REAL_FOUNDRY'] = 'false'
        _cached_test_model = "gpt-oss-20b-cuda-gpu"
        return _cached_test_model
    
    # Cache and return the first (best) model
    _cached_test_model = downloaded_models[0]
    return _cached_test_model

def setup_test_environment(use_real: bool = False) -> Tuple[Union[FoundryCLI, MockFoundryCLI], Union[Any, MockStorage]]:
    """Set up test environment with real or mock CLI based on flag."""
    if use_real:
        try:
            # Verify we have models available before using real CLI
            if not detect_downloaded_models():
                print("Warning: No downloaded models found, falling back to mock CLI")
                return _setup_mock_environment()
            
            from core.foundry_cli import FoundryCLI
            try:
                from core import storage
                return FoundryCLI(), storage
            except ImportError:
                # If storage module doesn't exist, use mock storage with real CLI
                return FoundryCLI(), MockStorage()
                
        except Exception as e:
            print(f"Warning: Could not use real Foundry CLI ({e}), falling back to mock")
            return _setup_mock_environment()
    else:
        return _setup_mock_environment()

def _setup_mock_environment() -> Tuple[MockFoundryCLI, MockStorage]:
    """Set up mock environment for testing."""
    foundry_cli = MockFoundryCLI()
    storage = MockStorage()
    
    # Try to use real model names in mock for more realistic testing
    try:
        real_models = detect_downloaded_models()
        if real_models:
            foundry_cli._available_models = real_models + foundry_cli.list_models()
    except Exception:
        pass  # Fall back to default mock models
    
    return foundry_cli, storage

def cleanup_test_environment() -> None:
    """Clean up test environment resources."""
    pass

def calculate_percentiles(values: List[float]) -> Dict[str, float]:
    """Calculate performance percentiles."""
    if not values:
        return {"p50": 0.0, "p90": 0.0, "p99": 0.0}
    sorted_values = sorted(values)
    n = len(sorted_values)
    return {
        "p50": sorted_values[int(n * 0.5)] if n > 0 else 0.0,
        "p90": sorted_values[int(n * 0.9)] if n > 0 else 0.0,
        "p99": sorted_values[int(n * 0.99)] if n > 0 else 0.0,
    }

def save_test_results(suite_name: str, results: Dict) -> None:
    """Save test results to JSON file."""
    results_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tests", "results")
    os.makedirs(results_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{suite_name.lower().replace(' ', '_')}_{timestamp}.json"
    filepath = os.path.join(results_dir, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

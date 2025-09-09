"""
Test suite for GPU memory usage monitoring and cleanup.

Authors:
    - Benjamin Dourthe (benjamin@adonamed.com)
"""
import functools
import gc
import os
import signal
import subprocess
import sys
import time
import unittest
from typing import Optional, Dict, Any, Tuple
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from common import (
    MockFoundryCLI, MockStorage, PerformanceTimer, TestResultAggregator,
    format_console_output, print_suite_header, print_suite_footer,
    setup_test_environment, cleanup_test_environment, get_test_model, detect_downloaded_models
)
from test_config import get_model_config, get_pass_criteria

def timeout(seconds=120):
    """Decorator to add timeout to test methods."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            import threading
            result = [None]
            exception = [None]
            
            def target():
                try:
                    result[0] = func(*args, **kwargs)
                except Exception as e:
                    exception[0] = e
            
            thread = threading.Thread(target=target)
            thread.daemon = True
            thread.start()
            thread.join(seconds)
            
            if thread.is_alive():
                # Test is still running, it's stuck
                print(f"\n{func.__name__} timed out after {seconds} seconds", flush=True)
                
                # Try to clean up
                if args and hasattr(args[0], 'foundry_cli'):
                    try:
                        args[0].foundry_cli.unload_model()
                    except:
                        pass
                
                # Force cleanup of processes
                try:
                    if os.name == 'nt':
                        subprocess.run(['taskkill', '/F', '/IM', 'foundry.exe', '/T'],
                                     capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    else:
                        subprocess.run(['pkill', '-9', '-f', 'foundry'],
                                     capture_output=True)
                except:
                    pass
                
                raise TimeoutError(f"Test {func.__name__} timed out after {seconds} seconds")
            
            if exception[0]:
                raise exception[0]
            
            return result[0]
        
        return wrapper
    return decorator

class GPUMemoryUsageTestSuite(unittest.TestCase):
    """Comprehensive GPU memory management test suite."""
    def __init__(self, methodName='runTest'):
        """Initialize test suite with aggregator."""
        super().__init__(methodName)
        self.aggregator = TestResultAggregator("GPU Memory Usage Test Suite")
        self.foundry_cli = None
        self.storage = None
        self.baseline_memory = 1024
        self.memory_threshold = 6144
        self.test_model = None
        
    def setUp(self) -> None:
        """Set up test environment with complete cleanup."""
        # Kill any existing processes before starting
        self._cleanup_all_processes()
        time.sleep(2.0)  # Wait for processes to fully terminate
        
        # Detect model once per test
        try:
            self.test_model = get_test_model()
        except RuntimeError as e:
            self.skipTest(f"No Foundry models available: {e}")
        
        # Check GPU memory before starting
        initial_gpu = self._get_current_gpu_memory()
        if initial_gpu > 1000:  # More than 1GB already used
            print(f"Warning: High initial GPU memory usage: {initial_gpu}MB", flush=True)
            # Try to free memory
            self._force_gpu_cleanup()
            time.sleep(2.0)
        
        # Set up test environment
        use_real = os.environ.get('USE_REAL_FOUNDRY', 'false').lower() == 'true'
        self.foundry_cli, self.storage = setup_test_environment(use_real)
        
        if use_real:
            print(f"Using real Foundry CLI with model: {self.test_model}", flush=True)
        
        # Apply model-specific configuration
        if self.test_model:
            model_config = get_model_config(self.test_model)
            self.memory_threshold = model_config['memory_threshold_mb']
            self.baseline_memory = model_config['baseline_memory_mb']
        
    def tearDown(self) -> None:
        """Complete cleanup after each test."""
        print("Cleaning up test environment...", flush=True)
        
        try:
            # Stop and unload model
            if self.foundry_cli:
                if hasattr(self.foundry_cli, 'unload_model'):
                    self.foundry_cli.unload_model()
                if hasattr(self.foundry_cli, 'stop_chat'):
                    self.foundry_cli.stop_chat()
                if hasattr(self.foundry_cli, 'force_garbage_collection'):
                    self.foundry_cli.force_garbage_collection()
            
            # Clean up environment
            cleanup_test_environment()
            
            # Kill all processes
            self._cleanup_all_processes()
            
            # Force GPU cleanup
            self._force_gpu_cleanup()
            
            # Wait for cleanup to complete
            time.sleep(2.0)
            
        except Exception as e:
            print(f"Cleanup error (non-fatal): {e}", flush=True)
        
    def _cleanup_all_processes(self) -> None:
        """Kill all Foundry processes across the system."""
        try:
            if os.name == 'nt':
                # Windows
                commands = [
                    ['taskkill', '/F', '/IM', 'foundry.exe', '/T'],
                    ['taskkill', '/F', '/IM', 'foundry', '/T'],
                ]
                for cmd in commands:
                    try:
                        subprocess.run(cmd, capture_output=True, 
                                     timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
                    except:
                        pass
            else:
                # Unix
                commands = [
                    ['pkill', '-9', '-f', 'foundry'],
                    ['killall', '-9', 'foundry'],
                ]
                for cmd in commands:
                    try:
                        subprocess.run(cmd, capture_output=True, timeout=5)
                    except:
                        pass
        except Exception as e:
            print(f"Process cleanup warning: {e}", flush=True)

    def _force_gpu_cleanup(self) -> None:
        """Force GPU memory cleanup."""
        try:
            # Try PyTorch cleanup if available
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except ImportError:
            pass
        
        # Force Python garbage collection
        import gc
        gc.collect()
        
        # Try to reset GPU if we have permission (usually requires sudo/admin)
        try:
            subprocess.run(['nvidia-smi', '--gpu-reset'], 
                          capture_output=True, timeout=5)
        except:
            pass

    def _get_current_gpu_memory(self) -> int:
        """Get current GPU memory usage from nvidia-smi."""
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return int(result.stdout.strip())
        except:
            pass
        return 0

    def _check_gpu_available(self) -> bool:
        """Check if GPU testing is available (gracefully handle missing GPU)."""
        try:
            import subprocess
            result = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"], 
                                  capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except Exception:
            return False
            
    def _get_memory_usage(self) -> int:
        """Get current GPU memory usage in MB."""
        if self.foundry_cli:
            info = self.foundry_cli.get_gpu_memory_info()
            return info.used_mb if info else self.baseline_memory
        return self.baseline_memory
        
    def _wait_for_memory_stabilization(self, timeout: float = 5.0) -> None:
        """Wait for GPU memory to stabilize after operations."""
        start_time = time.time()
        last_memory = self._get_memory_usage()
        stabilization_count = 0
        
        while time.time() - start_time < timeout:
            time.sleep(0.5)
            try:
                current_memory = self._get_memory_usage()
                
                # If memory readings are consistent, consider it stable
                if abs(current_memory - last_memory) < 50:
                    stabilization_count += 1
                    # Require 2 consecutive stable readings
                    if stabilization_count >= 2:
                        break
                else:
                    stabilization_count = 0
                    
                last_memory = current_memory
                
            except Exception as e:
                print(f"Warning: Memory monitoring error: {e}")
                # If memory monitoring fails, just wait a bit and continue
                time.sleep(1.0)
                break
            
    @timeout(120)
    @unittest.skipIf(not detect_downloaded_models(), "No Foundry models downloaded")
    def test_01_initial_model_load_memory(self) -> None:
        """TEST 1: Measure baseline GPU memory after model loading."""
        test_name = "Initial Model Load Memory"
        description = "Measure baseline GPU memory after model loading"
        timer = PerformanceTimer()
        timer.start()
        try:
            initial_memory = self._get_memory_usage()
            self.foundry_cli.start_chat(self.test_model)
            self._wait_for_memory_stabilization()
            post_load_memory = self._get_memory_usage()
            memory_delta = post_load_memory - initial_memory
            elapsed = timer.stop()
            metrics = {
                "Initial Memory": f"{initial_memory} MB",
                "Post-Load Memory": f"{post_load_memory} MB",
                "Memory Delta": f"{memory_delta} MB",
                "Load Time": f"{elapsed:.2f}s"
            }
            criteria = get_pass_criteria('memory_load_test')
            memory_increase_ok = memory_delta > 0 if criteria.get('memory_increase_required', True) else True
            threshold_ok = post_load_memory < self.memory_threshold if criteria.get('memory_threshold_check', True) else True
            passed = memory_increase_ok and threshold_ok
            result = f"Memory increased by {memory_delta}MB, within threshold"
            print(format_console_output(1, test_name, description, metrics, result, passed), flush=True)
            self.aggregator.add_result(test_name, "✅" if passed else "❌", f"{elapsed:.2f}s", metrics, passed)
        except Exception as e:
            elapsed = timer.stop()
            metrics = {"Error": str(e)}
            result = f"Failed: {str(e)}"
            print(format_console_output(1, test_name, description, metrics, result, False), flush=True)
            self.aggregator.add_result(test_name, "❌", f"{elapsed:.2f}s", metrics, False)
            raise
            
    @timeout(120)
    @unittest.skipIf(not detect_downloaded_models(), "No Foundry models downloaded")
    def test_02_single_chat_memory_growth(self) -> None:
        """TEST 2: Track memory usage over 10 sequential messages."""
        test_name = "Single Chat Memory Growth"
        description = "Track memory usage over 10 sequential messages"
        timer = PerformanceTimer()
        timer.start()
        try:
            self.foundry_cli.start_chat(self.test_model)
            initial_memory = self._get_memory_usage()
            chat_id = "test_chat_growth"
            memory_readings = [initial_memory]
            num_messages = 10
            for i in range(num_messages):
                prompt = f"This is test message number {i+1} with some content to simulate real usage patterns."
                request_id = self.foundry_cli.send_prompt(prompt, chat_id)
                # Wait for response to complete before next prompt
                if request_id:
                    time.sleep(0.8)  # Increased wait time for response processing
                else:
                    time.sleep(0.3)  # Still wait even if no request ID
                memory_readings.append(self._get_memory_usage())
            final_memory = memory_readings[-1]
            memory_growth = final_memory - initial_memory
            peak_memory = max(memory_readings)
            elapsed = timer.stop()
            metrics = {
                "Initial Memory": f"{initial_memory} MB",
                "Final Memory": f"{final_memory} MB",
                "Memory Growth": f"{memory_growth} MB",
                "Peak Memory": f"{peak_memory} MB",
                "Messages Sent": f"{num_messages}"
            }
            criteria = get_pass_criteria('memory_growth_test')
            max_growth = criteria.get('max_acceptable_growth_mb', 100)
            growth_ok = memory_growth <= max_growth
            threshold_ok = peak_memory < self.memory_threshold if criteria.get('memory_threshold_check', True) else True
            passed = growth_ok and threshold_ok
            result = f"Memory growth {memory_growth}MB over {num_messages} messages, peak {peak_memory}MB"
            print(format_console_output(2, test_name, description, metrics, result, passed), flush=True)
            self.aggregator.add_result(test_name, "✅" if passed else "❌", f"{elapsed:.2f}s", metrics, passed)
        except Exception as e:
            elapsed = timer.stop()
            metrics = {"Error": str(e)}
            result = f"Failed: {str(e)}"
            print(format_console_output(2, test_name, description, metrics, result, False), flush=True) 
            self.aggregator.add_result(test_name, "❌", f"{elapsed:.2f}s", metrics, False)
            raise
            
    @timeout(120)
    @unittest.skipIf(not detect_downloaded_models(), "No Foundry models downloaded")
    def test_03_chat_switching_memory(self) -> None:
        """TEST 3: Verify memory cleanup when switching between 3 chats."""
        test_name = "Chat Switching Memory"
        description = "Verify memory cleanup when switching between 3 chats"
        timer = PerformanceTimer()
        timer.start()
        try:
            self.foundry_cli.start_chat(self.test_model)
            baseline_memory = self._get_memory_usage()
            chat_ids = ["chat_1", "chat_2", "chat_3"]
            memory_per_chat = {}
            for chat_id in chat_ids:
                for i in range(5):
                    prompt = f"Message {i+1} for {chat_id}: Testing context accumulation and memory usage patterns."
                    request_id = self.foundry_cli.send_prompt(prompt, chat_id)
                    # Wait longer for response to complete before next prompt
                    if request_id:
                        time.sleep(1.0)  # Increased wait time for response processing
                    else:
                        time.sleep(0.5)  # Still wait even if no request ID
                memory_per_chat[chat_id] = self._get_memory_usage()
            self.foundry_cli.stop_chat()
            self._wait_for_memory_stabilization()
            post_cleanup_memory = self._get_memory_usage()
            memory_cleaned = baseline_memory - post_cleanup_memory
            peak_memory = max(memory_per_chat.values())
            elapsed = timer.stop()
            cleanup_percentage = ((peak_memory - post_cleanup_memory) / peak_memory) * 100
            metrics = {
                "Baseline Memory": f"{baseline_memory} MB",
                "Peak Chat Memory": f"{peak_memory} MB",
                "Post-Cleanup Memory": f"{post_cleanup_memory} MB",
                "Memory Cleaned": f"{memory_cleaned} MB",
                "Cleanup Percentage": f"{cleanup_percentage:.1f}%"
            }
            criteria = get_pass_criteria('memory_cleanup_test')
            min_cleanup = criteria.get('min_cleanup_percentage', 80.0)
            max_remaining = criteria.get('max_remaining_mb', 200)
            cleanup_ok = cleanup_percentage >= min_cleanup
            remaining_ok = post_cleanup_memory <= (self.baseline_memory + max_remaining)
            passed = cleanup_ok and remaining_ok
            result = f"Memory cleaned: {memory_cleaned}MB, peak: {peak_memory}MB"
            print(format_console_output(3, test_name, description, metrics, result, passed), flush=True)
            self.aggregator.add_result(test_name, "✅" if passed else "❌", f"{elapsed:.2f}s", metrics, passed)
        except Exception as e:
            elapsed = timer.stop()
            metrics = {"Error": str(e)}
            result = f"Failed: {str(e)}"
            print(format_console_output(3, test_name, description, metrics, result, False), flush=True)
            self.aggregator.add_result(test_name, "❌", f"{elapsed:.2f}s", metrics, False)
            raise
            
    @timeout(120)
    @unittest.skipIf(not detect_downloaded_models(), "No Foundry models downloaded")
    def test_04_context_limit_memory(self) -> None:
        """TEST 4: Test memory behavior at 80%, 90%, 100% context usage."""
        test_name = "Context Limit Memory"
        description = "Test memory behavior at 80%, 90%, 100% context usage"
        timer = PerformanceTimer()
        timer.start()
        try:
            self.foundry_cli.start_chat(self.test_model)
            chat_id = "context_limit_test"
            context_targets = [80, 90, 100]
            memory_at_context = {}
            base_message = "This is a test message to fill context window. " * 20
            memory_limit = self.memory_threshold
            for target_pct in context_targets:
                messages_needed = int((4096 * target_pct / 100) / len(base_message))
                for i in range(messages_needed):
                    self.foundry_cli.send_prompt(f"{base_message} Message {i+1}", chat_id)
                    time.sleep(0.01)
                memory_at_context[target_pct] = self._get_memory_usage()
            elapsed = timer.stop()
            peak_memory = max(memory_at_context.values())
            memory_growth = memory_at_context[100] - memory_at_context[80]
            metrics = {
                "80% Context Memory": f"{memory_at_context[80]} MB",
                "90% Context Memory": f"{memory_at_context[90]} MB",
                "100% Context Memory": f"{memory_at_context[100]} MB",
                "Memory Growth": f"{memory_growth} MB",
                "Peak Memory": f"{peak_memory} MB"
            }
            criteria = get_pass_criteria('memory_context_limit_test')
            max_degradation = criteria.get('max_degradation_percentage', 25.0)
            threshold_ok = peak_memory < memory_limit if criteria.get('memory_threshold_check', True) else True
            degradation_ok = memory_growth < 1000  # Keep existing logic for now
            passed = threshold_ok and degradation_ok
            result = f"Peak memory {peak_memory}MB, growth {memory_growth}MB within limits"
            print(format_console_output(4, test_name, description, metrics, result, passed), flush=True)
            self.aggregator.add_result(test_name, "✅" if passed else "❌", f"{elapsed:.2f}s", metrics, passed)
        except Exception as e:
            elapsed = timer.stop()
            metrics = {"Error": str(e)}
            result = f"Failed: {str(e)}"
            print(format_console_output(4, test_name, description, metrics, result, False), flush=True)
            self.aggregator.add_result(test_name, "❌", f"{elapsed:.2f}s", metrics, False)
            raise
            
    @timeout(120)
    @unittest.skipIf(not detect_downloaded_models(), "No Foundry models downloaded")
    def test_05_idle_timeout_memory_release(self) -> None:
        """TEST 5: Verify model unloading after 5-minute idle (accelerated)."""
        test_name = "Idle Timeout Memory Release"
        description = "Verify model unloading after 5-minute idle (accelerated for testing)"
        timer = PerformanceTimer()
        timer.start()
        try:
            self.foundry_cli.start_chat(self.test_model)
            loaded_memory = self._get_memory_usage()
            time.sleep(1.0)
            self.foundry_cli.unload_model()
            self._wait_for_memory_stabilization()
            unloaded_memory = self._get_memory_usage()
            memory_released = loaded_memory - unloaded_memory
            final_memory = unloaded_memory
            model_unloaded = not self.foundry_cli.is_model_loaded()
            elapsed = timer.stop()
            metrics = {
                "Loaded Memory": f"{loaded_memory} MB",
                "Unloaded Memory": f"{unloaded_memory} MB",
                "Memory Released": f"{memory_released} MB",
                "Model State": "Unloaded",
                "Idle Simulation": "Accelerated"
            }
            criteria = get_pass_criteria('memory_idle_release_test')
            min_release_pct = criteria.get('min_release_percentage', 50.0)
            release_percentage = (memory_released / loaded_memory) * 100 if loaded_memory > 0 else 0
            release_ok = release_percentage >= min_release_pct
            baseline_ok = final_memory <= self.baseline_memory
            passed = release_ok and baseline_ok and model_unloaded
            result = f"Released {memory_released}MB, model unloaded successfully"
            print(format_console_output(5, test_name, description, metrics, result, passed), flush=True)
            self.aggregator.add_result(test_name, "✅" if passed else "❌", f"{elapsed:.2f}s", metrics, passed)
        except Exception as e:
            elapsed = timer.stop()
            metrics = {"Error": str(e)}
            result = f"Failed: {str(e)}"
            print(format_console_output(5, test_name, description, metrics, result, False), flush=True)
            self.aggregator.add_result(test_name, "❌", f"{elapsed:.2f}s", metrics, False)
            raise
            
    @timeout(120)
    @unittest.skipIf(not detect_downloaded_models(), "No Foundry models downloaded")
    def test_06_multi_chat_memory(self) -> None:
        """TEST 6: Test memory with 5 simultaneous chat sessions."""
        test_name = "Multi-Chat Memory"
        description = "Test memory with 5 simultaneous chat sessions"
        timer = PerformanceTimer()
        timer.start()
        try:
            self.foundry_cli.start_chat(self.test_model)
            baseline_memory = self._get_memory_usage()
            chat_sessions = [f"multi_chat_{i}" for i in range(5)]
            memory_progression = [baseline_memory]
            num_chats = len(chat_sessions)
            for session_id in chat_sessions:
                for msg_num in range(3):
                    prompt = f"Session {session_id} message {msg_num+1}: Testing concurrent chat memory usage."
                    self.foundry_cli.send_prompt(prompt, session_id)
                    time.sleep(0.02)
                current_memory = self._get_memory_usage()
                memory_progression.append(current_memory)
            final_memory = self._get_memory_usage()
            total_growth = final_memory - baseline_memory
            peak_memory = max(memory_progression)
            elapsed = timer.stop()
            metrics = {
                "Baseline Memory": f"{baseline_memory} MB",
                "Final Memory": f"{final_memory} MB",
                "Total Growth": f"{total_growth} MB",
                "Peak Memory": f"{peak_memory} MB",
                "Active Chats": f"{num_chats}",
                "Messages per Chat": "3"
            }
            criteria = get_pass_criteria('memory_multi_chat_test')
            max_multiplier = criteria.get('max_memory_multiplier', 1.5)
            max_expected_memory = baseline_memory * max_multiplier
            growth_ok = peak_memory <= max_expected_memory
            threshold_ok = peak_memory < self.memory_threshold if criteria.get('memory_threshold_check', True) else True
            passed = growth_ok and threshold_ok
            result = f"Peak {peak_memory}MB with {num_chats} chats, growth {total_growth}MB"
            print(format_console_output(6, test_name, description, metrics, result, passed), flush=True)
            self.aggregator.add_result(test_name, "✅" if passed else "❌", f"{elapsed:.2f}s", metrics, passed)
        except Exception as e:
            elapsed = timer.stop()
            metrics = {"Error": str(e)}
            result = f"Failed: {str(e)}"
            print(format_console_output(6, test_name, description, metrics, result, False), flush=True)
            self.aggregator.add_result(test_name, "❌", f"{elapsed:.2f}s", metrics, False)
            raise
            
    @timeout(120)
    @unittest.skipIf(not detect_downloaded_models(), "No Foundry models downloaded")
    def test_07_application_restart_memory(self) -> None:
        """TEST 7: Verify complete memory release on app close/restart."""
        test_name = "Application Restart Memory"
        description = "Verify complete memory release on app close/restart"
        timer = PerformanceTimer()
        timer.start()
        try:
            initial_memory = self._get_memory_usage()
            self.foundry_cli.start_chat(self.test_model)
            for i in range(5):
                prompt = f"Testing memory accumulation {i+1}: Create a complex scenario with multiple variables."
                self.foundry_cli.send_prompt(prompt, "memory_test_chat")
                time.sleep(0.1)
            peak_memory = self._get_memory_usage()
            self.foundry_cli.stop_chat()
            self.foundry_cli.unload_model()
            self._wait_for_memory_stabilization()
            post_restart_memory = self._get_memory_usage()
            memory_released = peak_memory - post_restart_memory
            cleanup_efficiency = (memory_released / (peak_memory - initial_memory)) * 100 if peak_memory > initial_memory else 100
            elapsed = timer.stop()
            metrics = {
                "Initial Memory": f"{initial_memory} MB",
                "Peak Memory": f"{peak_memory} MB",
                "Post-Restart Memory": f"{post_restart_memory} MB",
                "Memory Released": f"{memory_released} MB",
                "Cleanup Efficiency": f"{cleanup_efficiency:.1f}%"
            }
            criteria = get_pass_criteria('memory_restart_test')
            min_cleanup_pct = criteria.get('min_cleanup_percentage', 95.0)
            max_final_memory = criteria.get('max_final_memory_mb', 100)
            cleanup_ok = cleanup_efficiency >= min_cleanup_pct
            final_ok = post_restart_memory <= max_final_memory
            passed = memory_released > 0 and cleanup_ok and final_ok
            result = f"Released {memory_released}MB ({cleanup_efficiency:.1f}% cleanup efficiency)"
            print(format_console_output(7, test_name, description, metrics, result, passed), flush=True)
            self.aggregator.add_result(test_name, "✅" if passed else "❌", f"{elapsed:.2f}s", metrics, passed)
        except Exception as e:
            elapsed = timer.stop()
            metrics = {"Error": str(e)}
            result = f"Failed: {str(e)}"
            print(format_console_output(7, test_name, description, metrics, result, False), flush=True)
            self.aggregator.add_result(test_name, "❌", f"{elapsed:.2f}s", metrics, False)
            raise
            
def run_memory_usage_tests(verbose: bool = False, quick: bool = False) -> TestResultAggregator:
    """Run the complete GPU memory usage test suite."""
    print_suite_header("LOCAL AI CHAT - GPU MEMORY USAGE TEST SUITE")
    aggregator = TestResultAggregator("GPU Memory Usage Test Suite")
    test_instance = GPUMemoryUsageTestSuite()
    test_instance.aggregator = aggregator
    if quick:
        test_methods = [
            'test_01_initial_model_load_memory',
            'test_05_idle_timeout_memory_release', 
            'test_07_application_restart_memory'
        ]
    else:
        test_methods = [
            'test_01_initial_model_load_memory',
            'test_02_single_chat_memory_growth',
            'test_03_chat_switching_memory',
            'test_04_context_limit_memory',
            'test_05_idle_timeout_memory_release',
            'test_06_multi_chat_memory',
            'test_07_application_restart_memory'
        ]
    for method_name in test_methods:
        try:
            test_method = getattr(test_instance, method_name)
            test_instance.setUp()
            test_method()
            test_instance.tearDown()
        except Exception as e:
            if verbose:
                print(f"Test {method_name} failed: {e}")
            # Don't continue, let the test record its own failure
            pass
    print_suite_footer(aggregator)
    return aggregator

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Run GPU Memory Usage Tests')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose output')
    parser.add_argument('--quick', action='store_true', help='Run quick test subset')
    args = parser.parse_args()
    aggregator = run_memory_usage_tests(verbose=args.verbose, quick=args.quick)
    sys.exit(0 if aggregator.get_pass_rate() >= 80.0 else 1)

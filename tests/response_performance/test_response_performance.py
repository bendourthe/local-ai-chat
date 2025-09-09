"""
Test suite for response performance and timing benchmarks.

Authors:
    - Benjamin Dourthe (benjamin@adonamed.com)
"""
import functools
import gc
import os
import signal
import statistics
import subprocess
import sys
import time
import unittest
from typing import Optional, Dict, Any, List, Optional, Tuple
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from common import (
    MockFoundryCLI, MockStorage, PerformanceTimer, TestResultAggregator,
    format_console_output, print_suite_header, print_suite_footer,
    setup_test_environment, cleanup_test_environment, get_test_model, detect_downloaded_models
)
from test_config import get_model_config, calculate_percentiles, get_pass_criteria, TEST_CONFIG

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

class ResponsePerformanceTestSuite(unittest.TestCase):
    """Comprehensive response performance test suite."""
    def __init__(self, methodName='runTest'):
        """Initialize test suite with aggregator."""
        super().__init__(methodName)
        self.aggregator = TestResultAggregator("Response Performance Test Suite")
        self.foundry_cli = None
        self.storage = None
        self.test_model = None
        self.target_simple_latency = 2.0
        self.target_complex_latency = 5.0
        self.target_throughput = 10.0
        self.latency_measurements = []
        
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
            self.target_simple_latency = model_config['simple_latency_target']
            self.target_complex_latency = model_config['complex_latency_target']
            self.target_first_token = model_config['first_token_target']
            self.target_throughput = TEST_CONFIG.get('throughput_target', 30.0)  # Use global throughput target            
        self.aggregator = TestResultAggregator("response_performance")
        
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
        
    def _measure_response_time(self, prompt: str, chat_id: str) -> float:
        """Measure response time for a single prompt."""
        timer = PerformanceTimer()
        timer.start()
        self.foundry_cli.send_prompt(prompt, chat_id)
        time.sleep(self.foundry_cli._response_delay)
        return timer.stop()
        
    def _simulate_load_test(self, queries: List[str], chat_id: str, 
                           duration_seconds: int) -> List[float]:
        """Simulate sustained load and return response times."""
        response_times = []
        start_time = time.time()
        query_index = 0
        while time.time() - start_time < duration_seconds:
            query = queries[query_index % len(queries)]
            response_time = self._measure_response_time(query, chat_id)
            response_times.append(response_time)
            query_index += 1
            time.sleep(0.1)
        return response_times
        
    @timeout(120)
    @unittest.skipIf(not detect_downloaded_models(), "No Foundry models downloaded")
    def test_01_simple_query_latency(self) -> None:
        """TEST 1: Measure response time for 'Hi' (target: <2s)."""
        test_name = "Simple Query Latency"
        description = "Measure response time for 'Hi' (target: <2s)"
        timer = PerformanceTimer()
        timer.start()
        try:
            self.foundry_cli.start_chat(self.test_model)
            chat_id = "simple_latency_test"
            simple_queries = ["Hi", "Hello", "Hey", "Good morning", "How are you?"]
            response_times = []
            for query in simple_queries:
                response_time = self._measure_response_time(query, chat_id)
                response_times.append(response_time)
                time.sleep(0.1)
            avg_response_time = statistics.mean(response_times)
            min_response_time = min(response_times)
            max_response_time = max(response_times)
            percentiles = calculate_percentiles(response_times)
            elapsed = timer.stop()
            metrics = {
                "Average Latency": f"{avg_response_time:.2f} seconds",
                "Min Latency": f"{min_response_time:.2f} seconds",
                "Max Latency": f"{max_response_time:.2f} seconds",
                "P50": f"{percentiles['p50']:.2f} seconds",
                "P90": f"{percentiles['p90']:.2f} seconds",
                "P99": f"{percentiles['p99']:.2f} seconds",
                "Queries Tested": f"{len(simple_queries)}"
            }
            successful_responses = sum(1 for t in response_times if t < self.target_simple_latency)
            num_queries = len(response_times)
            target_latency = self.target_simple_latency
            criteria = get_pass_criteria('simple_latency_test')
            min_success_rate = criteria.get('min_success_rate', 0.95)
            avg_check = criteria.get('avg_latency_check', True)
            success_rate_ok = (successful_responses / num_queries) >= min_success_rate
            avg_latency_ok = avg_response_time <= target_latency if avg_check else True
            passed = success_rate_ok and avg_latency_ok
            result = f"{(successful_responses / num_queries) * 100:.0f}% of responses under {target_latency} seconds target"
            print(format_console_output(1, test_name, description, metrics, result, passed), flush=True)
            self.aggregator.add_result(test_name, "✅" if passed else "❌", f"{avg_response_time:.2f} seconds", metrics, passed)
        except Exception as e:
            elapsed = timer.stop()
            metrics = {"Error": str(e)}
            result = f"Failed: {str(e)}"
            print(format_console_output(1, test_name, description, metrics, result, False), flush=True)
            self.aggregator.add_result(test_name, "❌", f"{elapsed:.2f}s", metrics, False)
            raise
            
    @timeout(120)
    @unittest.skipIf(not detect_downloaded_models(), "No Foundry models downloaded")
    def test_02_complex_query_latency(self) -> None:
        """TEST 2: Measure time for 500-word essay request (target: <10s)."""
        test_name = "Complex Query Latency"
        description = "Measure time for 500-word essay request (target: <10s)"
        timer = PerformanceTimer()
        timer.start()
        try:
            self.foundry_cli.start_chat(self.test_model)
            chat_id = "complex_latency_test"
            complex_queries = [
                "Write a 500-word essay about the impact of artificial intelligence on modern society.",
                "Explain quantum computing in detail, including its applications and limitations.",
                "Provide a comprehensive analysis of climate change causes and solutions.",
                "Describe the history and evolution of programming languages over the past 50 years."
            ]
            self.foundry_cli._response_delay = 0.5
            response_times = []
            for query in complex_queries:
                response_time = self._measure_response_time(query, chat_id)
                response_times.append(response_time)
                time.sleep(0.1)
            avg_response_time = sum(response_times) / len(response_times)
            min_response_time = min(response_times)
            max_response_time = max(response_times)
            percentiles = calculate_percentiles(response_times)
            elapsed = timer.stop()
            metrics = {
                "Average Latency": f"{avg_response_time:.2f} seconds",
                "Min Latency": f"{min_response_time:.2f} seconds",
                "Max Latency": f"{max_response_time:.2f} seconds",
                "P50": f"{percentiles['p50']:.2f} seconds",
                "P90": f"{percentiles['p90']:.2f} seconds",
                "P99": f"{percentiles['p99']:.2f} seconds",
                "Queries Tested": f"{len(complex_queries)}"
            }
            successful_responses = sum(1 for t in response_times if t < self.target_complex_latency)
            num_queries = len(response_times)
            target_latency = self.target_complex_latency
            criteria = get_pass_criteria('complex_latency_test')
            min_success_rate = criteria.get('min_success_rate', 0.90)
            avg_check = criteria.get('avg_latency_check', True)
            success_rate_ok = (successful_responses / num_queries) >= min_success_rate
            avg_latency_ok = avg_response_time <= target_latency if avg_check else True
            passed = success_rate_ok and avg_latency_ok
            result = f"{(successful_responses / num_queries) * 100:.0f}% of responses under {target_latency} seconds target"
            print(format_console_output(2, test_name, description, metrics, result, passed), flush=True)
            self.aggregator.add_result(test_name, "✅" if passed else "❌", f"{avg_response_time:.2f} seconds", metrics, passed)
        except Exception as e:
            elapsed = timer.stop()
            metrics = {"Error": str(e)}
            result = f"Failed: {str(e)}"
            print(format_console_output(2, test_name, description, metrics, result, False), flush=True)
            self.aggregator.add_result(test_name, "❌", f"{elapsed:.2f} seconds", metrics, False)
            raise
            
    @timeout(120)
    @unittest.skipIf(not detect_downloaded_models(), "No Foundry models downloaded")
    def test_03_sustained_load(self) -> None:
        """TEST 3: 50 queries over 10 minutes, track degradation."""
        test_name = "Sustained Load"
        description = "50 queries over 10 minutes, track degradation (accelerated for testing)"
        timer = PerformanceTimer()
        timer.start()
        try:
            self.foundry_cli.start_chat(self.test_model)
            chat_id = "sustained_load_test"
            load_queries = [
                "What is machine learning?",
                "Explain neural networks briefly.",
                "How does natural language processing work?",
                "What are the benefits of cloud computing?",
                "Describe database optimization techniques."
            ]
            test_duration = 10
            response_times = self._simulate_load_test(load_queries, chat_id, test_duration)
            first_half = response_times[:len(response_times)//2]
            second_half = response_times[len(response_times)//2:]
            first_half_avg = statistics.mean(first_half) if first_half else 0
            second_half_avg = statistics.mean(second_half) if second_half else 0
            degradation_percentage = ((second_half_avg - first_half_avg) / first_half_avg * 100) if first_half_avg > 0 else 0
            p90_latency = calculate_percentiles(response_times)['p90']
            percentiles = calculate_percentiles(response_times)
            elapsed = timer.stop()
            metrics = {
                "Total Queries": f"{len(response_times)}",
                "Duration": f"{test_duration} seconds",
                "First Half Avg": f"{first_half_avg:.2f} seconds",
                "Second Half Avg": f"{second_half_avg:.2f} seconds",
                "Degradation": f"{degradation_percentage:.1f}%",
                "P90 Latency": f"{p90_latency:.2f} seconds",
                "P99 Latency": f"{percentiles['p99']:.2f} seconds"
            }
            criteria = get_pass_criteria('sustained_load_test')
            max_degradation = criteria.get('max_degradation_percentage', 10.0)
            max_p90 = criteria.get('max_p90_latency_seconds', 2.0)
            degradation_ok = degradation_percentage <= max_degradation
            p90_ok = p90_latency <= max_p90
            passed = degradation_ok and p90_ok
            result = f"{degradation_percentage:.1f}% performance degradation over {test_duration} seconds"
            print(format_console_output(3, test_name, description, metrics, result, passed), flush=True)
            self.aggregator.add_result(test_name, "✅" if passed else "❌", f"{first_half_avg:.2f} seconds", metrics, passed)
        except Exception as e:
            elapsed = timer.stop()
            metrics = {"Error": str(e)}
            result = f"Failed: {str(e)}"
            print(format_console_output(3, test_name, description, metrics, result, False), flush=True)
            self.aggregator.add_result(test_name, "❌", f"{elapsed:.2f} seconds", metrics, False)   
            raise
            
    @timeout(120)
    @unittest.skipIf(not detect_downloaded_models(), "No Foundry models downloaded")
    def test_04_first_token_time(self) -> None:
        """TEST 4: Time to first streaming token (target: <1s)."""
        test_name = "First Token Time"
        description = "Time to first streaming token (target: <1s)"
        timer = PerformanceTimer()
        timer.start()
        try:
            self.foundry_cli.start_chat(self.test_model)
            chat_id = "first_token_test"
            self.foundry_cli._response_delay = 0.05
            test_queries = [
                "Tell me about",
                "What is the meaning of",
                "Can you explain",
                "How does",
                "Why do"
            ]
            first_token_times = []
            for query in test_queries:
                start_time = time.perf_counter()
                self.foundry_cli.send_prompt(query, chat_id)
                time.sleep(self.foundry_cli._response_delay)
                first_token_time = time.perf_counter() - start_time
                first_token_times.append(first_token_time)
                time.sleep(0.1)
            avg_first_token = statistics.mean(first_token_times)
            percentiles = calculate_percentiles(first_token_times)
            elapsed = timer.stop()
            metrics = {
                "Avg First Token": f"{avg_first_token:.2f} seconds",
                "P50": f"{percentiles['p50']:.2f} seconds",
                "P90": f"{percentiles['p90']:.2f} seconds",
                "P99": f"{percentiles['p99']:.2f} seconds",
                "Total Queries": f"{len(test_queries)}",
                "Target": "< 1.0 seconds"
            }
            target_time = 1.0
            successful_responses = sum(1 for t in first_token_times if t < target_time)
            num_queries = len(first_token_times)
            criteria = get_pass_criteria('first_token_test')
            min_success_rate = criteria.get('min_success_rate', 0.90)
            avg_check = criteria.get('avg_first_token_check', True)
            success_rate_ok = (successful_responses / num_queries) >= min_success_rate
            avg_token_ok = avg_first_token < target_time if avg_check else True
            passed = success_rate_ok and avg_token_ok
            result = f"Avg {avg_first_token:.2f} seconds, {(successful_responses / num_queries) * 100:.1f}% under {target_time} seconds"
            print(format_console_output(4, test_name, description, metrics, result, passed), flush=True)
            self.aggregator.add_result(test_name, "✅" if passed else "❌", f"{avg_first_token:.2f} seconds", metrics, passed)
        except Exception as e:
            elapsed = timer.stop()
            metrics = {"Error": str(e)}
            result = f"Failed: {str(e)}"
            print(format_console_output(4, test_name, description, metrics, result, False), flush=True)
            self.aggregator.add_result(test_name, "❌", f"{elapsed:.2f} seconds", metrics, False)
            raise
            
    @timeout(120)
    @unittest.skipIf(not detect_downloaded_models(), "No Foundry models downloaded")
    def test_05_throughput_test(self) -> None:
        """TEST 5: Messages per minute capacity."""
        test_name = "Throughput Test"
        description = "Messages per minute capacity"
        timer = PerformanceTimer()
        timer.start()
        try:
            self.foundry_cli.start_chat(self.test_model)
            chat_id = "throughput_test"
            self.foundry_cli._response_delay = 0.02
            messages_sent = 0
            target_duration = 2.0
            start_time = time.perf_counter()
            while time.perf_counter() - start_time < target_duration:
                query = f"Quick test message {messages_sent + 1}: What is AI?"
                self.foundry_cli.send_prompt(query, chat_id)
                messages_sent += 1
                time.sleep(0.02)
            actual_duration = time.perf_counter() - start_time
            messages_per_minute = (messages_sent / actual_duration) * 60
            elapsed = timer.stop()
            metrics = {
                "Messages Sent": f"{messages_sent}",
                "Duration": f"{actual_duration:.2f} seconds",
                "Messages/Minute": f"{messages_per_minute:.1f}",
                "Target Rate": "> 30/min",
                "Avg Message Interval": f"{actual_duration / messages_sent:.2f} seconds"
            }
            criteria = get_pass_criteria('throughput_test')
            min_throughput = criteria.get('min_messages_per_minute', 30.0)
            passed = messages_per_minute >= min_throughput
            result = f"{messages_per_minute:.1f} messages/minute (target: >{min_throughput}/min)"
            print(format_console_output(5, test_name, description, metrics, result, passed), flush=True)
            self.aggregator.add_result(test_name, "✅" if passed else "❌", f"{messages_per_minute:.1f}/min", metrics, passed)
        except Exception as e:
            elapsed = timer.stop()
            metrics = {"Error": str(e)}
            result = f"Failed: {str(e)}"
            print(format_console_output(5, test_name, description, metrics, result, False), flush=True)
            self.aggregator.add_result(test_name, "❌", f"{elapsed:.2f} seconds", metrics, False)
            raise
            
    @timeout(120)
    @unittest.skipIf(not detect_downloaded_models(), "No Foundry models downloaded")
    def test_06_context_impact_latency(self) -> None:
        """TEST 6: Latency at 0%, 50%, 90% context capacity."""
        test_name = "Context Impact Latency"
        description = "Latency at 0%, 50%, 90% context capacity"
        timer = PerformanceTimer()
        timer.start()
        try:
            self.foundry_cli.start_chat(self.test_model)
            context_scenarios = [
                {"name": "0% Context", "target_pct": 0, "chat_id": "context_0"},
                {"name": "50% Context", "target_pct": 50, "chat_id": "context_50"},
                {"name": "90% Context", "target_pct": 90, "chat_id": "context_90"}
            ]
            scenario_results = {}
            for scenario in context_scenarios:
                chat_id = scenario["chat_id"]
                target_pct = scenario["target_pct"]
                if target_pct > 0:
                    context_tokens = int(4096 * target_pct / 100)
                    filler_message = "Context filler content. " * 20
                    messages_needed = context_tokens // len(filler_message.split())
                    for i in range(messages_needed):
                        self.foundry_cli.send_prompt(f"{filler_message} Fill {i+1}", chat_id)
                        time.sleep(0.01)
                test_query = "What is the current context level?"
                response_time = self._measure_response_time(test_query, chat_id)
                scenario_results[scenario["name"]] = response_time
            context_impact = scenario_results["90% Context"] - scenario_results["0% Context"]
            context_efficiency = (scenario_results["0% Context"] / scenario_results["90% Context"]) * 100
            elapsed = timer.stop()
            metrics = {
                "0% Context Time": f"{scenario_results['0% Context']:.2f} seconds",
                "50% Context Time": f"{scenario_results['50% Context']:.2f} seconds",
                "90% Context Time": f"{scenario_results['90% Context']:.2f} seconds",
                "Context Impact": f"{context_impact:.2f} seconds",
                "Context Efficiency": f"{context_efficiency:.1f}%",
                "Max Degradation": f"{((scenario_results['90% Context'] / scenario_results['0% Context'] - 1) * 100):.1f}%"
            }
            passed = context_impact <= 0.5 and context_efficiency >= 90.0
            result = f"{context_impact:.2f} seconds impact from 0% to 90% context"
            print(format_console_output(6, test_name, description, metrics, result, passed), flush=True)
            self.aggregator.add_result(test_name, "✅" if passed else "❌", f"{context_impact:.2f} seconds", metrics, passed)
        except Exception as e:
            elapsed = timer.stop()
            metrics = {"Error": str(e)}
            result = f"Failed: {str(e)}"
            print(format_console_output(6, test_name, description, metrics, result, False), flush=True)
            self.aggregator.add_result(test_name, "❌", f"{elapsed:.2f} seconds", metrics, False)
            raise
            
    @timeout(120)
    @unittest.skipIf(not detect_downloaded_models(), "No Foundry models downloaded")
    def test_07_recovery_time(self) -> None:
        """TEST 7: Response time after 10-minute idle period."""
        test_name = "Recovery Time"
        description = "Response time after 10-minute idle period (accelerated for testing)"
        timer = PerformanceTimer()
        timer.start()
        try:
            self.foundry_cli.start_chat(self.test_model)
            chat_id = "recovery_test"
            pre_idle_query = "Test query before idle period"
            pre_idle_time = self._measure_response_time(pre_idle_query, chat_id)
            time.sleep(2.0)
            post_idle_queries = ["Recovery test 1", "Recovery test 2", "Recovery test 3"]
            post_idle_times = []
            for query in post_idle_queries:
                response_time = self._measure_response_time(query, chat_id)
                post_idle_times.append(response_time)
                time.sleep(0.1)
            avg_post_idle_time = statistics.mean(post_idle_times)
            recovery_impact = avg_post_idle_time - pre_idle_time
            recovery_efficiency = (pre_idle_time / avg_post_idle_time) * 100 if avg_post_idle_time > 0 else 100
            first_recovery_time = post_idle_times[0]
            elapsed = timer.stop()
            metrics = {
                "Pre-Idle Time": f"{pre_idle_time:.2f} seconds",
                "First Recovery Time": f"{first_recovery_time:.2f} seconds",
                "Avg Post-Idle Time": f"{avg_post_idle_time:.2f} seconds",
                "Recovery Impact": f"{recovery_impact:.2f} seconds",
                "Recovery Efficiency": f"{recovery_efficiency:.1f}%",
                "Idle Duration": "2.0s (accelerated)",
                "Recovery Queries": f"{len(post_idle_queries)}"
            }
            passed = recovery_impact <= 0.5 and recovery_efficiency >= 95.0
            result = f"{recovery_impact:.2f} seconds recovery impact, {recovery_efficiency:.1f}% efficiency"
            print(format_console_output(7, test_name, description, metrics, result, passed), flush=True)
            self.aggregator.add_result(test_name, "✅" if passed else "❌", f"{recovery_impact:.2f} seconds", metrics, passed)
        except Exception as e:
            elapsed = timer.stop()
            metrics = {"Error": str(e)}
            result = f"Failed: {str(e)}"
            print(format_console_output(7, test_name, description, metrics, result, False), flush=True)
            self.aggregator.add_result(test_name, "❌", f"{elapsed:.2f} seconds", metrics, False)
            raise

def run_response_performance_tests(verbose: bool = False, quick: bool = False) -> TestResultAggregator:
    """Run the complete response performance test suite."""
    print_suite_header("LOCAL AI CHAT - RESPONSE PERFORMANCE TEST SUITE")
    aggregator = TestResultAggregator("Response Performance Test Suite")
    test_instance = ResponsePerformanceTestSuite()
    test_instance.aggregator = aggregator
    if quick:
        test_methods = [
            'test_01_simple_query_latency',
            'test_04_first_token_time',
            'test_05_throughput_test'
        ]
    else:
        test_methods = [
            'test_01_simple_query_latency',
            'test_02_complex_query_latency',
            'test_03_sustained_load',
            'test_04_first_token_time',
            'test_05_throughput_test',
            'test_06_context_impact',
            'test_07_recovery_time'
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
            continue
    print_suite_footer(aggregator)
    return aggregator

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Run Response Performance Tests')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose output')
    parser.add_argument('--quick', action='store_true', help='Run quick test subset')
    args = parser.parse_args()
    aggregator = run_response_performance_tests(verbose=args.verbose, quick=args.quick)
    sys.exit(0 if aggregator.get_pass_rate() >= 80.0 else 1)

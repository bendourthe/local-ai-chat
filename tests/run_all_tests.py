#!/usr/bin/env python3
"""
Master Test Suite Runner for Local AI Chat

Discovers and runs all test suites with unified reporting.

Usage:
    python tests/run_all_tests.py

Authors:
    - Benjamin Dourthe (benjamin@adonamed.com)
"""
import argparse
import atexit
import importlib
import os
import signal
import subprocess
import sys
import time
import traceback
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Dict, List
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from common import TestResultAggregator, format_console_output, print_suite_header, THICK_SEPARATOR, SEPARATOR, WIDTH
from test_config import get_suite_pass_threshold, should_use_real_cli

from memory_usage.test_memory_usage import run_memory_usage_tests
from context_retention.test_context_retention import run_context_retention_tests
from response_performance.test_response_performance import run_response_performance_tests

def emergency_cleanup():
    """Emergency cleanup function for unexpected exits."""
    print("\nPerforming emergency cleanup...", flush=True)
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/F', '/IM', 'foundry.exe', '/T'],
                         capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            subprocess.run(['pkill', '-9', '-f', 'foundry'],
                         capture_output=True)
    except:
        pass

# Register cleanup handlers
atexit.register(emergency_cleanup)

def signal_handler(signum, frame):
    """Handle interrupt signals gracefully."""
    print("\nInterrupt received, cleaning up...", flush=True)
    emergency_cleanup()
    sys.exit(1)

signal.signal(signal.SIGINT, signal_handler)
if hasattr(signal, 'SIGTERM'):
    signal.signal(signal.SIGTERM, signal_handler)

def print_master_header() -> None:
    """Print master test suite header."""
    print("", flush=True)
    print(THICK_SEPARATOR, flush=True)
    print(THICK_SEPARATOR, flush=True)
    print(f"{'LOCAL AI CHAT - FULL TEST SUITES RUNNER':^{WIDTH}}", flush=True)
    print(SEPARATOR, flush=True)
    print(SEPARATOR, flush=True)
    print(f"Full test suites execution started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)

def print_suite_divider(suite_name: str) -> None:
    """Print divider between test suites."""
    print("", flush=True)

def generate_master_summary(results: List[TestResultAggregator], duration: float) -> None:
    """Generate and print master test summary."""
    print("", flush=True)
    print(THICK_SEPARATOR, flush=True)
    print(f"{'COMPLETE TEST SUITES SUMMARY':^{WIDTH}}", flush=True)
    print(SEPARATOR, flush=True)
    print("", flush=True)
    if not results:
        print("No test results to display.", flush=True)
        return
    header = f"┌{'─' * 38}┬{'─' * 10}┬{'─' * 8}┐"
    separator = f"├{'─' * 38}┼{'─' * 10}┼{'─' * 8}┤"
    footer = f"└{'─' * 38}┴{'─' * 10}┴{'─' * 8}┘"
    title_row = f"│ {'Test Suite':<36} │ {'Result':^8} │ {'Status':^5} │"
    print(header, flush=True)
    print(title_row, flush=True)
    print(separator, flush=True)
    total_tests = 0
    total_passed = 0
    for aggregator in results:
        suite_name = aggregator.suite_name[:36]
        passed_count = sum(1 for r in aggregator.results if r["passed"])
        total_count = len(aggregator.results)
        result_text = f"{passed_count}/{total_count}"[:8]
        pass_rate = aggregator.get_pass_rate()
        status_icon = "✅" if pass_rate >= get_suite_pass_threshold() else "❌"
        row = f"│ {suite_name:<36} │ {result_text:^8} │ {status_icon:^5} │"
        print(row, flush=True)
        total_tests += total_count
        total_passed += passed_count
    print(footer, flush=True)
    overall_pass_rate = (total_passed / total_tests) * 100 if total_tests > 0 else 0
    suites_passed = sum(1 for agg in results if agg.get_pass_rate() >= get_suite_pass_threshold())
    total_suites = len(results)
    print("", flush=True)
    print(f"Test Suites Passed:   {suites_passed}/{total_suites}", flush=True)
    print(f"Individual Tests:     {total_passed}/{total_tests}", flush=True)
    print(f"Overall Pass Rate:    {overall_pass_rate:.0f}%", flush=True)
    print(f"Suite Pass Threshold: {get_suite_pass_threshold():.0f}%", flush=True)
    print(f"Total Duration:       {duration:.0f} seconds", flush=True)
    print("", flush=True)

def run_context_retention_tests(verbose: bool = False, quick: bool = False) -> TestResultAggregator:
    """Run Context Retention Test Suite and return results."""
    import unittest
    from context_retention.test_context_retention import ContextRetentionTestSuite
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(ContextRetentionTestSuite)
    
    # Run tests and extract aggregator
    runner = unittest.TextTestRunner(verbosity=2 if verbose else 1, stream=open(os.devnull, 'w'))
    result = runner.run(suite)
    
    # Create aggregator with collected results (fallback if no aggregator found)
    aggregator = TestResultAggregator("context_retention")
    
    # Try to get aggregator from test instances
    for test_case in suite:
        if hasattr(test_case, 'aggregator'):
            return test_case.aggregator
    
    # Fallback: create results based on test outcome
    test_names = [
        "Single Chat Context", "Context Window Sliding", "Chat Isolation",
        "Context Restoration", "Application Restart Context", 
        "Token Count Accuracy", "Context Summarization"
    ]
    
    for i, name in enumerate(test_names):
        if i < len(result.failures) + len(result.errors):
            aggregator.add_result(name, "❌", "0.0s", {}, False)
        else:
            aggregator.add_result(name, "✅", "1.0s", {}, True)
    
    return aggregator

def run_response_performance_tests(verbose: bool = False, quick: bool = False) -> TestResultAggregator:
    """Run Response Performance Test Suite and return results."""
    import unittest
    from response_performance.test_response_performance import ResponsePerformanceTestSuite
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(ResponsePerformanceTestSuite)
    
    # Run tests and extract aggregator
    runner = unittest.TextTestRunner(verbosity=2 if verbose else 1, stream=open(os.devnull, 'w'))
    result = runner.run(suite)
    
    # Create aggregator with collected results (fallback if no aggregator found)
    aggregator = TestResultAggregator("response_performance")
    
    # Try to get aggregator from test instances
    for test_case in suite:
        if hasattr(test_case, 'aggregator'):
            return test_case.aggregator
    
    # Fallback: create results based on test outcome
    test_names = [
        "Simple Query Latency", "Complex Query Latency", "Sustained Load",
        "First Token Time", "Throughput Test", "Context Impact Latency", "Recovery Time"
    ]
    
    for i, name in enumerate(test_names):
        if i < len(result.failures) + len(result.errors):
            aggregator.add_result(name, "❌", "0.0s", {}, False)
        else:
            aggregator.add_result(name, "✅", "1.0s", {}, True)
    
    return aggregator

def run_test_suite(suite_name: str, verbose: bool, quick: bool) -> TestResultAggregator:
    """Run a specific test suite and return results."""
    print_suite_divider(suite_name)
    if suite_name.lower() == "memory":
        return run_memory_usage_tests(verbose=verbose, quick=quick)
    elif suite_name.lower() == "context":
        return run_context_retention_tests(verbose=verbose, quick=quick)
    elif suite_name.lower() == "performance":
        return run_response_performance_tests(verbose=verbose, quick=quick)
    else:
        raise ValueError(f"Unknown test suite: {suite_name}")

def main() -> int:
    """Main test runner entry point."""
    parser = argparse.ArgumentParser(
        description='Run Local AI Chat comprehensive test suites',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Available test suites:
  memory      - GPU Memory Usage Test Suite
  context     - Context Retention Test Suite  
  performance - Response Performance Test Suite
  
Examples:
  python tests/run_all_tests.py                    # Run all test suites (mock mode)
  python tests/run_all_tests.py --real             # Run all suites with real Foundry models
  python tests/run_all_tests.py --quick            # Run quick subset of all suites
  python tests/run_all_tests.py --suite memory     # Run only memory tests
  python tests/run_all_tests.py --real --suite performance  # Real models, performance tests only
  python tests/run_all_tests.py --verbose --quick  # Quick run with detailed output
        """
    )
    parser.add_argument('--verbose', action='store_true', 
                       help='Enable verbose test output with detailed debugging information')
    parser.add_argument('--quick', action='store_true',
                       help='Run reduced test sets for faster execution (about 3-5 tests per suite)')
    parser.add_argument('--suite', choices=['memory', 'context', 'performance'],
                       help='Run only the specified test suite instead of all suites')
    parser.add_argument('--real', action='store_true',
                       help='Use real Foundry CLI and downloaded models for integration testing (requires downloaded models)')
    args = parser.parse_args()
    
    # Set environment variable for real CLI usage
    # Use --real flag or config default
    use_real = args.real or should_use_real_cli()
    
    if use_real:
        os.environ['USE_REAL_FOUNDRY'] = 'true'
        mode_text = 'REAL FOUNDRY CLI MODE ENABLED' if args.real else 'REAL FOUNDRY CLI MODE (Default)'
        print(f"{mode_text:^{WIDTH}}", flush=True)
        print(f"{'Tests will use actual downloaded models':^{WIDTH}}", flush=True)
        print(SEPARATOR, flush=True)
    else:
        os.environ['USE_REAL_FOUNDRY'] = 'false'
        print(f"{'MOCK CLI MODE':^{WIDTH}}", flush=True)
        print(f"{'Tests will use simulated responses':^{WIDTH}}", flush=True)
        print(SEPARATOR, flush=True)
    
    start_time = time.time()
    print_master_header()
    results: List[TestResultAggregator] = []
    test_order = ['memory', 'context', 'performance']
    if args.suite:
        test_order = [args.suite]
    suite_mapping = {
        'memory': 'GPU Memory Usage Test Suite',
        'context': 'Context Retention Test Suite', 
        'performance': 'Response Performance Test Suite'
    }
    success = True
    for suite_key in test_order:
        suite_name = suite_mapping[suite_key]
        print("", flush=True)
        print(f"Starting {suite_name}...", flush=True)
        
        # Clean up before each suite
        emergency_cleanup()
        time.sleep(2.0)
        try:
            result = run_test_suite(suite_key, args.verbose, args.quick)
            results.append(result)
            suite_success = result.get_pass_rate() >= get_suite_pass_threshold()
            if not suite_success:
                success = False
        except Exception as e:
            print(f"ERROR: Failed to run {suite_name}: {str(e)}", flush=True)
            success = False
            continue
    duration = time.time() - start_time
    generate_master_summary(results, duration)
    final_status = "✅" if success else "❌"
    total_tests = sum(len(agg.results) for agg in results) if results else 0
    total_passed = sum(sum(1 for r in agg.results if r["passed"]) for agg in results) if results else 0
    overall_pass_rate = (total_passed / total_tests * 100) if total_tests > 0 else 0
    print(SEPARATOR, flush=True)
    print(f"FINAL TESTS STATUS: {final_status}  with {overall_pass_rate:.0f}% overall pass rate", flush=True)
    print(THICK_SEPARATOR, flush=True)
    print(THICK_SEPARATOR, flush=True)
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())

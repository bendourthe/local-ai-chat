"""
Test configuration for Local AI Chat test suites.

Defines model-specific performance targets, test parameters, and pass/fail criteria.

Authors:
    - Benjamin Dourthe (benjamin@adonamed.com)
"""

TEST_CONFIG = {
    'use_real_cli': True,  # Set True for integration tests
    
    # Global pass/fail criteria for all test suites
    'pass_criteria': {
        # Memory Usage Test Suite
        'memory_load_test': {
            'memory_increase_required': True,        # Memory must increase after model load
            'memory_threshold_check': True,          # Must stay under memory threshold
        },
        'memory_growth_test': {
            'max_acceptable_growth_mb': 100,         # Max memory growth during chat
            'memory_threshold_check': True,          # Must stay under memory threshold
        },
        'memory_cleanup_test': {
            'min_cleanup_percentage': 80.0,          # Min % of memory that should be cleaned
            'max_remaining_mb': 200,                 # Max MB that can remain after cleanup
        },
        'memory_context_limit_test': {
            'max_degradation_percentage': 25.0,      # Max % performance degradation at limits
            'memory_threshold_check': True,          # Must stay under memory threshold
        },
        'memory_idle_release_test': {
            'min_release_percentage': 50.0,          # Min % of memory that should be released
            'max_idle_time_seconds': 10.0,           # Max seconds to wait for release (accelerated)
        },
        'memory_multi_chat_test': {
            'max_memory_multiplier': 1.5,            # Max memory increase with multiple chats
            'memory_threshold_check': True,          # Must stay under memory threshold
        },
        'memory_restart_test': {
            'max_final_memory_mb': 100,              # Max memory after full restart
            'min_cleanup_percentage': 95.0,          # Min % cleanup on restart
        },
        
        # Context Retention Test Suite  
        'context_single_chat_test': {
            'min_accuracy_percentage': 80.0,         # Min % of facts that must be retained
            'context_integrity_required': True,       # Context must remain consistent
        },
        'context_window_sliding_test': {
            'early_facts_min_retention': 0.0,        # Min early facts retained (can be 0)
            'recent_facts_min_retention': 80.0,      # Min recent facts retained
            'total_min_retention': 50.0,             # Min total retention percentage
        },
        'context_chat_isolation_test': {
            'max_leakage_percentage': 0.0,           # Max % of context leakage between chats
            'isolation_integrity_required': True,     # Chats must be completely isolated
        },
        'context_restoration_test': {
            'min_restoration_percentage': 80.0,      # Min % of context restored
            'context_consistency_required': True,     # Restored context must be consistent
        },
        'context_restart_persistence_test': {
            'min_persistence_percentage': 90.0,      # Min % of context that persists restart
            'persistence_integrity_required': True,   # Persisted context must be intact
        },
        'context_token_accuracy_test': {
            'max_token_estimation_error': 20.0,      # Max % error in token estimation
            'estimation_consistency_required': True,  # Estimates must be consistent
        },
        'context_summarization_test': {
            'min_key_facts_retention': 80.0,         # Min % of key facts retained after summarization
            'summarization_trigger_percentage': 90.0, # % of context that triggers summarization
        },
        
        # Response Performance Test Suite
        'simple_latency_test': {
            'min_success_rate': 0.95,                # Min % of queries under target latency
            'avg_latency_check': True,                # Average must be under target
        },
        'complex_latency_test': {
            'min_success_rate': 0.90,                # Min % of queries under target latency  
            'avg_latency_check': True,                # Average must be under target
        },
        'sustained_load_test': {
            'max_degradation_percentage': 10.0,      # Max % performance degradation
            'max_p90_latency_seconds': 2.0,          # Max P90 latency during load
        },
        'first_token_test': {
            'min_success_rate': 0.90,                # Min % of queries under target time
            'avg_first_token_check': True,            # Average must be under target
        },
        'throughput_test': {
            'min_messages_per_minute': 30.0,         # Min throughput requirement
        },
        'context_impact_test': {
            'max_context_impact_seconds': 0.5,       # Max seconds impact from context
            'min_context_efficiency': 90.0,          # Min % efficiency at high context
        },
        'recovery_time_test': {
            'max_recovery_impact_seconds': 0.5,      # Max seconds for recovery impact
            'min_recovery_efficiency': 95.0,         # Min % recovery efficiency
        },
        
        # Global test suite thresholds
        'suite_pass_threshold': 80.0,                # Min % of tests that must pass per suite
    },
    
    # Model-specific performance targets
    'model_overrides': {
        'gpt-oss-20b': {
            'simple_latency_target': 5.0,      # Simple queries (was 2.0s)
            'complex_latency_target': 30.0,    # Complex queries (was 10.0s) 
            'first_token_target': 3.0,         # First token time (was 1.0s)
            'memory_threshold_mb': 8192,       # Memory threshold (was 6144)
            'baseline_memory_mb': 1024,        # Baseline GPU memory
            'model_memory_mb': 2560,           # Expected model loading memory
        },
        'gpt-oss-7b': {
            'simple_latency_target': 3.0,
            'complex_latency_target': 15.0,
            'first_token_target': 2.0,
            'memory_threshold_mb': 6144,
            'baseline_memory_mb': 1024,
            'model_memory_mb': 1536,
        },
        'default': {
            'simple_latency_target': 2.0,
            'complex_latency_target': 10.0,
            'first_token_target': 1.0,
            'memory_threshold_mb': 4096,
            'baseline_memory_mb': 512,
            'model_memory_mb': 512,
        }
    },
    'default_model': 'gpt-oss-20b',
    'throughput_target': 30.0,  # messages per minute
    'context_window': 4096,     # default context window size
    'test_timeouts': {
        'quick_test_timeout': 30.0,    # seconds
        'full_test_timeout': 300.0,    # seconds
        'integration_timeout': 600.0,  # seconds
    }
}

def get_model_config(model_name: str) -> dict:
    """Get configuration for a specific model."""
    # Find matching config by checking if model name contains key
    for config_key, config in TEST_CONFIG['model_overrides'].items():
        if config_key.lower() in model_name.lower():
            return config
    
    # Return default config if no match found
    return TEST_CONFIG['model_overrides']['default']

def calculate_percentiles(data: list) -> dict:
    """Calculate percentiles for a list of numeric values."""
    if not data:
        return {'p50': 0.0, 'p90': 0.0, 'p95': 0.0, 'p99': 0.0}
    
    sorted_data = sorted(data)
    n = len(sorted_data)
    
    def percentile(p):
        if n == 1:
            return sorted_data[0]
        index = (p / 100) * (n - 1)
        lower = int(index)
        upper = min(lower + 1, n - 1)
        weight = index - lower
        return sorted_data[lower] * (1 - weight) + sorted_data[upper] * weight
    
    return {
        'p50': percentile(50),
        'p90': percentile(90), 
        'p95': percentile(95),
        'p99': percentile(99)
    }

def get_pass_criteria(test_name: str) -> dict:
    """Get pass/fail criteria for a specific test."""
    criteria = TEST_CONFIG.get('pass_criteria', {}).get(test_name, {})
    if not criteria:
        # Return default criteria if test not found
        return {
            'min_success_rate': 0.80,
            'memory_threshold_check': True,
            'context_integrity_required': True
        }
    return criteria

def get_suite_pass_threshold() -> float:
    """Get the pass threshold for test suites."""
    return TEST_CONFIG.get('pass_criteria', {}).get('suite_pass_threshold', 80.0)

def should_use_real_cli() -> bool:
    """Determine if tests should use real CLI based on config and environment."""
    import os
    
    # Environment variable takes precedence
    env_setting = os.environ.get('USE_REAL_FOUNDRY', '').lower()
    if env_setting in ('true', '1', 'yes'):
        return True
    elif env_setting in ('false', '0', 'no'):
        return False
    
    # Fall back to config setting
    return TEST_CONFIG.get('use_real_cli', False)

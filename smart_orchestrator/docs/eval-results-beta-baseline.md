# Beta Baseline Eval Results

```json
{
  "domains": [
    "code",
    "creative",
    "factual",
    "reasoning",
    "math",
    "chat"
  ],
  "total_prompts": 300,
  "results": [
    {
      "config": "sovereign_only",
      "prompts": 1,
      "win_rate": 1.0,
      "cost_usd": 0.00011,
      "cache_hits": 0,
      "escalations": 0,
      "classify_tokens": 0,
      "route_tokens": 32,
      "prune_tokens_saved": 0,
      "avg_escalation_count": 0.0,
      "sensitive_overrides": 0
    },
    {
      "config": "groq_only",
      "prompts": 1,
      "win_rate": 1.0,
      "cost_usd": 3e-05,
      "cache_hits": 0,
      "escalations": 0,
      "classify_tokens": 0,
      "route_tokens": 31,
      "prune_tokens_saved": 0,
      "avg_escalation_count": 0.0,
      "sensitive_overrides": 0
    },
    {
      "config": "auto_routed",
      "prompts": 1,
      "win_rate": 1.0,
      "cost_usd": 0.00018,
      "cache_hits": 0,
      "escalations": 0,
      "classify_tokens": 0,
      "route_tokens": 32,
      "prune_tokens_saved": 0,
      "avg_escalation_count": 0.0,
      "sensitive_overrides": 0
    }
  ],
  "metrics": {
    "prometheus": "# HELP python_gc_objects_collected_total Objects collected during gc\n# TYPE python_gc_objects_collected_total counter\npython_gc_objects_collected_total{generation=\"0\"} 2126.0\npython_gc_objects_collected_total{generation=\"1\"} 264.0\npython_gc_objects_collected_total{generation=\"2\"} 51.0\n# HELP python_gc_objects_uncollectable_total Uncollectable objects found during GC\n# TYPE python_gc_objects_uncollectable_total counter\npython_gc_objects_uncollectable_total{generation=\"0\"} 0.0\npython_gc_objects_uncollectable_total{generation=\"1\"} 0.0\npython_gc_objects_uncollectable_total{generation=\"2\"} 0.0\n# HELP python_gc_collections_total Number of times this generation was collected\n# TYPE python_gc_collections_total counter\npython_gc_collections_total{generation=\"0\"} 588.0\npython_gc_collections_total{generation=\"1\"} 53.0\npython_gc_collections_total{generation=\"2\"} 4.0\n# HELP python_info Python platform information\n# TYPE python_info gauge\npython_info{implementation=\"CPython\",major=\"3\",minor=\"12\",patchlevel=\"3\",version=\"3.12.3\"} 1.0\n# HELP process_virtual_memory_bytes Virtual memory size in bytes.\n# TYPE process_virtual_memory_bytes gauge\nprocess_virtual_memory_bytes 5.65665792e+08\n# HELP process_resident_memory_bytes Resident memory size in bytes.\n# TYPE process_resident_memory_bytes gauge\nprocess_resident_memory_bytes 2.6331136e+08\n# HELP process_start_time_seconds Start time of the process since unix epoch in seconds.\n# TYPE process_start_time_seconds gauge\nprocess_start_time_seconds 1.77835966466e+09\n# HELP process_cpu_seconds_total Total user and system CPU time spent in seconds.\n# TYPE process_cpu_seconds_total counter\nprocess_cpu_seconds_total 2.4299999999999997\n# HELP process_open_fds Number of open file descriptors.\n# TYPE process_open_fds gauge\nprocess_open_fds 9.0\n# HELP process_max_fds Maximum number of open file descriptors.\n# TYPE process_max_fds gauge\nprocess_max_fds 524288.0\n# HELP orchestrator_requests_total Total number of inference requests\n# TYPE orchestrator_requests_total counter\n# HELP orchestrator_tokens_total Total tokens consumed\n# TYPE orchestrator_tokens_total counter\n# HELP orchestrator_request_latency_seconds Request latency in seconds\n# TYPE orchestrator_request_latency_seconds histogram\n# HELP orchestrator_ws_connections_active Number of active WebSocket connections\n# TYPE orchestrator_ws_connections_active gauge\norchestrator_ws_connections_active 0.0\n# HELP orchestrator_escalations_total Number of model escalations triggered\n# TYPE orchestrator_escalations_total counter\n# HELP orchestrator_errors_total Total errors by type\n# TYPE orchestrator_errors_total counter\n# HELP orchestrator_cache_hits_total Total cache hits\n# TYPE orchestrator_cache_hits_total counter\n# HELP orchestrator_cache_misses_total Total cache misses\n# TYPE orchestrator_cache_misses_total counter\norchestrator_cache_misses_total{cache_type=\"redis\"} 3.0\n# HELP orchestrator_cache_misses_created Total cache misses\n# TYPE orchestrator_cache_misses_created gauge\norchestrator_cache_misses_created{cache_type=\"redis\"} 1.7783596674175968e+09\n# HELP orchestrator_classify_calls_total Total classify stage calls\n# TYPE orchestrator_classify_calls_total counter\norchestrator_classify_calls_total{result=\"fallback\"} 3.0\n# HELP orchestrator_classify_calls_created Total classify stage calls\n# TYPE orchestrator_classify_calls_created gauge\norchestrator_classify_calls_created{result=\"fallback\"} 1.7783596674173675e+09\n# HELP orchestrator_route_calls_total Total route stage calls\n# TYPE orchestrator_route_calls_total counter\norchestrator_route_calls_total{model=\"llama-3.1-8b\"} 2.0\norchestrator_route_calls_total{model=\"llama-3.3-70b-versatile\"} 1.0\n# HELP orchestrator_route_calls_created Total route stage calls\n# TYPE orchestrator_route_calls_created gauge\norchestrator_route_calls_created{model=\"llama-3.1-8b\"} 1.7783596675394917e+09\norchestrator_route_calls_created{model=\"llama-3.3-70b-versatile\"} 1.7783596677026842e+09\n# HELP orchestrator_prune_calls_total Total prune stage calls\n# TYPE orchestrator_prune_calls_total counter\norchestrator_prune_calls_total 0.0\n# HELP orchestrator_prune_calls_created Total prune stage calls\n# TYPE orchestrator_prune_calls_created gauge\norchestrator_prune_calls_created 1.7783596653780267e+09\n",
    "counters": {
      "requests_total": 0.0
    }
  }
}
```


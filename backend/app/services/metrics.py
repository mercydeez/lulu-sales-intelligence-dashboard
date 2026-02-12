"""
Prometheus Metrics Service
Provides application metrics for monitoring and alerting.
"""
import time
from typing import Dict, Optional
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import asyncio

from app.config import logger


@dataclass
class MetricPoint:
    """A single metric data point."""
    value: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    labels: Dict[str, str] = field(default_factory=dict)


class MetricsCollector:
    """
    Simple in-memory metrics collector.
    Provides Prometheus-compatible metrics export.
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._initialized = True
        
        # Counters (cumulative)
        self._counters: Dict[str, float] = defaultdict(float)
        self._counter_labels: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        
        # Gauges (current value)
        self._gauges: Dict[str, float] = {}
        self._gauge_labels: Dict[str, Dict[str, float]] = defaultdict(dict)
        
        # Histograms (distribution)
        self._histogram_buckets = [0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0]
        self._histograms: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self._histogram_sums: Dict[str, float] = defaultdict(float)
        self._histogram_counts: Dict[str, int] = defaultdict(int)
        
        # Request tracking
        self._request_start_times: Dict[str, float] = {}
        
        # Initialize default metrics
        self._init_default_metrics()
        
        logger.info("Metrics collector initialized")
    
    def _init_default_metrics(self):
        """Initialize default application metrics."""
        # API metrics
        self._gauges["app_info"] = 1.0
        self._gauges["app_start_time"] = time.time()
        
    # =========================================================================
    # Counter Methods
    # =========================================================================
    
    def inc_counter(self, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None):
        """Increment a counter metric."""
        if labels:
            label_key = self._labels_to_key(labels)
            self._counter_labels[name][label_key] += value
        else:
            self._counters[name] += value
    
    def get_counter(self, name: str, labels: Optional[Dict[str, str]] = None) -> float:
        """Get current counter value."""
        if labels:
            label_key = self._labels_to_key(labels)
            return self._counter_labels[name].get(label_key, 0.0)
        return self._counters.get(name, 0.0)
    
    # =========================================================================
    # Gauge Methods
    # =========================================================================
    
    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """Set a gauge metric to a specific value."""
        if labels:
            label_key = self._labels_to_key(labels)
            self._gauge_labels[name][label_key] = value
        else:
            self._gauges[name] = value
    
    def inc_gauge(self, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None):
        """Increment a gauge metric."""
        if labels:
            label_key = self._labels_to_key(labels)
            current = self._gauge_labels[name].get(label_key, 0.0)
            self._gauge_labels[name][label_key] = current + value
        else:
            current = self._gauges.get(name, 0.0)
            self._gauges[name] = current + value
    
    def dec_gauge(self, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None):
        """Decrement a gauge metric."""
        self.inc_gauge(name, -value, labels)
    
    def get_gauge(self, name: str, labels: Optional[Dict[str, str]] = None) -> float:
        """Get current gauge value."""
        if labels:
            label_key = self._labels_to_key(labels)
            return self._gauge_labels[name].get(label_key, 0.0)
        return self._gauges.get(name, 0.0)
    
    # =========================================================================
    # Histogram Methods
    # =========================================================================
    
    def observe_histogram(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """Record a histogram observation."""
        label_suffix = f"_{self._labels_to_key(labels)}" if labels else ""
        full_name = f"{name}{label_suffix}"
        
        # Update buckets
        for bucket in self._histogram_buckets:
            if value <= bucket:
                bucket_key = f"{full_name}_bucket_le_{bucket}"
                self._histograms[name][bucket_key] += 1
        
        # +Inf bucket
        self._histograms[name][f"{full_name}_bucket_le_inf"] += 1
        
        # Sum and count
        self._histogram_sums[full_name] += value
        self._histogram_counts[full_name] += 1
    
    # =========================================================================
    # Request Tracking
    # =========================================================================
    
    def start_request(self, request_id: str):
        """Mark the start of a request."""
        self._request_start_times[request_id] = time.time()
        self.inc_gauge("http_requests_in_progress")
    
    def end_request(self, request_id: str, method: str, path: str, status_code: int):
        """Mark the end of a request and record metrics."""
        self.dec_gauge("http_requests_in_progress")
        
        start_time = self._request_start_times.pop(request_id, None)
        if start_time:
            duration = time.time() - start_time
            
            # Record request count
            labels = {"method": method, "path": self._normalize_path(path), "status": str(status_code)}
            self.inc_counter("http_requests_total", labels=labels)
            
            # Record request duration
            self.observe_histogram("http_request_duration_seconds", duration, labels={"method": method, "path": self._normalize_path(path)})
    
    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    def _labels_to_key(self, labels: Dict[str, str]) -> str:
        """Convert labels dict to a string key."""
        if not labels:
            return ""
        sorted_items = sorted(labels.items())
        return ",".join(f'{k}="{v}"' for k, v in sorted_items)
    
    def _normalize_path(self, path: str) -> str:
        """Normalize path for metrics (remove IDs)."""
        parts = path.split("/")
        normalized = []
        for part in parts:
            if part.isdigit():
                normalized.append(":id")
            else:
                normalized.append(part)
        return "/".join(normalized)
    
    # =========================================================================
    # Export Methods
    # =========================================================================
    
    def export_prometheus(self) -> str:
        """Export all metrics in Prometheus text format."""
        lines = []
        
        # App info
        lines.append("# HELP app_info Application information")
        lines.append("# TYPE app_info gauge")
        lines.append('app_info{version="1.0.0",environment="production"} 1')
        lines.append("")
        
        # Counters
        for name, value in self._counters.items():
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {value}")
        
        for name, label_values in self._counter_labels.items():
            lines.append(f"# TYPE {name} counter")
            for label_key, value in label_values.items():
                lines.append(f"{name}{{{label_key}}} {value}")
        
        if self._counters or self._counter_labels:
            lines.append("")
        
        # Gauges
        for name, value in self._gauges.items():
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {value}")
        
        for name, label_values in self._gauge_labels.items():
            lines.append(f"# TYPE {name} gauge")
            for label_key, value in label_values.items():
                lines.append(f"{name}{{{label_key}}} {value}")
        
        if self._gauges or self._gauge_labels:
            lines.append("")
        
        # Histograms
        for name in self._histogram_sums.keys():
            lines.append(f"# TYPE {name} histogram")
            for bucket_name, count in self._histograms.get(name.split("_")[0], {}).items():
                if name in bucket_name:
                    bucket_value = bucket_name.split("_le_")[-1]
                    if bucket_value == "inf":
                        lines.append(f'{name}_bucket{{le="+Inf"}} {int(count)}')
                    else:
                        lines.append(f'{name}_bucket{{le="{bucket_value}"}} {int(count)}')
            lines.append(f"{name}_sum {self._histogram_sums[name]}")
            lines.append(f"{name}_count {self._histogram_counts[name]}")
        
        return "\n".join(lines)
    
    def get_stats(self) -> Dict:
        """Get metrics as a dictionary for JSON export."""
        return {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": {
                name: {
                    "sum": self._histogram_sums.get(name, 0),
                    "count": self._histogram_counts.get(name, 0),
                    "avg": self._histogram_sums.get(name, 0) / max(self._histogram_counts.get(name, 1), 1)
                }
                for name in set(self._histogram_sums.keys())
            },
            "requests_in_progress": self._gauges.get("http_requests_in_progress", 0),
            "uptime_seconds": time.time() - self._gauges.get("app_start_time", time.time())
        }


# Global metrics instance
metrics = MetricsCollector()


def get_metrics() -> MetricsCollector:
    """Get the global metrics collector instance."""
    return metrics

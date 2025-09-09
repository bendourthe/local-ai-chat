"""
GPU memory monitoring module for performance optimization.

Monitors GPU memory usage and triggers cleanup when thresholds are exceeded.
Supports NVIDIA GPUs via nvidia-smi and Windows Management Instrumentation.

Authors:
    - Benjamin Dourthe (benjamin@adonamed.com)
"""
import os
import re
import subprocess
import threading
import time
from typing import Optional, Dict, Callable
from dataclasses import dataclass
try:
    from PySide6.QtCore import QObject, pyqtSignal, QTimer
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


@dataclass
class GPUMemoryInfo:
    """GPU memory usage information."""
    used_mb: int
    total_mb: int
    utilization_percent: float
    temperature_c: Optional[int] = None
    
    @property
    def usage_percent(self) -> float:
        """Calculate memory usage percentage."""
        if self.total_mb == 0:
            return 0.0
        return (self.used_mb / self.total_mb) * 100.0


class GPUMonitor:
    """Monitor GPU memory usage and trigger callbacks when thresholds are exceeded."""
    
    def __init__(self, threshold_mb: int = 8192):
        """Initialize GPU monitor with memory threshold."""
        self.threshold_mb = threshold_mb
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._callbacks: Dict[str, Callable[[GPUMemoryInfo], None]] = {}
        self._last_trigger_time = 0
        self._trigger_cooldown = 30  # 30 seconds between triggers
        self._last_info: Optional[GPUMemoryInfo] = None
        
    def get_gpu_memory_usage(self) -> Optional[GPUMemoryInfo]:
        """Return current GPU memory usage information."""
        # Try NVIDIA GPU first
        nvidia_info = self._get_nvidia_memory()
        if nvidia_info:
            return nvidia_info
            
        # Try Windows WMI for other GPUs
        wmi_info = self._get_wmi_memory()
        if wmi_info:
            return wmi_info
            
        return None
    
    def _get_nvidia_memory(self) -> Optional[GPUMemoryInfo]:
        """Get memory usage from NVIDIA GPU via nvidia-smi."""
        try:
            flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
            cmd = [
                'nvidia-smi', 
                '--query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu',
                '--format=csv,noheader,nounits'
            ]
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=5,
                creationflags=flags
            )
            
            if result.returncode == 0 and result.stdout.strip():
                # Parse first GPU (main one)
                line = result.stdout.strip().split('\n')[0]
                parts = [p.strip() for p in line.split(',')]
                
                if len(parts) >= 3:
                    used_mb = int(parts[0])
                    total_mb = int(parts[1])
                    utilization = float(parts[2])
                    temperature = None
                    
                    if len(parts) >= 4 and parts[3].replace('.', '').isdigit():
                        temperature = int(float(parts[3]))
                    
                    return GPUMemoryInfo(
                        used_mb=used_mb,
                        total_mb=total_mb,
                        utilization_percent=utilization,
                        temperature_c=temperature
                    )
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, 
                FileNotFoundError, ValueError, IndexError):
            pass
        
        return None
    
    def _get_wmi_memory(self) -> Optional[GPUMemoryInfo]:
        """Get memory usage from GPU via Windows WMI."""
        if os.name != 'nt':
            return None
            
        try:
            # PowerShell command to get GPU memory info
            ps_cmd = """
            Get-WmiObject -Class Win32_VideoController | Where-Object {$_.AdapterRAM -gt 0} | 
            Select-Object -First 1 AdapterRAM, VideoMemoryType | 
            ConvertTo-Json -Compress
            """
            
            flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            result = subprocess.run([
                'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', 
                '-Command', ps_cmd
            ], capture_output=True, text=True, timeout=10, creationflags=flags)
            
            if result.returncode == 0 and result.stdout.strip():
                import json
                data = json.loads(result.stdout.strip())
                
                if 'AdapterRAM' in data:
                    total_bytes = int(data['AdapterRAM'])
                    total_mb = total_bytes // (1024 * 1024)
                    
                    # WMI doesn't provide used memory directly
                    # Estimate based on system memory usage patterns
                    used_mb = int(total_mb * 0.1)  # Conservative estimate
                    
                    return GPUMemoryInfo(
                        used_mb=used_mb,
                        total_mb=total_mb,
                        utilization_percent=10.0  # Conservative estimate
                    )
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, 
                FileNotFoundError, json.JSONDecodeError, KeyError):
            pass
        
        return None
    
    def register_callback(self, name: str, callback: Callable[[GPUMemoryInfo], None]) -> None:
        """Register callback for memory threshold events."""
        self._callbacks[name] = callback
    
    def unregister_callback(self, name: str) -> None:
        """Unregister callback."""
        self._callbacks.pop(name, None)
    
    def start_monitoring(self, interval_seconds: float = 10.0) -> None:
        """Start monitoring GPU memory with callback when threshold exceeded."""
        if self._monitoring:
            return
            
        self._monitoring = True
        self._stop_event.clear()
        
        def _monitor_loop(self, interval_seconds: float) -> None:
            """Background monitoring loop."""
            while not self._stop_event.wait(interval_seconds):
                try:
                    info = self.get_gpu_memory_usage()
                    if info:
                        self._last_info = info
                        current_time = time.time()
                        
                        # Only trigger if above threshold and cooldown period has passed
                        if (info.used_mb > self.threshold_mb and 
                            current_time - self._last_trigger_time > self._trigger_cooldown):
                            self._last_trigger_time = current_time
                            # Trigger callbacks
                            for callback in self._callbacks.values():
                                try:
                                    callback(info)
                                except Exception:
                                    pass
                except Exception:
                    pass
        
        self._monitor_thread = threading.Thread(target=lambda: _monitor_loop(self, interval_seconds), daemon=True)
        self._monitor_thread.start()
    
    def stop_monitoring(self) -> None:
        """Stop GPU memory monitoring."""
        if not self._monitoring:
            return
            
        self._monitoring = False
        self._stop_event.set()
        
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2.0)
        
        self._monitor_thread = None
    
    def get_last_info(self) -> Optional[GPUMemoryInfo]:
        """Get the last recorded GPU memory information."""
        return self._last_info
    
    def is_monitoring(self) -> bool:
        """Check if monitoring is currently active."""
        return self._monitoring
    
    def set_threshold(self, threshold_mb: int) -> None:
        """Update the memory threshold for triggering callbacks."""
        self.threshold_mb = max(512, threshold_mb)  # Minimum 512MB threshold


# Global GPU monitor instance
_gpu_monitor = GPUMonitor()


def get_gpu_monitor() -> GPUMonitor:
    """Get the global GPU monitor instance."""
    return _gpu_monitor

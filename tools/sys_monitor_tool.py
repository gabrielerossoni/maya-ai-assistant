"""
sys_monitor_tool.py - Statistiche del PC in tempo reale
"""

import psutil

from core.gpu_stats import get_gpu_stats


class SysMonitorTool:
    def initialize(self):
        pass

    def execute(self, action: dict) -> dict:
        try:
            cpu_usage = psutil.cpu_percent(interval=0.5)
            ram = psutil.virtual_memory()
            ram_usage = ram.percent
            ram_total = ram.total / (1024**3)  # in GB
            ram_used = ram.used / (1024**3)  # in GB

            gpu_stats = get_gpu_stats()
            msg = f"Utilizzo CPU: {cpu_usage}%\nUtilizzo RAM: {ram_usage}% ({ram_used:.1f}GB su {ram_total:.1f}GB)"
            if gpu_stats.get("gpu_available"):
                gpu_name = gpu_stats.get("gpu_name") or "GPU"
                msg += f"\nUtilizzo {gpu_name}: {gpu_stats['gpu']}%"
            else:
                msg += "\nGPU: non rilevata"

            return {"status": "ok", "message": msg, "data": gpu_stats}
        except Exception as e:
            return {"status": "error", "message": str(e)}

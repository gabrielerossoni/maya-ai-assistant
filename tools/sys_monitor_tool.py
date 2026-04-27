"""
sys_monitor_tool.py - Statistiche del PC in tempo reale
"""
import psutil

class SysMonitorTool:
    def initialize(self):
        pass

    def execute(self, action: dict) -> dict:
        try:
            cpu_usage = psutil.cpu_percent(interval=0.5)
            ram = psutil.virtual_memory()
            ram_usage = ram.percent
            ram_total = ram.total / (1024 ** 3) # in GB
            ram_used = ram.used / (1024 ** 3)   # in GB

            msg = f"Utilizzo CPU: {cpu_usage}%\nUtilizzo RAM: {ram_usage}% ({ram_used:.1f}GB su {ram_total:.1f}GB)"
            return {"status": "ok", "message": msg}
        except Exception as e:
            return {"status": "error", "message": str(e)}

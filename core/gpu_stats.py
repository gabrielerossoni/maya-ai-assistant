"""
GPU usage helpers for dashboard and system monitor.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _nvidia_smi_candidates() -> list[str]:
    candidates = []
    path_hit = shutil.which("nvidia-smi")
    if path_hit:
        candidates.append(path_hit)

    program_files = os.environ.get("ProgramFiles")
    if program_files:
        candidates.append(str(Path(program_files) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe"))

    return list(dict.fromkeys(candidates))


def _read_nvidia_smi() -> dict[str, Any] | None:
    for executable in _nvidia_smi_candidates():
        try:
            completed = subprocess.run(
                [
                    executable,
                    "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue

        if completed.returncode != 0:
            continue

        line = next((item.strip() for item in completed.stdout.splitlines() if item.strip()), "")
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 4:
            continue

        try:
            return {
                "gpu": round(float(parts[1]), 1),
                "gpu_name": parts[0],
                "gpu_memory_used_mb": round(float(parts[2]), 1),
                "gpu_memory_total_mb": round(float(parts[3]), 1),
            }
        except ValueError:
            continue

    return None


def _read_gputil() -> dict[str, Any] | None:
    try:
        import GPUtil

        gpus = GPUtil.getGPUs()
    except Exception:
        return None

    if not gpus:
        return None

    gpu = gpus[0]
    return {
        "gpu": round(gpu.load * 100, 1),
        "gpu_name": getattr(gpu, "name", ""),
        "gpu_memory_used_mb": round(float(getattr(gpu, "memoryUsed", 0)), 1),
        "gpu_memory_total_mb": round(float(getattr(gpu, "memoryTotal", 0)), 1),
    }


def get_gpu_stats() -> dict[str, Any]:
    """
    Return GPU usage if available.

    GPUtil is kept as the first path for existing behavior; direct nvidia-smi is
    the fallback because GPUtil can fail when nvidia-smi is not on PATH.
    """
    stats = _read_gputil() or _read_nvidia_smi()
    if stats:
        return {"gpu_available": True, **stats}
    return {"gpu_available": False}

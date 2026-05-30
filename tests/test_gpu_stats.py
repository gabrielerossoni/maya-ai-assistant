from types import SimpleNamespace

from core import gpu_stats


def test_get_gpu_stats_uses_gputil(monkeypatch):
    monkeypatch.setattr(
        gpu_stats,
        "_read_gputil",
        lambda: {
            "gpu": 42.0,
            "gpu_name": "Test GPU",
            "gpu_memory_used_mb": 1000.0,
            "gpu_memory_total_mb": 2000.0,
        },
    )
    monkeypatch.setattr(gpu_stats, "_read_nvidia_smi", lambda: None)

    result = gpu_stats.get_gpu_stats()

    assert result["gpu_available"] is True
    assert result["gpu"] == 42.0
    assert result["gpu_name"] == "Test GPU"


def test_get_gpu_stats_falls_back_to_nvidia_smi(monkeypatch):
    monkeypatch.setattr(gpu_stats, "_read_gputil", lambda: None)
    monkeypatch.setattr(
        gpu_stats,
        "_read_nvidia_smi",
        lambda: {
            "gpu": 17.0,
            "gpu_name": "NVIDIA Test",
            "gpu_memory_used_mb": 256.0,
            "gpu_memory_total_mb": 1024.0,
        },
    )

    result = gpu_stats.get_gpu_stats()

    assert result["gpu_available"] is True
    assert result["gpu"] == 17.0
    assert result["gpu_name"] == "NVIDIA Test"


def test_read_nvidia_smi_parses_csv(monkeypatch):
    monkeypatch.setattr(gpu_stats, "_nvidia_smi_candidates", lambda: ["nvidia-smi"])
    monkeypatch.setattr(
        gpu_stats.subprocess,
        "run",
        lambda *_, **__: SimpleNamespace(
            returncode=0,
            stdout="NVIDIA RTX 4060, 9, 512, 8192\n",
        ),
    )

    result = gpu_stats._read_nvidia_smi()

    assert result == {
        "gpu": 9.0,
        "gpu_name": "NVIDIA RTX 4060",
        "gpu_memory_used_mb": 512.0,
        "gpu_memory_total_mb": 8192.0,
    }


def test_get_gpu_stats_reports_unavailable(monkeypatch):
    monkeypatch.setattr(gpu_stats, "_read_gputil", lambda: None)
    monkeypatch.setattr(gpu_stats, "_read_nvidia_smi", lambda: None)

    assert gpu_stats.get_gpu_stats() == {"gpu_available": False}

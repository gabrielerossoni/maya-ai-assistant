from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_env_example_uses_stable_safe_defaults():
    env = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "DISABLE_SELF_HEALER=true" in env
    assert "PLUGIN_LOADER_ENABLED=false" in env
    assert "DEV_MODE=false" in env
    assert "MAYA_WHISPER_DEVICE=auto" in env
    assert "Multitask Advanced Yielding Assistant" in env
    assert "Self-healer e plugin loader sono opt-in" in env


def test_pyproject_ruff_tmp_exclude_is_specific():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'extend-exclude = ["tests/.tmp_pytest"]' in pyproject
    assert 'extend-exclude = ["tests/.tmp_pytest*"]' not in pyproject


def test_single_presentation_artifact_exists():
    docs = ROOT / ".docs"

    assert (docs / "MAYA_presentazione.html").exists()
    assert not (docs / "Presentazione_Maya.html").exists()

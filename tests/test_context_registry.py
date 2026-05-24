"""
test_context_registry.py - Test per ContextManager e DeviceRegistry.

Copre: get/set, persistenza, time_slot, matches(), snapshot,
conflict detection, update_from_arduino_state.
"""

import json
import os
import sys
import time
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── ContextManager ────────────────────────────────────────────────────────────

class TestContextManager:
    def test_default_state(self, fresh_context):
        assert fresh_context.get("presence") == "unknown"
        assert fresh_context.get("weather") == "unknown"
        assert fresh_context.get("activity") == "idle"

    def test_set_and_get(self, fresh_context):
        fresh_context.set("presence", "home")
        assert fresh_context.get("presence") == "home"

    def test_set_scene(self, fresh_context):
        fresh_context.set_scene("buonanotte")
        assert fresh_context.get("active_scene") == "buonanotte"

    def test_snapshot_returns_copy(self, fresh_context):
        snap = fresh_context.snapshot()
        assert isinstance(snap, dict)
        assert "presence" in snap
        # Modifica snapshot non altera lo stato interno
        snap["presence"] = "HACKED"
        assert fresh_context.get("presence") != "HACKED"

    def test_matches_simple(self, fresh_context):
        fresh_context.set("presence", "home")
        fresh_context.set("weather", "rain")
        assert fresh_context.matches({"presence": "home"})
        assert fresh_context.matches({"presence": "home", "weather": "rain"})
        assert not fresh_context.matches({"presence": "away"})

    def test_matches_list_values(self, fresh_context):
        fresh_context.set("time_slot", "evening")
        with patch.object(type(fresh_context), "_compute_time_slot", return_value="evening"):
            assert fresh_context.matches({"time_slot": ["evening", "night"]})
            assert not fresh_context.matches({"time_slot": ["morning", "afternoon"]})

    def test_persistence(self, fresh_context, tmp_data_dir):
        fresh_context.set("activity", "working")
        # Forza reload
        from core.context_manager import ContextManager
        ContextManager._instance = None
        ctx2 = ContextManager()
        # activity persiste, ma weather/presence vengono resettati al reload
        assert ctx2.get("activity") == "working"

    def test_time_slot_is_string(self, fresh_context):
        ts = fresh_context.get("time_slot")
        assert ts in ("morning", "afternoon", "evening", "night")

    def test_get_default(self, fresh_context):
        assert fresh_context.get("nonexistent", "fallback") == "fallback"


# ── DeviceRegistry ────────────────────────────────────────────────────────────

class TestDeviceRegistry:
    def test_update_and_get(self, fresh_registry):
        fresh_registry.update("light", True, scene="test")
        assert fresh_registry.get_value("light") is True

    def test_get_entry(self, fresh_registry):
        fresh_registry.update("servo", 90, scene="ospite")
        entry = fresh_registry.get_entry("servo")
        assert entry is not None
        assert entry["value"] == 90
        assert entry["last_set_by"] == "ospite"
        assert "ts" in entry

    def test_get_nonexistent(self, fresh_registry):
        assert fresh_registry.get_value("fantasma") is None
        assert fresh_registry.get_value("fantasma", "default") == "default"
        assert fresh_registry.get_entry("fantasma") is None

    def test_snapshot(self, fresh_registry):
        fresh_registry.update("light", False)
        fresh_registry.update("relay", True)
        snap = fresh_registry.snapshot()
        assert "light" in snap
        assert "relay" in snap

    def test_get_current_values(self, fresh_registry):
        fresh_registry.update("light", True)
        fresh_registry.update("rgb", [255, 0, 0])
        vals = fresh_registry.get_current_values()
        assert vals["light"] is True
        assert vals["rgb"] == [255, 0, 0]

    def test_update_from_arduino_state(self, fresh_registry):
        state = {"light": False, "servo": 45, "relay": True}
        fresh_registry.update_from_arduino_state(state, scene="hardware")
        assert fresh_registry.get_value("light") is False
        assert fresh_registry.get_value("servo") == 45
        entry = fresh_registry.get_entry("relay")
        assert entry["last_set_by"] == "hardware"

    def test_conflict_detection(self, fresh_registry):
        fresh_registry.update("light", True, scene="buonanotte")
        # Appena aggiornato → conflitto
        assert fresh_registry.check_conflict("light", False, min_age_seconds=5.0) is True

    def test_no_conflict_after_time(self, fresh_registry):
        fresh_registry.update("light", True)
        # Forza un timestamp vecchio
        fresh_registry._devices["light"]["ts"] = time.time() - 100
        assert fresh_registry.check_conflict("light", False, min_age_seconds=5.0) is False

    def test_persistence(self, fresh_registry, tmp_data_dir):
        fresh_registry.update("relay", True, scene="test_persist")
        from core.device_registry import DeviceRegistry
        DeviceRegistry._instance = None
        reg2 = DeviceRegistry()
        assert reg2.get_value("relay") is True

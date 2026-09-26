"""Default-deny policy for irreversible or network-side-effect actions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    requires_confirmation: bool
    reason: str


class PermissionEngine:
    SAFE_TOOLS = {"calendar", "weather", "news", "notes", "search", "none"}
    SENSITIVE_TOOLS = {"system", "mqtt", "browser", "home_assistant", "network"}

    def decide(self, action: dict) -> PermissionDecision:
        tool = str(action.get("tool", "none"))
        if tool in self.SAFE_TOOLS and action.get("action") not in {"delete", "remove"}:
            return PermissionDecision(True, False, "safe")
        if tool in self.SENSITIVE_TOOLS or action.get("action") in {"delete", "remove"}:
            return PermissionDecision(False, True, "sensitive_action")
        return PermissionDecision(False, True, "unknown_action")

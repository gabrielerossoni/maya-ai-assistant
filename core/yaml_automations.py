"""Optional declarative context automations; invalid files never stop startup."""

from __future__ import annotations

from pathlib import Path

from .automation_engine import Action, Automation, Condition, Priority, Scene, Trigger


def load_yaml_automations(path: str | Path) -> list[Automation]:
    try:
        import yaml

        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (ImportError, OSError, ValueError):
        return []
    automations = []
    for entry in payload.get("automations", []):
        try:
            actions = [Action(str(item["tool"]), dict(item.get("params", {}))) for item in entry.get("actions", [])]
            triggers = [Trigger(**item) for item in entry.get("triggers", [])]
            scene = Scene(
                name=str(entry["name"]),
                actions=actions,
                priority=Priority[str(entry.get("priority", "NORMAL")).upper()],
                conditions=[Condition(dict(item)) for item in entry.get("conditions", [])],
            )
            automations.append(Automation(scene, aliases=list(entry.get("aliases", [])), triggers=triggers))
        except (KeyError, TypeError, ValueError):
            continue
    return automations

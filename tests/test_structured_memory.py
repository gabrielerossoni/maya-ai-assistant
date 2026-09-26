from datetime import datetime, timezone

from core.agent_core import AgentCore
from core.memory.structured import StructuredMemory


def test_structured_memory_persists_all_phase_one_data_types(tmp_path):
    memory = StructuredMemory(tmp_path / "maya.sqlite3")
    memory.initialize()

    note = memory.add_note("Comprare il latte")
    reminder = memory.add_reminder("Bolletta", datetime(2026, 9, 26, 9, tzinfo=timezone.utc))
    fact = memory.remember_fact("Trapano", "Prestato a Marco")
    preference = memory.set_preference("briefing_time", "08:00")

    assert memory.list_notes() == [
        {
            "id": note["id"],
            "content": "Comprare il latte",
            "created_at": note["created_at"],
            "updated_at": note["created_at"],
        }
    ]
    assert memory.due_reminders(datetime(2026, 9, 26, 10, tzinfo=timezone.utc)) == [reminder]
    assert memory.find_facts("trapano")[0]["value"] == fact["value"]
    assert preference["value"] == "08:00"


def test_remember_fact_updates_a_previous_subject(tmp_path):
    memory = StructuredMemory(tmp_path / "maya.sqlite3")
    memory.initialize()
    memory.remember_fact("Trapano", "Prestato a Marco")
    memory.remember_fact("Trapano", "Rientrato in garage")

    assert memory.find_facts("trapano") == [
        {
            "subject": "trapano",
            "value": "Rientrato in garage",
            "updated_at": memory.find_facts("trapano")[0]["updated_at"],
        }
    ]


def test_agent_parses_phase_one_memory_commands():
    agent = AgentCore.__new__(AgentCore)

    assert agent._parse_direct_structured_memory_command("segnati che ho prestato il trapano a Marco") == (
        "fact",
        {"subject": "trapano", "value": "Prestato a Marco"},
    )
    assert agent._parse_direct_structured_memory_command("dov'è il trapano?") == (
        "fact_lookup",
        {"query": "trapano"},
    )

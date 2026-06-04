import pytest

from core.memory_manager import MemoryManager


class EmptyCollection:
    def __init__(self):
        self.added = []

    def count(self):
        return 0

    def add(self, **kwargs):
        self.added.append(kwargs)


@pytest.mark.asyncio
async def test_migrate_json_to_chroma_logs_when_collection_empty(capsys):
    async def fake_embedding(_text):
        return []

    memory = MemoryManager.__new__(MemoryManager)
    memory.collection = EmptyCollection()
    memory.turns = [{"role": "user", "text": "ciao", "time": "2026-06-04"}]
    memory._get_embedding = fake_embedding

    await memory.migrate_json_to_chroma()

    out = capsys.readouterr().out
    assert "ChromaDB vuoto" in out
    assert "Migrazione completata: 1 turni indicizzati" in out
    assert memory.collection.added

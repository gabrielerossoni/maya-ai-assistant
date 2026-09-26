"""Tool facade for allowlisted Home Assistant entity controls."""

from core.home_assistant import HomeAssistantAdapter


class HomeAssistantTool:
    def __init__(self):
        self.adapter = HomeAssistantAdapter()

    def initialize(self):
        pass

    async def execute(self, action: dict) -> dict:
        entity_id = str(action.get("entity_id", ""))
        service = str(action.get("service", ""))
        return await self.adapter.set_state(entity_id, service)

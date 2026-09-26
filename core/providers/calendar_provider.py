"""Calendar adapter retaining current Google Calendar tool."""

class CalendarProvider:
    def __init__(self, tool_manager):
        self.tool_manager = tool_manager

    async def list(self) -> dict:
        return await self.tool_manager.execute({"tool": "calendar", "action": "list"})

    def health(self) -> bool:
        return "calendar" in self.tool_manager.tools

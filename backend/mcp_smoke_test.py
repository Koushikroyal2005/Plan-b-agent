"""Protocol-level smoke test for the running Plan B MCP server."""

import asyncio

from mcp import Client


async def main() -> None:
    async with Client("http://127.0.0.1:8011/mcp") as client:
        tools = await client.list_tools()
        names = [tool.name for tool in tools.tools]
        assert len(names) == 10, f"Expected 10 tools, received {len(names)}: {names}"
        result = await client.call_tool("check_deadline_risks", {})
        assert not result.is_error, result
        print(f"MCP OK: {len(names)} tools; check_deadline_risks succeeded")


if __name__ == "__main__":
    asyncio.run(main())

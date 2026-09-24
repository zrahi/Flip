"""A pretend Roblox Studio MCP server with one tool, for tests."""
try:
    from mcp.server.mcpserver import MCPServer as Server
except ImportError:
    from mcp.server.fastmcp import FastMCP as Server

app = Server("fake-studio")


@app.tool()
def run_code(command: str) -> str:
    """Run Luau in Studio."""
    return f"ran: {command}"


app.run()

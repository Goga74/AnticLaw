"""Entry point for running the AnticLaw MCP server: python -m anticlaw.mcp"""

from anticlaw.mcp.server import mcp

if __name__ == "__main__":
    mcp.run()

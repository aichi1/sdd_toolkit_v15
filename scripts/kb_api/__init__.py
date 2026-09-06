"""Knowledge Base API (FastAPI REST). Renamed from mcp_server in Phase 13 (R-22 / C-13)."""

from . import handlers, schemas, server

__all__ = ["handlers", "schemas", "server"]

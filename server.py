"""Backward-compatible entry point.

Older Claude Desktop configs run ``uv --directory <path> run python server.py``.
The server now lives in ``src/notebooklm_study_mcp``; prefer
``uv --directory <path> run notebooklm-study-mcp``.
"""

from notebooklm_study_mcp.server import main

if __name__ == "__main__":
    main()

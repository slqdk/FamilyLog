"""Small helpers shared by test files (importable: conftest puts tests/ on the path)."""
from __future__ import annotations

import socket


def closed_port_url() -> str:
    """An http URL on localhost where nothing listens."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}"

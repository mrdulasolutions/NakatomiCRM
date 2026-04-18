"""Memory connector subsystem.

Thin pluggable layer. Nakatomi does not store semantic embeddings. Instead it
forwards events to external memory systems (DocDeploy, Supermemory, …) and
answers recall queries by fanning out across them.
"""

from app.services.memory.base import MemoryConnector, MemoryItem  # noqa: F401
from app.services.memory.registry import enabled_connectors, get_connector  # noqa: F401

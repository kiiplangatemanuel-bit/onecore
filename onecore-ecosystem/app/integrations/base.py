from abc import ABC, abstractmethod
from typing import Any

class IntegrationAdapter(ABC):
    """Provider boundary. Implement provider-specific HTTP, signing and mapping here."""
    provider: str

    @abstractmethod
    async def health(self) -> dict[str, Any]: ...

    async def execute(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(f"{self.provider} operation {operation!r} is not implemented")

"""Contract for regulatory document search.

Defines the interface any search backend must satisfy. Agent logic
depends only on this Protocol, never on a concrete provider.
"""

from typing import Protocol


class RegulationSearchProvider(Protocol):
    """Contract for querying the regulatory document store."""

    def search(self, query: str) -> str:
        """Search regulatory documents and return a grounded answer.

        Args:
            query: Natural-language search query.

        Returns:
            Generated, citation-grounded answer text.

        Raises:
            RuntimeError: If the underlying search backend is unreachable.
        """
        ...

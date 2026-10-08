"""Contract for regulatory document search.

Defines the interface any search backend must satisfy. Agent logic
depends only on this Protocol, never on a concrete provider.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SearchResult:
    """A grounded answer plus the documents it was generated from.

    Attributes:
        answer: Generated answer text containing citation markers ("[1]").
        sources: File names of the cited documents; sources[i] is marker [i + 1].
    """

    answer: str
    sources: list[str]


class RegulationSearchProvider(Protocol):
    """Contract for querying the regulatory document store."""

    def search(self, query: str) -> SearchResult:
        """Search regulatory documents and return a grounded answer.

        Args:
            query: Natural-language search query.

        Returns:
            Generated answer text and the file names it cites.

        Raises:
            RuntimeError: If the underlying search backend is unreachable.
        """
        ...

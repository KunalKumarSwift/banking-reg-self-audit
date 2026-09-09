"""Vertex AI Search implementation of RegulationSearchProvider."""

from google.cloud import discoveryengine_v1 as discoveryengine

from compliance_agent._contracts.search import RegulationSearchProvider


class VertexSearchProvider(RegulationSearchProvider):
    """Queries the compliance-search-app for grounded regulatory answers."""

    def __init__(self, project_id: str, location: str, engine_id: str) -> None:
        """Initialize the provider targeting a specific Vertex AI Search app.

        Args:
            project_id: GCP project ID.
            location: Search app location (e.g. "global").
            engine_id: The Vertex AI Search app's engine ID.
        """
        self._serving_config = (
            f"projects/{project_id}/locations/{location}/collections/"
            f"default_collection/engines/{engine_id}/servingConfigs/default_search"
        )
        self._client = discoveryengine.SearchServiceClient()

    def search(self, query: str) -> str:
        """See RegulationSearchProvider.search."""
        request = discoveryengine.SearchRequest(
            serving_config=self._serving_config,
            query=query,
            content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
                summary_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec(
                    summary_result_count=5,
                    include_citations=True,
                )
            ),
        )
        response = self._client.search(request)
        return response.summary.summary_text

"""Vertex AI Search implementation of RegulationSearchProvider.

The summary's references don't carry the gs:// link, so each cited
document's file name is taken from the matching search result's link.
"""

from google.cloud import discoveryengine_v1 as discoveryengine

from compliance_agent._contracts.search import RegulationSearchProvider, SearchResult


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

    def search(self, query: str) -> SearchResult:
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

        # e.g. "gs://bucket/osfi/B-13-technology-cyber-risk.pdf" -> "B-13-technology-cyber-risk.pdf"
        file_names = {
            result.document.name: str(
                dict(result.document.derived_struct_data).get("link", "")
            ).rsplit("/", 1)[-1]
            for result in response.results
        }
        sources = [
            # Chunked data stores cite ".../documents/<id>/chunks/<n>"; results use ".../documents/<id>".
            file_names.get(ref.document.split("/chunks/")[0]) or ref.title
            for ref in response.summary.summary_with_metadata.references
        ]
        return SearchResult(answer=response.summary.summary_text, sources=sources)

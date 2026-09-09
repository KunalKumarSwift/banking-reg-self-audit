"""Quick manual test for the Vertex AI Search provider."""

from compliance_agent.config import load_config
from compliance_agent._providers.vertex_search import VertexSearchProvider


def main() -> None:
    config = load_config()
    provider = VertexSearchProvider(
        project_id=config.project_id,
        location=config.search_location,
        engine_id=config.search_engine_id,
    )
    answer = provider.search("technology and cyber risk governance requirements")
    print(answer)


if __name__ == "__main__":
    main()

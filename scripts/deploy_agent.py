"""Deploys the compliance agent to Vertex AI Agent Engine."""

import os
from pathlib import Path

import vertexai
from vertexai import agent_engines

from compliance_agent.agent import root_agent
from compliance_agent.config import load_config


def main() -> None:
    config = load_config()
    vertexai.init(
        project=config.project_id,
        location=config.agent_location,
        staging_bucket=f"gs://{config.project_id}-agent-staging",
    )

    # agent_engines.create() tars extra_packages using the given relative path
    # as-is for the archive member name (no arcname stripping). root_agent was
    # pickled with module path `compliance_agent.*` (our src-layout install
    # puts `src` on sys.path, not `src/compliance_agent`), so the uploaded
    # archive must contain `compliance_agent/` at its root — not
    # `src/compliance_agent/` — or the remote unpickle fails with
    # `ModuleNotFoundError: No module named 'compliance_agent'`.
    os.chdir(Path(__file__).resolve().parent.parent / "src")

    remote_agent = agent_engines.create(
        agent_engine=root_agent,
        requirements=[
            "google-adk",
            "google-cloud-aiplatform[agent_engines]",
            "google-cloud-discoveryengine",
            "python-dotenv",
        ],
        extra_packages=["compliance_agent"],
        env_vars={
            "SEARCH_LOCATION": config.search_location,
            "AGENT_LOCATION": config.agent_location,
            "SEARCH_ENGINE_ID": config.search_engine_id,
            "MODEL_NAME": config.model_name,
            "ENVIRONMENT": "remote",
        },
        display_name="compliance-self-audit-agent",
    )

    print(f"Deployed. Resource name: {remote_agent.resource_name}")


if __name__ == "__main__":
    main()

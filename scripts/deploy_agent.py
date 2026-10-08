"""Deploys the compliance agent to Vertex AI Agent Engine.

Creates the Agent Engine on the first run. Once REASONING_ENGINE_RESOURCE_NAME
is set in .env (the first run prints it), later runs update that same engine,
so its resource name, and anything pointing at it such as the webapp, stays
the same.

Remote packages are pinned to the versions installed locally: root_agent is
pickled here and unpickled in the cloud, which breaks or changes behaviour if
ADK, pydantic or cloudpickle differ between the two sides.
"""

import os
from importlib.metadata import version
from pathlib import Path

import vertexai
from vertexai import agent_engines

from compliance_agent.agent import root_agent
from compliance_agent.config import load_config

# Distribution name -> requirement prefix (extras included) for the cloud side.
_PINNED_PACKAGES = {
    "google-adk": "google-adk",
    "google-cloud-aiplatform": "google-cloud-aiplatform[agent_engines]",
    "google-cloud-discoveryengine": "google-cloud-discoveryengine",
    "python-dotenv": "python-dotenv",
    "pydantic": "pydantic",
    "cloudpickle": "cloudpickle",
}


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

    requirements = [f"{req}=={version(dist)}" for dist, req in _PINNED_PACKAGES.items()]
    settings = {
        "agent_engine": root_agent,
        "requirements": requirements,
        "extra_packages": ["compliance_agent"],
        "env_vars": {
            "SEARCH_LOCATION": config.search_location,
            "AGENT_LOCATION": config.agent_location,
            "SEARCH_ENGINE_ID": config.search_engine_id,
            "MODEL_NAME": config.model_name,
        },
        "display_name": "compliance-self-audit-agent",
    }
    print("Pinned requirements:\n  " + "\n  ".join(requirements))

    if config.reasoning_engine_resource_name:
        print(f"Updating {config.reasoning_engine_resource_name} ...")
        remote_agent = agent_engines.update(
            resource_name=config.reasoning_engine_resource_name, **settings
        )
        print(f"Updated. Resource name: {remote_agent.resource_name}")
    else:
        print("No REASONING_ENGINE_RESOURCE_NAME in .env; creating a new Agent Engine ...")
        remote_agent = agent_engines.create(**settings)
        print(f"Deployed. Resource name: {remote_agent.resource_name}")
        print("Add it to .env as REASONING_ENGINE_RESOURCE_NAME so later deploys update it.")


if __name__ == "__main__":
    main()

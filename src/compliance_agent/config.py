"""Environment configuration for the compliance agent.

This is the only module allowed to read os.environ. Every other module
receives configuration as explicit constructor arguments.

Locally, `load_dotenv()` reads a `.env` file (gitignored) into the process
environment. When deployed to Agent Engine, no `.env` file exists — the
same variable names are set directly as real environment variables in the
deployment config, so `load_config()` behaves identically either way.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """Runtime configuration for the compliance agent.

    Attributes:
        project_id: GCP project ID.
        search_location: Vertex AI Search location (typically "global").
        agent_location: Vertex AI Agent Engine location (e.g. "us-central1").
        search_engine_id: The Vertex AI Search app's engine ID.
        model_name: Gemini model identifier used for reasoning.
        environment: "local" or "remote" — lets code branch behavior if ever needed.
    """

    project_id: str
    search_location: str
    agent_location: str
    search_engine_id: str
    model_name: str
    environment: str


def load_config() -> AgentConfig:
    """Load configuration from environment variables.

    Returns:
        A populated AgentConfig.

    Raises:
        RuntimeError: If a required environment variable is missing.
    """
    required = [
        "GOOGLE_CLOUD_PROJECT",
        "SEARCH_LOCATION",
        "AGENT_LOCATION",
        "SEARCH_ENGINE_ID",
    ]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")

    return AgentConfig(
        project_id=os.environ["GOOGLE_CLOUD_PROJECT"],
        search_location=os.environ["SEARCH_LOCATION"],
        agent_location=os.environ["AGENT_LOCATION"],
        search_engine_id=os.environ["SEARCH_ENGINE_ID"],
        model_name=os.environ.get("MODEL_NAME", "gemini-2.5-flash"),
        environment=os.environ.get("ENVIRONMENT", "local"),
    )

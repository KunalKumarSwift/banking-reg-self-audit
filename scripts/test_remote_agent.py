"""Quick manual test that queries the already-deployed remote agent.

Requires GOOGLE_CLOUD_PROJECT, AGENT_LOCATION, and REASONING_ENGINE_RESOURCE_NAME
in .env (see .env.example) — the resource name is printed by deploy_agent.py
on a successful deploy.
"""

import os

import vertexai
from dotenv import load_dotenv
from vertexai import agent_engines

load_dotenv()

project_id = os.environ["GOOGLE_CLOUD_PROJECT"]
location = os.environ["AGENT_LOCATION"]
resource_name = os.environ["REASONING_ENGINE_RESOURCE_NAME"]

vertexai.init(project=project_id, location=location)

agent_engine = agent_engines.get(resource_name)

for event in agent_engine.stream_query(
    user_id="test-user",
    message="What are the technology risk governance requirements for a new digital banking feature?",
):
    print(event)

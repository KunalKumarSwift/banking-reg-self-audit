"""Runs the full agent pipeline locally (no deploy) for a three-turn conversation.

Streams with SSE like Agent Engine does, and prints what a chat UI would
show: each event's author, any tool calls, and the text of final events.
Turn 1 should go through the audit pipeline and end with a sources table;
turns 2-3 are follow-ups the router should answer directly, in free form
(turn 3 may call search_regulations, but must not run the pipeline).
"""

import asyncio

# ADK documents this import path but doesn't list StreamingMode as a re-export.
from google.adk.agents.run_config import (
    RunConfig,
    StreamingMode,  # pyright: ignore[reportPrivateImportUsage]
)
from google.adk.runners import InMemoryRunner
from google.genai import types

from compliance_agent.agent import root_agent

_TURNS = [
    (
        "Check this feature: customers can log in to the mobile banking app with "
        "face ID and approve e-transfers up to $3,000 without an extra OTP."
    ),
    "How should we fix the High severity gaps? Give concrete changes to the feature.",
    "Does PIPEDA say how long we can keep the authentication audit logs?",
]


async def main() -> None:
    runner = InMemoryRunner(agent=root_agent, app_name="compliance_local")
    session = await runner.session_service.create_session(
        app_name="compliance_local", user_id="local-user"
    )
    run_config = RunConfig(streaming_mode=StreamingMode.SSE)
    for turn in _TURNS:
        print(f"\n{'=' * 80}\nUSER: {turn}\n{'=' * 80}")
        async for event in runner.run_async(
            user_id="local-user",
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=turn)]),
            run_config=run_config,
        ):
            parts = event.content.parts if event.content and event.content.parts else []
            for part in parts:
                if part.function_call:
                    print(f"[{event.author}] tool_call: {part.function_call.name}")
                if part.text and not event.partial:
                    print(f"[{event.author}] FINAL TEXT:\n{part.text}")


if __name__ == "__main__":
    asyncio.run(main())

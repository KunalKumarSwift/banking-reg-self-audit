# Compliance Self-Audit Agent — How We Built This (Beginner's Guide)

This README explains, from the ground up, everything we built and _why_. If you've never touched Google Cloud before, this should still make sense — we explain every concept before using it.

## What This Project Does

Imagine you're building a new feature for a bank — say, a way for customers to send money to each other from their phones. Before you launch it, a compliance team needs to check it against a pile of government rules (from OSFI, Canada's bank regulator, and others). That review usually happens _late_, after the feature is mostly built.

This project builds an AI "assistant" that engineers can ask _early_ — "does my feature idea have any obvious compliance problems?" — before the official review even starts. Think of it as a spell-checker, but for regulations instead of grammar.

To do that, the assistant needs to:

1. **Read** a pile of real regulatory documents (PDFs)
2. **Search** through them intelligently when asked a question
3. **Reason** about what it found and give a structured answer
4. **Live somewhere** so anyone can ask it questions, not just your own laptop

Each of those four things maps to a different piece of Google Cloud, which we'll walk through.

---

## Part 1: The Building Blocks (Concepts First)

Before any commands, here's what each piece of Google Cloud actually _is_, in plain terms.

### A GCP Project

Think of a **Google Cloud Project** as a labeled box. Everything you create — storage, AI services, permissions — lives inside one specific box, identified by a **Project ID** (ours is `<YOUR_PROJECT_ID>`). If you have multiple projects, you have to tell every tool which box you're working in.

### Cloud Storage (a "bucket")

A **bucket** is just a folder that lives on Google's servers instead of your laptop. We created one (`gs://<YOUR_PROJECT_ID>-compliance-docs`) to hold our regulatory PDF files. `gs://` is just the web-address style prefix that means "this is a Cloud Storage location," the same way `https://` means "this is a website."

### Vertex AI Search (the "librarian")

Imagine hiring a librarian who has read every document in your bucket, memorized it, and can instantly answer questions like "what does the rulebook say about biometric login?" — and even tell you _which_ book and page it came from. That's what Vertex AI Search does. You don't have to teach it how to read or search — you just hand it documents, and it builds its own internal index automatically.

Behind the scenes, this involves an idea called **embeddings** — turning sentences into lists of numbers that capture their _meaning_, so the computer can find "similar meaning" text even if the exact words don't match. You don't need to build this yourself; Vertex AI Search does it for you.

### An Agent (the "assistant")

An **agent**, in AI terms, isn't just a chatbot that talks — it's a program that can _decide to take actions_ to answer a question. Our agent's action is "search the regulations" — when you ask it something, it decides on its own to call the librarian (Vertex AI Search), read what comes back, and then write you a proper answer using that information. This pattern is called **RAG** — Retrieval-Augmented Generation: _retrieve_ real documents, then _generate_ an answer grounded in them, instead of the AI just guessing from memory.

### Vertex AI Agent Engine (the "hosting")

Writing the assistant on your laptop is only useful to you. **Agent Engine** is Google's way of taking your assistant and giving it a permanent home in the cloud — a real address other people (or other programs) can call, 24/7, without your laptop needing to be on.

### IAM (Identity and Access Management) — "who's allowed to do what"

Google Cloud doesn't let anyone do anything by default — every action needs explicit permission. **IAM** is the system that manages this. Two ideas matter here:

- A **service account** is like an employee ID badge — but for a _program_ instead of a person. When your deployed agent runs in the cloud, it's not "you" anymore; it's a robot wearing a badge, and that badge needs its own permissions.
- A **role** is a bundle of permissions you hand to a badge — e.g., "can search this specific library, but can't add or delete books."

We'll come back to this in detail in Part 5, because it caused us real trouble during deployment — a good learning moment.

---

## Part 2: Setting Up Your Local Machine

### Logging into Google Cloud

```bash
gcloud auth login
gcloud auth application-default login
```

Two logins, two different jobs:

- `gcloud auth login` lets your **terminal commands** (like `gcloud storage buckets create`) act as you.
- `gcloud auth application-default login` lets your **Python code** act as you, when running locally.

### Picking your project

```bash
gcloud projects list
gcloud config set project <YOUR_PROJECT_ID>
```

`gcloud projects list` shows every "box" you have access to. `gcloud config set project` tells your terminal which box to work in by default, so you don't have to specify it on every single command.

---

## Part 3: Creating the Storage and Search Layer

### Creating a bucket

```bash
gcloud storage buckets create gs://<YOUR_PROJECT_ID>-compliance-docs \
  --location=us-central1 \
  --uniform-bucket-level-access
```

- `gs://<YOUR_PROJECT_ID>-compliance-docs` — the bucket's unique name (bucket names must be globally unique across _all_ of Google Cloud, not just your project — like a username).
- `--location=us-central1` — which physical region of Google's data centers stores this data. Doesn't need to match every other resource's region.
- `--uniform-bucket-level-access` — a security setting meaning "permissions apply to the whole bucket the same way," rather than allowing different files inside to have wildly different permission rules. Simpler and safer for most use cases.

### Uploading files

```bash
gcloud storage cp data/osfi/B-13-technology-cyber-risk.pdf \
  gs://<YOUR_PROJECT_ID>-compliance-docs/osfi/
```

`cp` (copy) works just like copying a file on your own computer, except the destination is a cloud bucket instead of a folder.

### Creating the Search "app"

We did this through the web console rather than the command line, because it involves several linked pieces (a **data store**, which holds the indexed content, and an **app**, which is the thing you actually query). Key choices we made and why:

| Setting                      | What we chose            | Why                                                                                           |
| ---------------------------- | ------------------------ | --------------------------------------------------------------------------------------------- |
| Data type                    | Documents (unstructured) | Our PDFs aren't spreadsheets/structured data                                                  |
| Sync frequency               | One time                 | We're manually curating documents for now, not auto-refreshing                                |
| Contains access control info | No                       | Every user should see the same documents — no per-person restrictions needed                  |
| Document parser              | Layout Parser            | Understands headings/sections in structured PDFs, better than treating it as one wall of text |
| Search type (on the App)     | Search with follow-ups   | Enables the "generate an actual answer, not just links" behavior                              |

**A concept worth understanding: the Search "pipeline."** Vertex AI Search actually runs your query through four stages internally:

1. **Prepare** — cleans up/interprets your query
2. **Retrieve** — pulls matching chunks of text from your documents
3. **Signal** — re-ranks and filters those chunks by relevance
4. **Serve** — writes a final, readable answer using the best chunks

You don't have to build any of this — it's what you're paying for by using this managed product instead of building your own search from scratch.

---

## Part 4: The Python Code

### Why we organized the code this way

We used a **Protocol + Provider** pattern. In plain terms: we separated "_what_ the search feature needs to do" from "_how_ it's actually done today."

- `_contracts/search.py` defines the **contract** — a promise that says "anything claiming to be a search provider must have a `.search(query)` method." This file contains no real logic — just the shape of the promise.
- `_providers/vertex_search.py` is the **provider** — the actual class that fulfills that promise, using Vertex AI Search specifically.

**Why bother?** If we ever swapped Vertex AI Search for a different tool, only the provider file would need to change — nothing else in the codebase would need to know or care, because everything else only ever talks to the _contract_, never the specific implementation. This is the same idea as a wall socket: any lamp that has the right plug shape works, without the wall needing to know or care which lamp brand you bought.

### `config.py` — one door for secrets

```python
load_dotenv()
```

This line reads a `.env` file (a plain text file with `KEY=VALUE` lines) and quietly copies those values into the program's environment — as if you'd typed them into your terminal yourself. We keep `.env` out of git (via `.gitignore`) since it holds project-specific values we don't want committed.

**Why only one file is allowed to read environment variables:** it means every other part of the code just receives plain, explicit arguments (like `project_id: str`) — easier to test, easier to reason about, and there's exactly one place to look if a config value is ever wrong.

### `_providers/vertex_search.py` — talking to Google

```python
self._serving_config = (
    f"projects/{project_id}/locations/{location}/collections/"
    f"default_collection/engines/{engine_id}/servingConfigs/default_search"
)
```

Every resource in Google Cloud has a unique "full address," similar to a file path on your computer (`C:\Users\You\Documents\file.txt`) but for cloud resources. This string is that full address for our specific Search app — it says, in order: which project, which region, which "collection" (an organizational grouping Google uses internally), which specific app, and which serving configuration (a named setting profile — we use the default one).

```python
self._client = discoveryengine.SearchServiceClient()
```

This creates a "telephone" object — something that knows how to correctly dial and speak Google's API language. It automatically uses whatever login credentials are active (from `gcloud auth application-default login`).

```python
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
```

This builds the actual question we're asking and sends it. `summary_result_count=5` means "consider up to 5 matching passages when writing your answer." `include_citations=True` is what produces those `[1]`, `[2]` markers pointing back to source documents. `response.summary.summary_text` pulls out just the final written answer from a much larger response object (which also contains raw matched documents, relevance scores, etc. — we just don't need those for our use case).

**A lesson learned:** we initially hand-built the `serving_config` string. We later checked whether the Google SDK provides a built-in helper for this (`serving_config_path()`) — it does, but only for a slightly different resource shape (data stores, not search "engines"/apps). Lesson: SDK helper methods don't always cover every possible resource shape an API supports — sometimes building the string yourself, carefully, is the correct approach, not a shortcut.

### `_prompts.py` — teaching the agent how to behave

This file holds one big string of plain English instructions — the agent's "personality and rules." Kept separate from code because you'll likely tweak the _wording_ often, without needing to touch any logic.

### `agent.py` — wiring it all together

```python
def search_regulations(query: str) -> str:
    """Search Canadian banking regulatory guidelines for relevant guidance.
    ...
    """
    return _search_provider.search(query)
```

This is a completely normal Python function — nothing magical. What makes it usable by an AI agent is its **docstring** (the text in triple quotes). The agent-building framework (**ADK**, Google's Agent Development Kit) reads that docstring to understand _when_ it should call this function and _what_ to pass it — so writing a clear, accurate docstring isn't just good practice here, it directly shapes how well the AI understands its own tool.

```python
root_agent = Agent(
    name="compliance_self_audit_agent",
    model=_config.model_name,
    instruction=SYSTEM_INSTRUCTION,
    tools=[search_regulations],
)
```

This creates the actual agent: which AI model powers its thinking (`gemini-2.5-flash`), what its personality/rules are, and which tools (functions) it's allowed to call. `root_agent` is a special name ADK looks for automatically — like how a returnable value in some languages must be named a specific thing by convention.

---

## Part 5: Deploying to the Cloud (and everything that went wrong)

This part had the most learning value, because things broke in instructive ways. We're documenting the failures on purpose — future you (or a teammate) will hit the same walls otherwise.

### The deploy script's key parts

```python
vertexai.init(
    project=config.project_id,
    location=config.agent_location,
    staging_bucket=f"gs://{config.project_id}-agent-staging",
)
```

`vertexai.init()` sets up the "default settings" for every Vertex AI call that follows in this script. `staging_bucket` is a temporary parking spot Google needs — before your agent becomes a live cloud service, your code first has to be zipped up and uploaded somewhere, and that "somewhere" is this bucket.

```python
os.chdir(Path(__file__).resolve().parent.parent / "src")

remote_agent = agent_engines.create(
    agent_engine=root_agent,
    requirements=[...],
    extra_packages=["compliance_agent"],
    env_vars={...},
    display_name="compliance-self-audit-agent",
)
```

- `agent_engine=root_agent` — the actual agent object to deploy.
- `requirements=[...]` — a list of _public_ packages (things installable from PyPI, the public Python package library) that the remote environment needs installed.
- `extra_packages=["compliance_agent"]` — this is for **our own private code**, which isn't published anywhere public. It tells Google "also bundle up this folder and install it too."
- `env_vars={...}` — since the deployed agent runs in a totally separate environment with no access to our local `.env` file, we have to explicitly pass the configuration values it needs.
- `os.chdir(...)` — changes "where we are" before running the deploy command, so that `extra_packages=["compliance_agent"]` refers to the _top level_ of our package folder, not a nested `src/compliance_agent` path. (See the bug story below — this single line fixed a repeated failure.)

### Bug #1: "No module named 'compliance_agent'"

**What happened:** Even after fixing our local Python packaging (`pyproject.toml`), the _deployed_ agent still failed with this error.

**Why:** `extra_packages=["src/compliance_agent"]` uploaded our code nested inside a `src/` folder. But locally, our editable install (`uv pip install -e .`) treats `src/` as invisible — Python just sees `compliance_agent` sitting at the top. So the deployed bundle's folder structure didn't match what our already-pickled agent object expected to find. **Fix:** change into the `src/` directory _before_ calling `extra_packages=["compliance_agent"]`, so the path is relative to the right starting point, and the folder structure matches.

**Lesson:** `extra_packages` paths are relative to your current working directory at the moment you run the deploy script — not relative to the script's own file location.

### Bug #2: "Please provide a `staging_bucket`"

Simple one — we hadn't set `staging_bucket` in `vertexai.init()` at all yet. Some Google Cloud SDK features require this explicitly; there's no fallback default.

### Bug #3: Missing environment variables

Even after fixing the module error, the deployed agent's own log said it needed `SEARCH_LOCATION`, `AGENT_LOCATION`, etc. — because our `config.py`'s `load_config()` function checks for those at the moment the module loads, and the deployed environment has no `.env` file. **Fix:** explicitly pass those values via `env_vars={...}` in the deploy call. One exception: `GOOGLE_CLOUD_PROJECT` is _reserved_ by Agent Engine itself — it auto-injects that one, so you're not even allowed to set it yourself.

### Bug #4: `403 Permission Denied` on search

This was the trickiest one, and the best IAM lesson in the whole project.

**What happened:** the deployed agent could run and even correctly decide to call the search tool — but Google refused the request with a permissions error.

**Why:** locally, your Python code runs _as you_ — your own Google account, with all your own permissions. But once deployed, the agent runs as a **service account** (remember: an ID badge for robots, not people) — and by default, that badge starts with almost no permissions at all. It's not "inheriting" your personal permissions just because you're the one who deployed it.

**Finding the right badge:** this took two tries.

1. We first guessed it was the "Compute Engine default service account" (a general-purpose badge many Google services use by default) and granted it access. Still failed.
2. We then discovered Agent Engine actually has its _own_, more specific badge — a "Reasoning Engine Service Agent" — purpose-built for exactly this kind of deployed-agent scenario. _That_ was the badge actually making the search request.

**The fix:**

```bash
gcloud projects add-iam-policy-binding <YOUR_PROJECT_ID> \
  --member="serviceAccount:service-<YOUR_PROJECT_NUMBER>@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
  --role="roles/discoveryengine.viewer"
```

- `add-iam-policy-binding` — "attach this permission to this badge, on this project."
- `--member=` — _which_ badge (service account) is receiving the permission.
- `--role=` — _what_ permission it's receiving. `roles/discoveryengine.viewer` is a pre-built bundle of permissions Google defines, covering "can search and read from Discovery Engine (Vertex AI Search) resources" — without granting the ability to _edit or delete_ the search app itself. This follows a security principle called **least privilege**: only grant the minimum access actually needed, nothing more, so if something ever goes wrong, the damage is limited.

**One more twist:** even after granting the correct permission, it still failed for several more minutes. This turned out to be **IAM propagation delay** — permission changes at Google Cloud's scale don't take effect literally instantly across every server; there's a short real-world delay (a few minutes, sometimes longer) before the new permission is recognized everywhere. Patience, not more debugging, was the actual fix.

**How we found the right badge to fix, methodically:** rather than guessing, we ran:

```bash
gcloud projects get-iam-policy <YOUR_PROJECT_ID> \
  --flatten="bindings[].members" \
  --filter="bindings.members~aiplatform" \
  --format="table(bindings.members, bindings.role)"
```

This lists every AI-Platform-related service account already known to your project, along with their current roles — a good general technique for "who already exists and what can they do" whenever you're unsure which identity is actually responsible for a failing action.

**How we read the actual error, not just the summary:** the top-level error Google gives you (`"failed to start and cannot serve traffic"`) is deliberately vague. The _real_ reason always lives in **Cloud Logging**:

```bash
gcloud logging read "resource.labels.reasoning_engine_id=<YOUR_ID>" \
  --project=<YOUR_PROJECT_ID> \
  --limit=50 \
  --format=json
```

This pulls the actual stderr/stdout output from inside the failed deployment — the real Python tracebacks, not just a generic wrapper message. Whenever a cloud deployment fails with a vague error, checking the logs directly (rather than re-reading the vague error over and over) is almost always the fastest path to the real cause.

---

## Part 6: Verifying It Actually Works, Remotely

```python
import vertexai
from vertexai import agent_engines

vertexai.init(project="<YOUR_PROJECT_ID>", location="us-central1")

agent_engine = agent_engines.get(
    "projects/<YOUR_PROJECT_NUMBER>/locations/us-central1/reasoningEngines/<YOUR_REASONING_ENGINE_ID>"
)

for event in agent_engine.stream_query(
    user_id="test-user",
    message="What are the technology risk governance requirements for a new digital banking feature?",
):
    print(event)
```

- `agent_engines.get(...)` — fetches a _reference_ to your already-deployed agent, using its unique resource name (the long `projects/.../reasoningEngines/...` string Google gave us when deployment succeeded).
- `stream_query(...)` — actually sends it a question and streams back a sequence of **events** as the agent works — you can see it decide to call the search tool, receive the tool's result, and then compose its final written answer, step by step, rather than waiting silently for one final blob.

This confirms the deployed agent works completely independently of your own laptop — it's a real, live, callable service.

---

## What We Could Do Next (Ideas, Not Yet Built)

- **A proper web front end**, so the VP sees a clean chat interface instead of raw Python event objects — planned to run on **Cloud Run**, a separate Google service for hosting web apps/APIs.
- **Automated document ingestion** (a scheduled job that re-checks regulator websites for updates), instead of manually downloading PDFs.
- **Document versioning**, so answers can say not just "per OSFI B-13" but "per the version effective January 2024," in case guidelines get updated later.
- **Tighter IAM scoping** — right now we granted `discoveryengine.viewer` at the whole-project level; a more advanced setup could scope it down to just the one specific Search app.
- **Automated tests**, so future code changes can be checked automatically rather than manually re-running scripts each time.

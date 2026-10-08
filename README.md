# Compliance Self-Audit Agent — How We Built This (Beginner's Guide)

This README explains, from the ground up, everything we built and _why_. If you've never touched Google Cloud before, this should still make sense — we explain every concept before using it.

## What This Project Does

Imagine you're building a new feature for a bank — say, a way for customers to send money to each other from their phones. Before you launch it, a compliance team needs to check it against a pile of government rules (from OSFI, Canada's bank regulator, and others). That review usually happens _late_, after the feature is mostly built.

This project builds an AI "assistant" that engineers can ask _early_ — "does my feature idea have any obvious compliance problems?" — before the official review even starts. Think of it as a spell-checker, but for regulations instead of grammar.

To do that, the assistant needs to:

1. **Read** a pile of real regulatory documents (PDFs)
2. **Search** through them intelligently when asked a question — and also search the web for anything newer than the PDFs
3. **Reason** about what it found and write a structured report: applicable guidelines, potential gaps, recommendations and open questions, with every claim tied to a listed source
4. **Hold a conversation**, so engineers can follow up ("how do we fix these gaps?") without starting over
5. **Live somewhere** so anyone can ask it questions, not just your own laptop

Each of these maps to a piece of Google Cloud or of the agent code, which we'll walk through.

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

We'll come back to this in detail in Part 6, because it caused us real trouble during deployment — a good learning moment.

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

### The big picture: a team of agents, not one

The first version of this project was a single agent with one tool. It worked, but answers took one fixed shape and could only see the PDFs. The current version is a small **team of agents**, each with one job, wired together with ADK (Google's **Agent Development Kit**):

```
user message
   │
   ▼
compliance_assistant (the "front desk")
   │  ├─ follow-up question?  → answers directly (may do one quick PDF lookup)
   │  └─ new feature / PRD?   → hands off to the audit pipeline ↓
   ▼
audit_pipeline (runs its steps in order)
   ├─ research (runs its members at the same time)
   │    ├─ pdf_researcher  → searches our PDFs (Vertex AI Search)
   │    └─ web_researcher  → searches the web (Google Search)
   └─ report_writer        → turns both sets of findings into the final report
```

Three ADK building blocks make this possible:

- **`Agent` (an "LLM agent")** — one Gemini-powered worker with its own instructions and tools.
- **`ParallelAgent`** — runs its members _at the same time_. The two researchers don't depend on each other, so there's no reason to make one wait for the other.
- **`SequentialAgent`** — runs its members _in order_. The report writer must wait until research is finished.

**Why a "front desk" agent?** People go back and forth. "How do we fix these gaps?" or "rewrite FR-04 for me" shouldn't trigger two searches and a brand-new seven-section report. The front desk runs the full pipeline only for something new to audit, and answers everything else itself, in whatever shape fits the question.

**How does the next message get back to the front desk?** ADK decides who answers each new message by looking at who spoke last. If that was an agent _inside_ a `SequentialAgent` or `ParallelAgent`, ADK can't hand control back to it (those wrappers can't "transfer"), so it falls back to the top-level agent. That's exactly what we want: every new message starts at the front desk.

### How the code is organized

```
src/compliance_agent/
├── agent.py                  # wires the team together; defines root_agent
├── sub_agents/
│   ├── pdf_researcher.py     # search_regulations tool + the PDF researcher
│   ├── web_researcher.py     # Google Search researcher
│   └── report_writer.py      # writes the final report
├── _contracts/search.py      # the "promise" a search backend must keep
├── _providers/vertex_search.py  # the Vertex AI Search implementation
├── _callbacks.py             # hooks that run after each model reply
├── _sources.py               # tracks which sources were used; renders the sources table
├── _report.py                # the report's structure, and turning it into markdown
├── _prompts.py               # every agent's instructions (plain English)
└── config.py                 # the only file that reads environment variables
```

Files starting with `_` are internal helpers; the rest is the agent itself.

### Why we organized the search code this way

We used a **Protocol + Provider** pattern. In plain terms: we separated "_what_ the search feature needs to do" from "_how_ it's actually done today."

- `_contracts/search.py` defines the **contract** — a promise that says "anything claiming to be a search provider must have a `.search(query)` method that returns an answer plus the documents it came from." No real logic lives here — just the shape of the promise.
- `_providers/vertex_search.py` is the **provider** — the actual class that fulfills that promise, using Vertex AI Search specifically.

**Why bother?** If we ever swapped Vertex AI Search for a different tool, only the provider file would need to change. This is the same idea as a wall socket: any lamp with the right plug works, without the wall caring which brand you bought.

### `config.py` — one door for secrets

```python
load_dotenv()
```

This line reads a `.env` file (a plain text file with `KEY=VALUE` lines) and quietly copies those values into the program's environment — as if you'd typed them into your terminal yourself. We keep `.env` out of git (via `.gitignore`) since it holds project-specific values we don't want committed.

**Why only one file is allowed to read environment variables:** every other part of the code just receives plain, explicit values (like `project_id: str`) — easier to test, easier to reason about, and there's exactly one place to look if a config value is ever wrong.

### `_providers/vertex_search.py` — talking to Google

```python
self._serving_config = (
    f"projects/{project_id}/locations/{location}/collections/"
    f"default_collection/engines/{engine_id}/servingConfigs/default_search"
)
```

Every resource in Google Cloud has a unique "full address," similar to a file path on your computer but for cloud resources. This string is that address for our Search app: which project, which region, which "collection" (an internal grouping), which app, and which serving configuration (a named settings profile — we use the default).

```python
request = discoveryengine.SearchRequest(
    serving_config=self._serving_config,
    query=query,
    content_search_spec=...SummarySpec(summary_result_count=5, include_citations=True),
)
response = self._client.search(request)
```

This sends the question and asks Vertex AI Search to also _write a short summary_ of the top 5 matches, with `[1]`, `[2]` citation markers. The provider then returns two things: the summary text, and the **file names** of the cited PDFs (e.g. `B-13-technology-cyber-risk.pdf`) — those end up in the report's sources table.

**A quirk worth knowing:** the summary's citation list tells you _which document_ was cited, but not its file location. The location lives on the separate search results, and the two use slightly different IDs (the citation points at a _chunk_ — `.../documents/<id>/chunks/c4` — while the result points at the whole document). The provider trims off the `/chunks/...` part to match them up.

**A lesson learned:** we initially hand-built the `serving_config` string, then checked whether the SDK has a helper (`serving_config_path()`). It does, but only for a slightly different resource shape (data stores, not search "apps"). SDK helpers don't always cover every shape an API supports — sometimes building the string yourself, carefully, is the right approach.

### The agents, one by one

**`pdf_researcher`** has one tool, `search_regulations`. Gemini decides on up to 4 focused searches ("biometric consent", "MFA requirements", …) and fires them **all at once**. It then writes its findings as bullet points.

**`web_researcher`** has one tool, Google's built-in `google_search`, to catch guidance newer than our PDFs. It prefers official regulator sites but may also use reputable secondary sources. (Gemini doesn't allow a built-in tool like Google Search in the same agent as our own function tools — another reason each researcher gets exactly one tool.)

**`report_writer`** has no tools. It reads both researchers' findings and writes the final report.

What makes a plain Python function usable as a tool is its **docstring** (the text in triple quotes). ADK reads it to understand _when_ to call the function and _what_ to pass — so a clear docstring directly shapes how well the AI uses its tool.

### Session state — the team's shared whiteboard

Agents in a pipeline don't call each other. Instead, ADK gives each conversation a **session state**: a shared dictionary every agent can read and write. Think of it as a whiteboard in the team room:

- each researcher writes its findings under its own key (`temp:findings:pdf`, `temp:findings:web`);
- every search writes down which sources it used (`temp:sources:...`);
- the report writer reads all of it before it starts.

Keys starting with `temp:` are wiped after every message, so each new question starts with a clean whiteboard.

**Why a separate key per search?** The two researchers write _at the same time_. If they both appended to one shared list, ADK would merge their updates key-by-key and one researcher's sources would silently overwrite the other's.

### Callbacks — hooks that run after each model reply (`_callbacks.py`)

A **callback** is a function ADK calls at a fixed moment — here, right after a model replies, before anyone else sees the reply. We use two:

1. **On each researcher:** save the findings to the whiteboard, then _remove the text from the reply_. Otherwise the researchers' raw notes would flash up in the chat before the report. For web searches, it also keeps only sentences that Google actually linked to a web page, each labelled with its domain and whether that site is an official regulator.
2. **On the report writer:** turn the report into markdown and attach the sources table.

### The report: structured data, rendered by code (`_report.py`)

The report writer doesn't write markdown. It fills in a **form** — a summary, a list of guideline rows, a list of gap rows, recommendations, open questions — and returns it as JSON (ADK's `output_schema` feature). Code then turns that into markdown tables.

**Why?** Gemini repeatedly broke while writing markdown tables itself: once it "padded" a table row to over 100,000 characters until it hit its length limit, cutting the report off. If the model never writes table syntax, it can't break a table.

Code also enforces two rules the model can't break:

- **No source, no row.** Every guideline and gap must cite a numbered source; rows without one are dropped.
- **Citations to non-official websites are marked `†`**, e.g. `[1][7†]`.

The **Sources Consulted** section is three tables, numbered continuously: internal documents (our PDFs), official regulator websites, and other web sources (marked as not authoritative).

### `_prompts.py` — teaching each agent how to behave

Every agent's instructions are plain English strings in one file. Kept separate from code because you'll likely tweak the _wording_ often without touching any logic.

### Lessons learned while building the pipeline

- **Callback parameter names matter.** ADK calls callbacks with _keyword_ arguments (`callback_context=`, `llm_response=`), so a parameter named anything else crashes.
- **An empty reply is an error to ADK.** When the researcher callback removes all the text, ADK (in non-streaming mode) flags a reply that finished with no content as `MODEL_RETURNED_NO_CONTENT`. The callback also clears the "finish reason" so ADK quietly skips the empty reply instead.
- **"Parallel" tool calls weren't parallel.** ADK runs ordinary (synchronous) Python tools directly on its event loop, so five searches ran one after another — and froze the other researcher meanwhile. Making `search_regulations` `async` and running the blocking Google call in a background thread (`asyncio.to_thread`) took five searches from ~6.7s to ~1.9s.
- **Uncapped "thinking" is slow.** Gemini 2.5 Flash thinks before answering, with no limit by default; one web search turn varied from 10 seconds to 3 minutes. Capping the thinking budget made it consistently fast.
- **Telling Gemini which sites to search isn't a guarantee.** It writes its own Google queries and often ignores `site:` hints. That's why "official vs other" is decided in _code_ from each page's domain, not left to the prompt.
- **A failed search shouldn't sink the whole audit.** A tool that raises an error aborts the entire run. `search_regulations` retries quota errors and otherwise returns a "search unavailable" message so the report can still be written from what was found.

---

## Part 5: Testing Locally

Two ways to try the agent on your own machine before deploying:

**1. The ADK web UI** — a chat window in your browser, plus an Events view showing every agent step, tool call and timing:

```bash
uv run adk web --port 8000 src
```

Then open http://127.0.0.1:8000 and pick `compliance_agent`. Start a **new session** after changing code, so old replies don't confuse the test.

**2. The end-to-end script** — a repeatable three-message conversation (an audit, a "fix the gaps" follow-up, and a regulatory lookup follow-up), streamed the same way a web front end receives it:

```bash
uv run python scripts/test_local_pipeline.py
```

It prints which agent produced each step, so you can check the routing: the first message should go through the full pipeline and end with the sources table; the follow-ups should be answered directly by `compliance_assistant`.

**Watch the search quota.** Each PDF search asks Vertex AI Search for a generated summary, and the default quota for those is **10 per minute per project** (`discoveryengine.googleapis.com/llm_requests`). One audit uses up to 4, so a few audits in quick succession can hit `429 Quota exceeded`. The agent retries briefly and carries on, but reports get thinner. To see or raise the limit: Google Cloud console → **IAM & Admin → Quotas**, filtered to "Discovery Engine API".

---

## Part 6: Deploying to the Cloud (and everything that went wrong)

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

### Bug #5 (avoided): the deploy can't "pickle" a network connection

Deploying works by **pickling** `root_agent` — freezing the Python object into bytes, uploading them, and thawing them in the cloud. A live network connection (like the gRPC client inside our search provider) can't be frozen. Functions defined at the top level of a module are pickled as just a _reference_ ("re-import `search_regulations` from `compliance_agent.sub_agents.pdf_researcher`"), so the cloud side builds its own fresh connection. A function nested _inside_ another function would drag the live connection along and the deploy would fail.

**Rule:** define every tool as a plain top-level function, never as a nested function. You can check before deploying:

```bash
uv run python -c "import cloudpickle; from compliance_agent.agent import root_agent; cloudpickle.dumps(root_agent); print('ok')"
```

---

## Part 7: Verifying It Actually Works, Remotely

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

- **A dedicated search index of regulator websites** (a Vertex AI Search "website" data store over OSFI, FCAC, OPC, FINTRAC, etc.). Every web result would be official by construction, with real page titles and direct links. Costs about $4 per 1,000 searches after a free trial; crawling and storage for basic website indexing are free.
- **Lift the search-summary quota** — either request a higher `llm_requests` quota, or stop asking Vertex AI Search for summaries (use the plain 300-per-minute search quota and let the researcher summarize).
- **Automated document ingestion** (a scheduled job that re-checks regulator websites for updates), instead of manually downloading PDFs.
- **Document versioning**, so answers can say not just "per OSFI B-13" but "per the version effective January 2024."
- **Tighter IAM scoping** — we granted `discoveryengine.viewer` at the whole-project level; a more advanced setup could scope it down to just the one Search app.
- **Automated tests** that check report structure and routing on every change, instead of running `scripts/test_local_pipeline.py` by hand.

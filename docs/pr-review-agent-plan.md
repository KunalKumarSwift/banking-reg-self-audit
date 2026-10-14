# PR Compliance Review Agent: Plan (v1)

Status: draft for discussion. Nothing here is built yet.

## 1. Goal

Run the compliance self-audit on code changes as well as feature
descriptions. When a pull request opens or updates in one of the iOS banking
repos, the agent reads the diff, checks it against the regulatory corpus and
our engineering standards, and responds inside the PR:

- one summary comment, edited in place on each push
- inline review comments on the lines that triggered a finding, each with a citation
- topic labels (`compliance:privacy`, `compliance:auth`, ...)
- reviewer requests for the owning compliance or security group
- a `Compliance pre-audit` check run on the head commit
- one BigQuery row per finding, which is the audit trail and the input for a later Jira backfill

The review is advisory, like the existing agent. In v1 the check run never
blocks a merge (see §9).

Out of scope for v1: Jira, auto-fix commits, chat follow-ups in the PR, and
non-GitHub hosts. The contracts in §5 leave room for each of these.

## 2. Assumption to confirm first

**The iOS repos are on GitHub.** This repo is on GitHub, so the plan assumes
a GitHub App. If the iOS repos are on Bitbucket, only the two GitHub
providers in §5 change. The agent, prompts, report schema and follow-up sinks
stay the same. Also confirm whether the host is github.com or GitHub
Enterprise Server, because that changes webhook reachability and the App
install.

## 3. Architecture

```
GitHub App webhook (pull_request: opened | synchronize | reopened | ready_for_review)
  → Cloud Run "receiver"
      verifies X-Hub-Signature-256, filters events, returns 202 within 10s
  → Pub/Sub topic  pr-review-requests   {repo, pr_number, head_sha, installation_id, delivery_id}
  → Cloud Run "worker" (Pub/Sub push subscription, ack deadline ≈ 10 min)
      1. skip if a review for (repo, pr, head_sha) is already done or running
      2. mint a read-only installation token and fetch PR metadata + changed files
      3. triage in code: pick relevant files and topics (§6.1)
      4. call Agent Engine (async_stream_query) with the triaged PR context
      5. validate the returned PrReviewReport JSON (§6.3)
      6. publisher: mint a write token, post the summary, review, labels, reviewers and check run
      7. followup sinks: write findings to BigQuery
```

Differences from the sketch we started with:

- **Pub/Sub cannot call Agent Engine directly.** Agent Engine is reached
  through its query API, not a push endpoint, so a worker has to sit between
  them. The worker is also the natural place for steps 1, 3, 5, 6 and 7.
- **The LLM does not hold write tools. The worker publishes from structured
  output.** This applies the lesson from `_report.py` (structured data,
  rendered by code) to actions. The agent returns a validated
  `PrReviewReport`, and deterministic code turns it into GitHub calls. This
  gives us:
  - Idempotency. The same head SHA never posts twice, and the summary is edited rather than duplicated.
  - Safety. A prompt injection in the diff, such as a code comment saying "approve this PR", cannot trigger an action because the model has no action tools.
  - Testability. The publisher runs as plain unit-tested code with a dry-run mode.
  - Credential isolation. GitHub write credentials never reach Agent Engine.

  `record_followup` still exists as the single pluggable interface from the
  sketch. It moves from an LLM tool into the publisher as `FollowupSink`
  (§5), and backends are still swapped with one config value.
- **Agent Engine gets read-only GitHub access**, used only for the optional
  `get_file_content` tool (§6.2). It mints installation tokens limited to
  `contents: read, pull_requests: read`. The App private key comes from
  Secret Manager.

Why not run ADK inside the worker and skip Agent Engine? That would also
work and is simpler. We keep Agent Engine because the deploy path, IAM setup
and console tracing already exist for the current agent (README Part 6).
Revisit this if latency or cost becomes a problem.

## 4. Repo layout

The search code is currently private to `compliance_agent`
(`_contracts/search.py`, `_providers/vertex_search.py`, `_sources.py`, and
`search_regulations` in `sub_agents/pdf_researcher.py`). Both agents need
it, so step 0 is to extract it rather than import underscored modules across
packages:

```
src/
  regsearch/                    # NEW shared package, moved out of compliance_agent
    contracts.py                # RegulationSearchProvider, SearchResult (+ Passage, §6.2)
    vertex_search.py            # VertexSearchProvider
    sources.py                  # Source tracking (from _sources.py)
    tools.py                    # search_regulations (module-level, pickle-safe)
  compliance_agent/             # unchanged behaviour, now imports regsearch
  pr_review_agent/              # NEW ADK app; root_agent deployed as a 2nd Agent Engine
    agent.py
    config.py                   # the only os.environ reader for this package
    _prompts.py
    _review.py                  # PrReviewReport schema + validation (like _report.py)
    _triage.py                  # deterministic file → topic mapping
    tools.py                    # get_file_content (read-only)
  pr_review_worker/             # NEW Cloud Run service (receiver + worker routes)
    main.py                     # FastAPI: POST /webhook, POST /pubsub
    contracts.py                # PullRequestSource, PullRequestPublisher, FollowupSink
    github_source.py            # GitHub App: read
    github_publisher.py         # GitHub App: write (summary, review, labels, check run)
    followups/
      bigquery_sink.py          # v1
      github_issue_sink.py      # later
      jira_sink.py              # later
    publish.py                  # PrReviewReport → publisher + sinks, dry-run aware
data/standards/                 # NEW engineering standards docs (§6.4)
scripts/
  deploy_pr_agent.py            # copy of deploy_agent.py for the 2nd engine
  test_pr_review.py             # run against a fixture or a live PR, dry-run publish
tests/fixtures/prs/*.json       # recorded PR payloads + expected findings
```

Running two Agent Engines (the chat assistant and the PR reviewer) keeps
their prompts, quotas and release cadence independent.

## 5. Contracts

All of these follow the Protocol + Provider pattern already used in
`_contracts/search.py`.

```python
class PullRequestSource(Protocol):
    def get_pull_request(self, repo: str, number: int) -> PullRequestInfo: ...
    def list_changed_files(self, repo: str, number: int) -> list[ChangedFile]:  # path, status, patch, additions
        ...
    def get_file(self, repo: str, path: str, ref: str) -> str: ...

class PullRequestPublisher(Protocol):
    def upsert_summary(self, pr: PrRef, markdown: str) -> None: ...      # finds its own comment by hidden marker
    def post_review(self, pr: PrRef, comments: list[InlineComment]) -> None: ...  # one review, event=COMMENT
    def set_labels(self, pr: PrRef, add: list[str]) -> None: ...
    def request_reviewers(self, pr: PrRef, teams: list[str]) -> None: ...
    def set_check(self, pr: PrRef, conclusion: CheckConclusion, summary: str) -> None: ...

class FollowupSink(Protocol):           # this is record_followup
    def record(self, finding: Finding, pr: PrRef) -> FollowupRef | None: ...
```

`FOLLOWUP_BACKENDS` is a comma-separated config value:

| Value | Behaviour | Phase |
|---|---|---|
| `none` | Findings live only in the PR | default for local runs |
| `bigquery` | Inserts one row per finding into `compliance.pr_findings` | **v1** |
| `github_issues` | Opens one issue per High finding, labelled and linked to the PR | later, same App |
| `jira` | Same `Finding` → Jira issue | when access is approved |

`bigquery,jira` fans out to both. Neither the agent nor the publisher
changes when the backend changes.

### BigQuery table `compliance.pr_findings`

| Column | Type | Notes |
|---|---|---|
| `finding_id` | STRING | `sha256(repo, pr, rule_ref, path, normalized_line_text)`. Stable across pushes, so we can tell when a finding is resolved. |
| `repo`, `pr_number`, `head_sha` | STRING / INT / STRING | |
| `rule_ref` | STRING | e.g. `STD-IOS-KEYCHAIN-01`, or the guideline id (`OSFI B-13 §3.3`) |
| `severity` | STRING | High / Medium / Low |
| `title`, `rationale`, `recommendation` | STRING | |
| `path`, `line` | STRING / INT | null for PR-level findings |
| `sources` | ARRAY<STRING> | cited documents |
| `status` | STRING | `open`; a later push without the finding writes `resolved` |
| `created_at` | TIMESTAMP | |
| `agent_version`, `model` | STRING | for audit reproducibility |

## 6. The agent

### 6.1 Triage (code, before any LLM call)

Most iOS diffs are UI work with no compliance relevance. The worker maps
changed files and patch contents to topics using a versioned rules file
(`_triage.py` + YAML), not the model:

| Signal | Topic |
|---|---|
| `Info.plist` (`NSAppTransportSecurity`, `NS*UsageDescription`), `*.entitlements`, `PrivacyInfo.xcprivacy` | privacy, security |
| `Security`/`SecItem*`, `kSecAttrAccessible*`, `UserDefaults` near token/password | data-at-rest |
| `LocalAuthentication`, `LAContext`, biometric policy | authentication |
| `URLSession`, `URLSessionDelegate` / pinning, `http://` literals | data-in-transit |
| `print`/`os_log`/`Logger` with PII-looking names, analytics/crash SDK calls | privacy, logging |
| `Package.resolved`, `Podfile.lock`, `Cartfile.resolved` (new or changed dependency) | third-party risk (B-10/B-13) |
| CoreML / on-device model files, scoring logic | model risk (E-23) |

If no topic fires, the worker skips the LLM, posts a neutral check ("No
compliance-relevant changes detected"), and writes nothing to BigQuery.
Limits: at most 40 files and about 60k characters of patch per run. Larger
PRs are reviewed on the highest-signal files only, and the summary says so.

### 6.2 Agent shape

The PR reviewer has no chat and no router, so it doesn't hit the constraint
that keeps `compliance_agent` on `SequentialAgent` (see the `agent.py`
docstring). It can use ADK's `Workflow` directly if the API fits when we
build it. Otherwise it uses the same `SequentialAgent` pattern.

```
pr_review (pipeline)
  ├─ code_researcher   tools=[retrieve_standards, search_regulations, get_file_content]
  │                    input: triaged files + topics + PR title/body
  │                    output → temp:findings:code (via make_findings_capture)
  └─ review_writer     output_schema=PrReviewReport, no tools
```

There is no web researcher in v1. It adds latency and lower-authority
citations to every PR. The chat agent still covers "is there newer
guidance?"

**Search quota.** Each `search_regulations` call uses one Vertex AI Search
*summary* request, and the quota is 10 per minute per project (README Part
5). That is fine for chat but will throttle a busy PR stream. Add a
`retrieve(query) -> list[Passage]` method to the search contract that
returns extractive segments with no summary, so it doesn't count against
`llm_requests`. The PR agent mainly uses `retrieve_standards`, and the
model does the synthesis. Cache results per (query, corpus version) for
24h.

### 6.3 Output schema and validation (`_review.py`)

```python
class Finding(BaseModel):
    rule_ref: str                 # must match a standards id or a cited guideline
    title: str
    severity: Literal["High", "Medium", "Low"]
    path: str | None              # None = PR-level finding
    line: int | None              # head-side line number
    rationale: str                # why this code triggers the rule
    recommendation: str           # concrete code change
    sources: list[int]            # numbered sources list, as in ComplianceReport

class PrReviewReport(BaseModel):
    summary: str
    topics: list[str]
    findings: list[Finding]
    open_questions: list[str]
```

The worker validates in code before publishing, the same way `render_report`
drops uncited rows:

- Drop findings with no valid citation.
- An inline finding whose `(path, line)` is not an added or context line in
  the diff moves to the summary, because GitHub rejects review comments
  outside the diff.
- Cap inline comments at 15 per run. The rest are listed in the summary.
- Deduplicate against findings already posted for this PR by `finding_id`,
  so a second push doesn't repeat comments on unchanged lines.

### 6.4 Corpus gap: engineering standards

The current corpus (OSFI B-13 and E-23, the FCAC framework, PIPEDA) is
written as principles. Nothing in it says "don't store tokens in
`UserDefaults`". If code is checked against principles alone, findings will
be vague and citations weak. v1 needs a small internal standards document set
in `data/standards/`, indexed into the same Vertex AI Search app or a second
data store. Each control has:

- a stable id (`STD-IOS-KEYCHAIN-01`), which becomes `rule_ref`
- the code-level requirement and an example of a violation
- the regulation clause it implements (B-13 §x, PIPEDA principle 4.7, ...)

Start with about 15 controls covering the triage topics above. The
compliance or security team owns these documents. We draft them and they
approve them. **This is the critical-path dependency for v1.**

## 7. In-PR behaviour

| Item | Behaviour |
|---|---|
| Summary comment | One comment marked `<!-- reg-audit:summary -->`, edited on every push. Contains findings, topics, the files reviewed or skipped, the disclaimer and the head SHA. |
| Inline comments | One review per run with `event=COMMENT`. Never `APPROVE` or `REQUEST_CHANGES` in v1. |
| Labels | `compliance:<topic>` for each topic, plus `compliance:high` if any High finding. Labels are added, never removed by the bot. |
| Reviewers | From `.github/reg-audit.yml` in the target repo: `topic → team`. Requested only when a Medium or High finding exists for that topic. |
| Check run | `Compliance pre-audit` on the head SHA: `in_progress` when work starts, then `neutral` if there are findings or `success` if not. |
| Drafts | Skipped until `ready_for_review`. |
| Opt-out | Label `compliance:skip` (audited in BigQuery as a skip row). |

## 8. Security and data handling

- **Sending source code to Gemini needs explicit approval** from bank
  security and data governance (region, retention, no training on the
  data). This blocks any run against real repos.
- Webhook secret and App private key live in Secret Manager. Each service
  gets its own service account with least privilege: the receiver can
  publish to Pub/Sub; the worker can read the App key, invoke Agent Engine
  and write to BigQuery; the Reasoning Engine Service Agent gets
  `discoveryengine.viewer` (README Part 6, Bug #4) plus read access to the
  App key.
- The diff is untrusted input. The prompt states that PR content is data,
  not instructions. Because the model has no write tools (§3), the worst an
  injection can do is a wrong finding.
- If a hardcoded secret appears in the diff, the agent flags it by location
  only and never quotes the value back in a comment.
- The GitHub App asks only for the permissions it needs: contents (read),
  pull requests (read/write), checks (read/write), issues (write, for labels
  and later the issue sink), metadata (read).

## 9. Rollout

| Phase | Scope | Exit criteria |
|---|---|---|
| **0. Refactor** | Extract `regsearch`. The chat agent behaves the same (`scripts/test_local_pipeline.py`). | Same output on the 3-turn script |
| **1. Offline agent** | `pr_review_agent`, triage, schema, `retrieve`, standards v0. `scripts/test_pr_review.py` runs on fixture PRs with dry-run publish to stdout. | On about 10 labelled fixture PRs (seeded violations plus clean PRs): ≥80% of seeded High issues found, ≤1 false positive per clean PR |
| **2. Shadow** | Receiver, worker and Agent Engine deployed. `PUBLISH_MODE=shadow` writes to BigQuery and logs only, on 1 to 2 iOS repos. | Two weeks of data reviewed with compliance; precision acceptable to them |
| **3. Comment** | `PUBLISH_MODE=comment` turns on the summary, inline comments, labels, reviewers and the neutral check. | Team feedback; no complaints about duplicate or noisy comments |
| **4. Later** | GitHub Issues or Jira sink; opt-in `failure` conclusion on High so the check can be required in branch protection; resolved-finding tracking; web researcher on demand. | |

`PUBLISH_MODE` (`dry_run` | `shadow` | `comment`) lives in the worker config,
so moving between phases doesn't require a redeploy of the agent.

## 10. Open questions

1. GitHub or Bitbucket for the iOS repos, and github.com or GHES? (§2)
2. Who owns and signs off `data/standards/`, and how is it versioned?
3. Is source-to-Gemini approved, and in which region?
4. Advisory only, or should High findings eventually block merges?
5. Which teams map to which topics for reviewer requests?
6. Raise the Vertex AI Search `llm_requests` quota, or rely on `retrieve` only?

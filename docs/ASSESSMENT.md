# NotebookLM MCP — Assessment, Security Review & Roadmap

_Reviewed: 2026-11-01 · Branch `claude/magical-pasteur-p36pn1` · Commit `860a652`_

> **Status: implemented (v1.0.0).** Sections 1–7 below describe the project *as it was*
> when reviewed. See [section 8](#8-decisions--implementation-status) for the owner's
> decisions and how each finding was resolved.

---

## 1. How the project works

```
Claude Desktop / Claude Code
        │  (MCP over stdio)
        ▼
server.py  ── FastMCP 2.14.4 ── 15 @mcp.tool() functions
        │
        ▼
notebooklm-py 0.3.1  (UNOFFICIAL, reverse-engineered client)
        │  HTTPS "batchexecute" RPCs + your Google session cookies
        ▼
notebooklm.google.com
```

* **Auth**: `uv run notebooklm login` opens Playwright Chromium. You sign in to Google, and the
  browser's cookies are written to `~/.notebooklm/storage_state.json` (chmod 600 on macOS/Linux).
  A persistent browser profile is kept at `~/.notebooklm/browser_profile/`.
* **Startup**: the FastMCP `lifespan` loads those cookies once, opens one `NotebookLMClient`,
  and shares it across all tool calls. If you aren't logged in, the server process exits, and the
  tools disappear from Claude without explanation.
* **Tools**: each tool is a thin 3-line wrapper over a library call. There is no validation,
  error handling, status polling, or download support.
* **Other files**: `main.py` is an unused "Hello" stub. `SKILL.md` is a Claude Code skill
  description that refers to a `notebooklm mcp` command which doesn't exist in the pinned
  library version. `pyproject.toml` still has the template name and description. There are no
  tests, no CI, and no LICENSE file, although the README says "MIT".

---

## 2. Security review

### Verified safe ✅
| Check | Result |
|---|---|
| Secrets committed to git (all history, both commits) | **None found** |
| `.gitignore` covers `storage_state.json`, `.notebooklm/`, `.env` | Yes |
| Server logs cookies/tokens | No. It logs only to stderr, so the stdio channel stays clean |
| Cookie file permissions | Login writes it `0600`, and the directory is `0700` (POSIX) |
| Cookies leaked to non-Google hosts on download redirects | No. The library uses a domain-scoped cookie jar, with an allow-list of Google domains |
| TLS verification disabled anywhere | No |
| Lockfile integrity | `uv.lock` pins exact versions with 542 sha256 hashes |
| Local SSRF via `add_source_url` | No. Google's servers fetch the URL, not your machine |
| Destructive tools (delete/share) exposed | None, so the blast radius is currently small |

### Findings ⚠️

| # | Severity | Finding | Fix |
|---|---|---|---|
| S1 | **High (inherent)** | The credential is your **full Google session cookie set** (SID, HSID, `__Secure-*PSID`…), stored in plaintext JSON plus a full browser profile. Anyone or anything that reads that file is logged in as you: **Gmail, Drive, Photos**, not only NotebookLM. On Windows, `chmod 0600` is a no-op. | Use a **dedicated Google account** for NotebookLM. Never sync `~/.notebooklm` to cloud backups. Document this. Optionally store the file in the OS keychain. |
| S2 | **High** | **76 known advisories in 19 locked packages**, including `fastmcp` (2), `mcp` (7), `authlib` (16), `pyjwt` (17), `starlette` (5), `python-multipart` (5), `cryptography` (7), `urllib3` (5). Most affect the HTTP/SSE/OAuth transports, which this stdio server doesn't use, so real exposure today is low. They become live if a remote mode is ever added. | Upgrade to `notebooklm-py` 0.8.6 and `fastmcp` 4.x, re-lock, and add `pip-audit` to CI. |
| S3 | **Medium** | **Unofficial API / Terms of Service.** It scrapes Google's private RPCs. Google can break it at any time, and automated use can get the account flagged. | Use a dedicated account. Pin versions. If you're on Workspace/Enterprise, consider the **official NotebookLM Enterprise API** (Discovery Engine v1alpha). |
| S4 | **Medium** | **README tells users to clone `github.com/alfredang/notebooklm-mcp`**, a different person's repository. Anyone following *your* README runs *their* code. | Point it at your own repo. |
| S5 | **Medium** | **Indirect prompt injection.** Any web page you add as a source can carry instructions that come back to Claude inside `ask_notebook` answers. Harmless now, because no tools delete or share. Once delete/share/upload tools are added, an injected page could, for example, make a notebook public or exfiltrate chat context via `add_source_text`. | Add `confirm=true` gates on destructive and sharing actions, MCP tool annotations (`readOnlyHint` / `destructiveHint`), and an optional read-only mode. |
| S6 | Low | `README` recommends `uv sync --upgrade`. The specs are `>=`, so this jumps 0.3 → 0.8+ unreviewed (supply-chain and breakage risk). | Upper-bound the specs. Upgrade only through reviewed lock updates. |
| S7 | Low | Raw library exceptions go straight to Claude, and some include 500 characters of Google's raw response. | Wrap the errors and return clean messages. |
| S8 | Low | `SKILL.md` suggests `~/.claude/config.json` with `notebooklm mcp`. The path is wrong and the command doesn't exist in 0.3.1, so users end up hand-editing configs. | Rewrite it. |

### Functional bugs 🐞
| # | Bug |
|---|---|
| B1 | **`ask_notebook` and `get_notebook_summary` crash on every call.** They read `result.text` / `result.sources`, but the library returns `AskResult.answer` / `.references`. Reproduced: `AttributeError: 'AskResult' object has no attribute 'text'`. **The core Q&A feature does not work.** |
| B2 | `get_notebook_summary` uses an expensive chat prompt, although the library has `notebooks.get_summary()`. |
| B3 | The 8 `generate_*` tools are fire-and-forget. They return a `task_id`, but there is no tool to check status or download the result, so you have to open the NotebookLM website anyway. |
| B4 | The README advertises "add files as sources", but no file-upload tool exists. |
| B5 | `add_source_url` doesn't wait for processing, so asking right after can return empty or incorrect answers. |
| B6 | Startup hard-fails when not logged in. The server should start and return "please run `notebooklm login`" from the tools instead. |
| B7 | No `conversation_id`, so there are no follow-up questions. No `source_ids`, so you can't restrict to specific sources. No language or format options. |
| B8 | Lifespan calls `__aexit__` even when `__aenter__` failed. `_client_context` is unused. |

---

## 3. What it does today (15 tools)

| Area | Tool | Works? |
|---|---|---|
| Notebooks | `list_notebooks`, `create_notebook` | ✅ |
| Sources | `add_source_url`, `add_source_text` | ✅ (no wait) |
| Chat | `ask_notebook` | ❌ crashes (B1) |
| Chat | `get_notebook_summary` | ❌ crashes (B1) |
| Studio | `generate_audio_overview`, `generate_video_overview`, `generate_slide_deck`, `generate_infographic`, `generate_quiz`, `generate_flashcards`, `generate_summary_report`, `generate_data_table` | ⚠️ start only; no status or download |
| Studio | `generate_mind_map` | ✅ (synchronous; saved as a note) |

Not present: delete/rename anything, list sources, read source text, file/Drive/YouTube-specific
uploads, artifact status/list/download, research, notes, sharing, chat settings, language selection,
artifact options, and auth health.

---

## 4. NotebookLM in late 2026: what it can do

> Google reportedly renamed NotebookLM to **"Gemini Notebook"** on 16 Jul 2026, with the same
> product and URLs. Only some sources mention this, so treat it as unconfirmed.

| Area | Capabilities (2026) |
|---|---|
| **Model** | Gemini 3.5 (default since Jun 2026), large-context chat, saved chat history, chat goals/personas, response length |
| **Sources** | Web URLs, YouTube, PDF, Google Docs/Slides/Sheets, Drive (with **auto-sync** of living docs, May 2026), EPUB, Word, audio, video, images, pasted text, Play Books |
| **Research** | Fast & **Deep Research** agents (web + Drive). Chat-driven source discovery suggests and imports sources (Jun 2026) |
| **Audio Overviews** | Deep Dive / Brief / Critique / Debate formats, short/default/long, interactive "Join", 80+ languages |
| **Video Overviews** | Explainer / Brief, visual styles (whiteboard, classic…), **Cinematic** (Mar 2026), **Short vertical 60s** (Jun 2026), review step before rendering (Oct 2026) |
| **Slide decks** | Detailed/presenter formats, lengths, per-slide revision & feedback, PPTX/PDF export |
| **Infographics** | Orientation, detail level, 10 new styles |
| **Quizzes / Flashcards** | Quantity, difficulty, question types, progress saved |
| **Reports** | Briefing doc, study guide, blog post, custom prompt, AI-suggested report types |
| **Data tables / Mind maps** | Export to Sheets/CSV; interactive mind map |
| **Notes, Sharing** | Notes, save-answer-to-note; public link, viewer/editor per user |
| **Platforms** | Web, Android, iOS, inside the Gemini app; **NotebookLM Enterprise** on Google Cloud with an **official REST API** (notebooks, sources, audio) |

### The most important discovery
`notebooklm-py` (the library this project wraps) has gone from 0.3.1 to **0.8.6** and now ships
**its own official MCP server, `notebooklm-mcp`, with 38 tools**. It covers everything above, plus
security controls this project lacks:
* `confirm=true` gates on delete and sharing; read-only/destructive tool annotations
* default-deny local file uploads (`NOTEBOOKLM_MCP_ALLOWED_ROOTS`), refusing credential files
* an SSRF guard, a loopback-only HTTP mode, bearer/OAuth for remote use, signed expiring download links
* multi-account profiles, background chat jobs, research start/status/import, studio status/download/retry
* an installer: `notebooklm mcp install claude-desktop | claude-code`

**So rebuilding those 38 tools here by hand would duplicate upstream with worse security.** This
repo's value should be what upstream *doesn't* do: opinionated **workflows**, **prompts**, a
**Claude Code skill**, sensible defaults, and documentation for *your* use case.

---

## 5. Gaps & potential (what it could do but doesn't)

1. **One-shot workflows.** "Turn this URL/PDF/YouTube into a podcast, wait, and save the MP3 to
   ~/Downloads." "Build a study pack (quiz + flashcards + study guide) from these 5 links."
2. **Research-to-notebook.** Run Deep Research on a topic, auto-import the best sources, then
   answer with citations.
3. **Grounded Q&A for Claude.** Use NotebookLM as a citation-backed knowledge base Claude
   consults, with follow-ups and per-source filtering.
4. **Artifact retrieval.** Download audio/video/slides/reports/quiz JSON to disk so Claude can
   post-process them (e.g. turn quiz JSON into Anki, or a report into a blog draft).
5. **Sync local folders/Drive** into a notebook (a "second brain" that stays current).
6. **Multi-language output** (podcasts and reports in any of 80+ languages).
7. **MCP Prompts & Resources** (`notebook://{id}/sources`, slash-command prompts in Claude).
8. **Remote connector.** Use it from claude.ai web/mobile, not only desktop.
9. **Health & auth UX.** An `auth_status` tool, clear "re-login" errors, cookie-expiry warnings.

---

## 6. Recommendations

**Fix now**
* Fix B1 (`.answer` / `.references`), and use `notebooks.get_summary()`.
* Upgrade `notebooklm-py` to ~0.8.6 and `fastmcp` to 4.x, re-lock, and clear the advisories.
* Fix the README clone URL (S4), rewrite SKILL.md, add a LICENSE, fix the pyproject metadata,
  and delete `main.py`.
* Return errors as tool results instead of crashing. Start even when logged out.

**Architecture (recommended: hybrid)**
* Run the upstream `notebooklm-mcp` as the base tool layer, either mounted into this FastMCP
  server or side by side.
* Keep this repo as a **thin "workflow layer"**: about 6–10 high-level composite tools, MCP
  prompts, and a Claude Code skill, all with safe defaults.

**Security hardening**
* Dedicated Google account. Read-only mode env flag. Confirmation on destructive and sharing
  actions. Download directory sandbox. `pip-audit` + Dependabot. Tool annotations.

**Quality**
* pytest with a mocked client (the stub technique used in this review already caught B1).
  Ruff + pyright. GitHub Actions CI. A `doctor`/smoke-test command.

---

## 7. Implementation plan (draft; finalised after your answers)

| Phase | Work | Outcome |
|---|---|---|
| **0. Decide** | Answer the questions (account type, clients, use cases, build-vs-adopt, permissions) | Locked scope |
| **1. Fix & secure** (~½ day) | B1–B8 fixes, dependency upgrade + re-lock, pip-audit clean, README/SKILL/LICENSE/pyproject cleanup, auth-status tool, graceful logged-out mode | **Usable today** |
| **2. Architecture** (~½ day) | Adopt/mount upstream `notebooklm-mcp`. Read-only mode. Confirm gates. Allowed upload roots. Download sandbox. Tool annotations | Secure full tool surface (≈40 tools) |
| **3. Workflow tools** (~1 day) | e.g. `research_to_notebook`, `url_to_podcast`, `study_pack`, `ask_with_citations` (follow-ups), `export_artifacts`, `sync_folder`, all with wait+download | One-sentence automations |
| **4. Prompts & skill** (~½ day) | MCP prompts (slash commands), resources, rewritten Claude Code `SKILL.md` | Natural UX in Desktop & Code |
| **5. Quality** (~½ day) | pytest (mocked), ruff/pyright, CI (tests + pip-audit), smoke test, troubleshooting docs, one-command installer | Maintainable & verifiable |
| **6. Optional** | Remote connector for claude.ai/mobile (OAuth + tunnel). Enterprise official-API backend. Multi-account profiles. Scheduled refresh | Use anywhere |

**Definition of "ready to use":** fresh clone → `uv sync` → `notebooklm login` → one install
command → in Claude: "make a podcast from <url> and save it" works end to end. The full test
suite and `pip-audit` pass in CI, and no credentials leave `~/.notebooklm`.

---

## 8. Decisions & implementation status

**Owner's answers:**
- **Account and client:** personal Gmail (one dedicated account), Claude Desktop only.
- **Priorities:** everything, with studying and a second brain first.
- **Restrictions:** no artifact downloads, no local file uploads, read-and-create only.
- **Shape:** self-contained, local server, English output, personal use.
- **Key workflow:** "make study content and quizzes based on my example quiz, the notebook's
  context, and my reading style."

**Architecture chosen:** a self-contained FastMCP server (`src/notebooklm_study_mcp`) on the
public `notebooklm-py` client API. The upstream `notebooklm-mcp` server is not used, as
requested. It exposes 30 tools and 4 prompts.

| Finding | Resolution |
|---|---|
| B1 ask/summary crash | Fixed: uses `AskResult.answer` / `.references`. A regression test fails if `.text` comes back. |
| B2 summary via chat | `get_notebook` uses `notebooks.get_description()` (summary + suggested questions). |
| B3 fire-and-forget generation | Added `wait_for_artifact`, `list_artifacts`, `read_artifact` (inline quiz/flashcards/report/mind map/table). |
| B4 no file tool | Intentionally none (owner: no local uploads). Added Drive and YouTube instead. |
| B5 no wait | Source adds wait for processing by default; URLs are restricted to public http(s) hosts. |
| B6 hard-fail when logged out | Lazy single-flight client: starts instantly, explains `notebooklm login`, recovers without restart. |
| B7 missing options | Follow-ups, source filters, and all format/style/length/difficulty options are exposed. |
| B8 lifespan bug | Replaced by `ClientProvider`. |
| S1 cookie = whole account | README requires a dedicated account; login stays in the library's 0700/0600 store. |
| S2 76 advisories | notebooklm-py 0.8.6, fastmcp 4.1.4, mcp 2.3.0, full re-lock. **`pip-audit`: no known vulnerabilities.** CI audits weekly; Dependabot enabled. |
| S3 unofficial API | Documented; versions capped `<0.9` / `<5`. |
| S4 foreign clone URL | README points to `ryanvafaei/notebooklm-mcp`. |
| S5 prompt injection | No delete/rename/share/update tools exist. Tool annotations (read-only vs create, none destructive). Server instructions mark source content as untrusted. Optional `NOTEBOOKLM_MCP_READ_ONLY=1`. |
| S6 `uv sync --upgrade` | Removed from the docs; upper-bounded specs. |
| S7 raw errors | All tools go through `handle_errors`: categorised messages with tokens and paths scrubbed. FastMCP `mask_error_details`. Logs record exception *types* only. |
| S8 wrong SKILL.md | Removed (with the `main.py` stub). Workflow guidance now lives in server instructions + MCP prompts. |
| No local file access | No tool takes a path. Artifact text is exported to a per-call 0700 temp dir, read, and deleted. |
| Study profile | `~/.notebooklm-study/study_profile.json`, atomic write, 0600, field size caps. |

**Verification:**
- 23 pytest tests use a fake client built from the library's real dataclasses.
- A mutation check confirmed that reintroducing B1 fails the suite.
- An end-to-end stdio run of both entry points (`notebooklm-study-mcp` and legacy
  `python server.py`) completed the handshake in about 1.3 s with no login. It listed 30 tools
  and 4 prompts and returned the login hint.
- Ruff lint and format are clean.
- **Not verifiable in CI:** live calls to Google, which need your login. Run `auth_status` in
  Claude Desktop after setup.

---

### Sources
* [notebooklm-py CHANGELOG](https://github.com/teng-lin/notebooklm-py/blob/main/CHANGELOG.md) · [MCP guide](https://github.com/teng-lin/notebooklm-py/blob/main/docs/mcp-guide.md) · [repo](https://github.com/teng-lin/notebooklm-py)
* [NotebookLM — Wikipedia](https://en.wikipedia.org/wiki/NotebookLM)
* [TechCrunch, Jun 2026 — build source repository from chat](https://techcrunch.com/2026/06/08/notebooklms-new-update-will-help-you-build-source-repository-from-chat/)
* [Google Workspace Updates, Mar 2026](https://workspaceupdates.googleblog.com/2026/03/new-ways-to-customize-and-interact-with-your-content-in-NotebookLM.html)
* [Geeky Gadgets — NotebookLM 2026 guide](https://www.geeky-gadgets.com/notebooklm-2026-new-features/)
* [Glasp — Gemini Notebook 2026 guide](https://glasp.co/articles/notebooklm-2026)
* [notebooklm-enterprise-mcp (official Enterprise API notes)](https://pypi.org/project/notebooklm-enterprise-mcp/)
* Local: `pip-audit` on `uv.lock`; source inspection of notebooklm-py 0.3.1; stub-client reproduction of B1.

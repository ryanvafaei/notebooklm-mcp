# NotebookLM Study MCP (for Claude Desktop)

A **local** MCP server that connects Claude Desktop to Google NotebookLM. It is built for
**studying** and a **second brain**:

- Turn a notebook into **study notes written in your reading style**.
- Get **quizzes that copy the format of an example quiz you like**, then be quizzed interactively.
- Ask **cited questions** across your sources, with follow-ups.
- Capture links, YouTube videos, Google Docs and text, save notes, and run **web/Drive research**
  to grow your knowledge base.
- Use NotebookLM's own Studio: quizzes, flashcards, study guides, mind maps, audio and video
  overviews, slides, infographics and data tables.

**Safety model:**
- **Read and create only.** It can never delete, rename or share anything.
- **No local file access.** It never reads your files or downloads artifacts.
- **Runs only on your computer** over stdio. It never opens a network port.
- **Talks to Google only.** A built-in network guard blocks every other destination and
  stops the server from starting other programs.

---

## ⚠️ Read first: privacy, network & your Google account

### Where your data goes
```
Your laptop                                      Internet
┌──────────────────────────────────────┐
│ Claude Desktop ─stdio─► this server ─┼──► Google only (notebook.google.com,
│                         (local)      │    accounts.google.com, *.googleapis.com)
│ Google login cookies stay here       │
└──────────────────────────────────────┘
Claude Desktop ──► Anthropic (Claude itself; sees what tools return in the chat)
```

- **This server runs entirely on your laptop.** Claude Desktop starts it as a local process
  and talks to it through stdin/stdout. It never opens a network port and has no server of
  its own.
- **Its only outbound connections go to Google**, because NotebookLM is a Google cloud
  service: your notebooks live on Google's servers, not on your laptop. A built-in **egress
  guard** (`netguard.py`) enforces this. It refuses DNS lookups and connections to anything
  that isn't a Google domain, including proxies, analytics and update checks, and it refuses
  to start other programs. Ask Claude *"check my NotebookLM connection"*; `auth_status`
  reports `"network": "Google-only egress guard active"`.
- **Your Google login (cookies) never leaves your laptop** except to Google itself. Tools
  never return cookies, tokens or file paths.
- **What Claude reads goes to Anthropic.** Claude is a cloud model, so whatever a tool returns
  into the chat (answers, notes, quiz questions, source text) is sent to Anthropic, like
  anything else you share with Claude. Only ask about notebooks you're comfortable sharing
  with Claude.

### Using your main Google account
The saved cookies (`~/.notebooklm/profiles/default/storage_state.json`) act as a **logged-in
session for your whole Google account** (Gmail, Drive, Photos…), not only NotebookLM. Anyone
or anything that can read that file can act as you. If you use your main account:

1. **Turn on full-disk encryption**: FileVault on macOS, BitLocker on Windows.
2. **Keep `~/.notebooklm` out of backups and sync** (iCloud Drive, OneDrive, Dropbox, Time
   Machine to unencrypted disks). Never commit or share it.
3. **Don't install untrusted software** on this laptop. Any program running as you can read
   the file.
4. **To revoke access at any time:** delete the `~/.notebooklm` folder, then in your Google
   Account go to *Security → Your devices* and sign out the unrecognised session (or sign out
   of all other sessions).
5. Avoid `notebooklm login --browser-cookies`. It copies cookies from your everyday browser
   profile.

Other things to know:
- `notebooklm-py` is an **unofficial** library using NotebookLM's private web API. Google can
  change it at any time, and heavy automated use could in principle get an account flagged.
  The server makes no requests on its own; it only acts when you ask Claude to.
- Content from web pages and documents is treated as **untrusted**. Because the server has no
  delete, rename or share tools, a malicious page can't delete or share your notebooks or
  reach any non-Google server.

---

## 1. Install

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) and git.

```bash
git clone https://github.com/ryanvafaei/notebooklm-mcp.git
```

```bash
cd notebooklm-mcp
```

```bash
uv sync
```

## 2. Log in to NotebookLM (once)

Log in with your Google account (see the main-account precautions above). On macOS, using
your installed Google Chrome is the most reliable option:

```bash
uv run notebooklm login --browser chrome
```

Or, with the bundled Chromium:

```bash
uv run playwright install chromium
```

```bash
uv run notebooklm login
```

A browser opens. Sign in, and the login is saved automatically. Login is the only step that
uses a normal browser window, which talks to Google's sign-in pages. Sessions expire after a few
weeks. When Claude says *"NotebookLM is not logged in"*, run the login command again (no
restart needed).

> Avoid `--browser-cookies`. It copies cookies out of your everyday browser profile.

## 3. Connect Claude Desktop

Find the full path to `uv` (`which uv` on macOS, `where uv` on Windows) and to this folder
(`pwd`). Then in Claude Desktop open **Settings → Developer → Edit Config** and add:

**macOS**
```json
{
  "mcpServers": {
    "notebooklm": {
      "command": "/Users/YOU/.local/bin/uv",
      "args": ["--directory", "/Users/YOU/path/to/notebooklm-mcp", "run", "notebooklm-study-mcp"]
    }
  }
}
```

**Windows** (use double backslashes)
```json
{
  "mcpServers": {
    "notebooklm": {
      "command": "C:\\Users\\YOU\\.local\\bin\\uv.exe",
      "args": ["--directory", "C:\\Users\\YOU\\path\\to\\notebooklm-mcp", "run", "notebooklm-study-mcp"]
    }
  }
}
```

Fully quit Claude Desktop (macOS: Cmd+Q; Windows: tray icon → Quit) and reopen it.
Then ask: **"Check my NotebookLM connection"**. Claude calls `auth_status`.

> Older configs that run `python server.py` keep working.

## 4. Install the Claude Desktop skill (recommended)

`skills/notebooklm-study/SKILL.md` teaches Claude the best workflows below. Unlike the slash
prompts, it **triggers automatically** when you ask for something it covers (e.g. "make a doc
from my Biology notebook"). To install it:
1. Zip the `skills/notebooklm-study` folder.
2. In Claude Desktop, open **Settings → Capabilities → Skills** and upload the ZIP. Skills
   must be enabled for your account.

## 5. First steps

1. **Set up a study profile.** Use the **`setup_study_profile`** prompt (the "+" / attach menu
   → NotebookLM Study), or say *"set up my Biology study profile"*. Describe how you like
   material written, paste an example quiz you like, and pick the notebooks that use it.
2. **Write a document.** Use **`draft_document`**, or say: *"Write a 2-page handout on cell
   respiration from my Biology notebook."*
3. **Study.** Use **`study_session`**: *"Study session on my Biology notebook, topic: cell
   respiration."*
4. **Quiz.** Use **`quiz_me`**: *"Quiz me with 10 questions on chapter 3."* Your results are
   remembered, so the next session targets your weak spots.
5. **Capture.** Use **`capture`**: *"Add https://… to my Biology notebook."*

---

## What it can do (35 tools, 5 prompts)

| Area | Tools |
|---|---|
| Status | `auth_status` (login, account, network guard) |
| Notebooks | `list_notebooks`, `get_notebook` (summary, suggested questions, sources), `create_notebook` |
| Sources | `read_source` (summary + key terms, or full text paged), `add_source_url` (web/YouTube), `add_source_text`, `add_source_drive` (Docs/Slides/Sheets/PDF in your Drive) |
| Chat | `ask_notebook` (cited answers; each call is an independent prompt unless you pass `conversation_id`), `ask_notebook_batch` (up to 8 independent prompts in one call) |
| Documents | `finalize_citations` (turns citation tokens into `[1]`, `[2]` … plus a reference list) |
| Notes | `list_notes`, `read_note`, `create_note`, `save_answer_as_note` (keeps interactive citations) |
| Research | `start_research` (web or Drive, fast or deep), `get_research_status`, `import_research_sources` |
| Studio | `generate_quiz`, `generate_flashcards`, `generate_report` (study guide, briefing, concept explanation, blog, custom), `generate_mind_map`, `generate_audio_overview`, `generate_video_overview`, `generate_slide_deck`, `generate_infographic`, `generate_data_table`, `list_artifacts`, `wait_for_artifact`, `read_artifact` |
| Study | `get_study_profile`, `update_study_profile` (per subject), `build_study_pack`, `record_quiz_result`, `get_study_progress` |

**Prompts** (slash-commands): `draft_document`, `study_session`, `quiz_me`, `capture`,
`setup_study_profile`.

### How documents are written (NotebookLM writes, Claude assembles)
1. Claude reads the notebook's summary and proposes an outline for you to confirm.
2. It writes **one self-contained prompt per section** and sends them with
   `ask_notebook_batch`. Each prompt is independent: NotebookLM sees no earlier questions,
   so sections don't contaminate each other.
3. Each answer comes back with stable citation tokens (`[src:1a2b3c4d]`). Claude assembles
   the document with **light edits only**: headings, transitions, trimming repetition. It
   never adds facts that aren't in NotebookLM's answers.
4. `finalize_citations` renumbers the tokens to `[1]`, `[2]` … in order of first use and adds
   a **References** list of the cited sources. This step is deterministic, never by hand.
5. The document appears as an artifact in Claude Desktop. Optionally, it's saved into the
   notebook with `create_note`.

Independent asks still show up in the notebook's chat panel in NotebookLM; that's how
NotebookLM records them.

### How personalised studying works
- **Profiles per subject.** `update_study_profile` saves your **reading style**, an
  **example quiz**, your **learner context** (level, goal, exam) and **quiz preferences**
  under a profile name (e.g. `biology`, `law`) and assigns it to notebooks. Notebooks
  without an assignment use `default`. Profiles are stored in
  `~/.notebooklm-study/study_profile.json`, readable only by you, with no credentials.
- **Weak-spot tracking.** After a quiz, `record_quiz_result` saves your score and the topics
  you missed to `~/.notebooklm-study/progress.json`. `get_study_progress` shows your
  history, average, weak spots and mastered topics.
- **`build_study_pack`** gathers, for a notebook and optional topic:
  - the notebook's profile and your weak spots
  - the notebook summary
  - each source's summary and key terms
  - a cited explanation from NotebookLM that goes deeper on your weak spots
  - the latest NotebookLM quiz and flashcards

  Claude then writes notes in your style and a quiz that **copies your example's format**,
  weighted towards what you keep missing.
- `generate_quiz`, `generate_flashcards` and `generate_report` blend the notebook's profile
  into NotebookLM's instructions (turn off with `use_study_profile=false`). NotebookLM
  quizzes are always multiple-choice; for your exact format, use `quiz_me`.
- `read_artifact` brings finished quizzes, flashcards, reports, mind maps and data tables into
  the chat. Audio, video, slides and infographics open in NotebookLM, and nothing is
  downloaded.
- `save_answer_as_note` keeps a great answer in the notebook with clickable citations.

---

## Configuration (optional environment variables)

Add these under `"env": { ... }` in the Claude Desktop config.

| Variable | Effect |
|---|---|
| `NOTEBOOKLM_MCP_READ_ONLY=1` | Hide every create tool (pure read-only mode). |
| `NOTEBOOKLM_STUDY_HOME` | Where study profiles and quiz progress are stored (default `~/.notebooklm-study`). |
| `NOTEBOOKLM_HOME` | Where the NotebookLM login is stored (default `~/.notebooklm`). |
| `NOTEBOOKLM_MCP_LOG_LEVEL` | `DEBUG`/`INFO`/`WARNING` (logs go to Claude's MCP log, never to the chat). |

## Troubleshooting

| Symptom | Fix |
|---|---|
| "NotebookLM is not logged in / session expired" | Run `uv run notebooklm login --browser chrome` in this folder, then retry. |
| Server not listed in Claude | Use **full paths** to `uv` and the folder; check the JSON is valid; fully quit and reopen Claude. |
| Bundled Chromium crashes on login (macOS 15+) | Use `--browser chrome`. |
| "rate limit or daily quota" | NotebookLM limits generations per day; try later. |
| Windows: `NotImplementedError` during login | Fixed in notebooklm-py ≥ 0.8 (we pin 0.8.6). Run `uv sync`; make sure `NOTEBOOKLM_WINDOWS_EVENT_LOOP` is not set to `selector`. |
| Logs | macOS: `~/Library/Logs/Claude/mcp*.log` · Windows: `%APPDATA%\Claude\logs` |

## Updating safely

Dependency versions are locked in `uv.lock`, and `pyproject.toml` caps them below the next
minor release. To update:

```bash
git pull
```

```bash
uv sync
```

Avoid `uv sync --upgrade` unless you then run the tests (below). The NotebookLM library changes
often.

## Development

```bash
uv run pytest
```

```bash
uv run ruff check src tests && uv run ruff format --check src tests
```

```bash
uvx pip-audit -r <(uv export --frozen --no-hashes --no-emit-project)
```

CI runs tests on macOS, Windows and Linux, plus lint and a dependency vulnerability audit.
`docs/ASSESSMENT.md` holds the security review and design notes.

```
notebooklm-mcp/
├── src/notebooklm_study_mcp/
│   ├── server.py     # tools & prompts (read/create only)
│   ├── client.py     # lazy NotebookLM client (starts even when logged out)
│   ├── errors.py     # safe, actionable error messages
│   ├── artifacts.py  # read quiz/report content inline, no files kept
│   ├── profile.py    # study profiles per subject (0600)
│   ├── progress.py   # quiz history & weak spots (0600)
│   ├── citations.py  # citation tokens → [1], [2] + reference list
│   ├── netguard.py   # egress guard: Google-only network, no child processes
│   └── prompts.py    # server instructions + slash-command prompts
├── tests/            # fake client using the library's real data types
├── skills/notebooklm-study/SKILL.md  # Claude Desktop skill (auto-triggered workflows)
└── server.py         # backward-compatible entry point
```

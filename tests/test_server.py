import os
import stat
import sys

import notebooklm as nlm
import pytest
from conftest import NB, call, make_server
from fastmcp import Client
from fastmcp.exceptions import ToolError

from notebooklm_study_mcp.errors import LOGIN_HINT, scrub
from notebooklm_study_mcp.profile import StudyProfile
from notebooklm_study_mcp.server import blend_profile, parse_drive_id, validate_url

DESTRUCTIVE_WORDS = ("delete", "remove", "rename", "share", "update_note", "set_")


# ------------------------------------------------------------------ safety surface
async def test_no_destructive_or_file_tools(mcp_client):
    tools = await mcp_client.list_tools()
    names = {t.name for t in tools}
    assert len(names) == 30
    for name in names:
        assert not any(w in name for w in DESTRUCTIVE_WORDS), name
    for t in tools:
        props = t.input_schema.get("properties", {})
        assert not any("path" in p or "file" == p for p in props), (t.name, props)
        assert t.annotations is not None
        assert t.annotations.destructive_hint in (False, None), t.name


async def test_read_tools_are_annotated_read_only(mcp_client):
    tools = {t.name: t for t in await mcp_client.list_tools()}
    for name in (
        "list_notebooks",
        "get_notebook",
        "ask_notebook",
        "read_source",
        "read_artifact",
        "build_study_pack",
        "wait_for_artifact",
    ):
        assert tools[name].annotations.read_only_hint is True, name
    for name in ("create_notebook", "add_source_url", "generate_quiz", "create_note"):
        assert tools[name].annotations.read_only_hint is False, name


async def test_read_only_mode_hides_create_tools(fake, store):
    async with Client(make_server(fake, store, read_only=True)) as c:
        names = {t.name for t in await c.list_tools()}
    assert "create_notebook" not in names
    assert "add_source_url" not in names
    assert "generate_quiz" not in names
    assert "update_study_profile" not in names
    assert {"list_notebooks", "ask_notebook", "build_study_pack"} <= names


async def test_prompts_registered(mcp_client):
    names = {p.name for p in await mcp_client.list_prompts()}
    assert names == {"study_session", "quiz_me", "capture", "setup_study_profile"}


# ------------------------------------------------------------------ auth handling
async def test_logged_out_server_still_starts_and_explains(store):
    server = make_server(FileNotFoundError("storage_state.json missing"), store)
    async with Client(server) as c:
        status = await call(c, "auth_status")
        assert status["logged_in"] is False
        assert "notebooklm login" in status["problem"]
        with pytest.raises(ToolError, match="notebooklm login"):
            await c.call_tool("list_notebooks", {})


async def test_auth_status_ok(mcp_client):
    status = await call(mcp_client, "auth_status")
    assert status["logged_in"] is True
    assert status["notebook_count"] == 1


# ------------------------------------------------------------------ core tools
async def test_ask_notebook_returns_answer_and_citations(mcp_client, fake):
    out = await call(mcp_client, "ask_notebook", notebook_id=NB, question="What makes ATP?")
    assert out["answer"].startswith("Mitochondria")
    assert out["conversation_id"] == "conv1"
    assert out["citations"] == [
        {
            "n": 1,
            "source_id": "s1",
            "source_title": "Cell Biology Ch.1",
            "cited_text": "The mitochondria...",
        }
    ]
    assert out["suggested_follow_ups"] == ["What is ATP?"]
    out2 = await call(
        mcp_client, "ask_notebook", notebook_id=NB, question="More?", conversation_id="conv1"
    )
    assert out2["conversation_id"] == "conv1"
    assert fake.rec.last("chat.ask")[1]["conversation_id"] == "conv1"


async def test_list_notebooks_sorts_mixed_timestamps(fake, store):
    from datetime import UTC, datetime

    async def listing():
        return [
            nlm.Notebook(id="old", title="Old", modified_at=datetime(2024, 1, 1)),
            nlm.Notebook(id="none", title="No date"),
            nlm.Notebook(id="new", title="New", modified_at=datetime(2026, 1, 1, tzinfo=UTC)),
        ]

    fake.notebooks.list = listing
    async with Client(make_server(fake, store)) as c:
        out = await call(c, "list_notebooks")
    assert [n["id"] for n in out] == ["new", "old", "none"]


async def test_get_notebook(mcp_client):
    out = await call(mcp_client, "get_notebook", notebook_id=NB)
    assert out["summary"] == "All about cells."
    assert out["suggested_questions"] == ["What is ATP?"]
    assert out["sources"][0]["status"] == "ready"


async def test_not_found_is_clean_error(mcp_client):
    with pytest.raises(ToolError, match="Not found"):
        await mcp_client.call_tool("get_notebook", {"notebook_id": "nope"})


async def test_read_source_paging(mcp_client):
    out = await call(
        mcp_client, "read_source", notebook_id=NB, source_id="s1", mode="text", max_chars=1000
    )
    assert out["total_chars"] == 1500 and len(out["content"]) == 1000
    assert out["next_offset"] == 1000
    guide = await call(mcp_client, "read_source", notebook_id=NB, source_id="s1")
    assert guide["keywords"] == ["cell", "ATP"]


async def test_add_sources(mcp_client, fake):
    await call(mcp_client, "add_source_url", notebook_id=NB, url="https://youtu.be/abc")
    assert fake.rec.last("sources.add_url")[1]["wait"] is True
    with pytest.raises(ToolError, match="http"):
        await mcp_client.call_tool(
            "add_source_url", {"notebook_id": NB, "url": "file:///etc/passwd"}
        )
    await call(
        mcp_client,
        "add_source_drive",
        notebook_id=NB,
        title="Doc",
        drive_url_or_id="https://docs.google.com/document/d/1AbCdEfGhIjKlMn/edit",
    )
    args, _ = fake.rec.last("sources.add_drive")
    assert args[1] == "1AbCdEfGhIjKlMn"
    with pytest.raises(ToolError, match="empty"):
        await mcp_client.call_tool(
            "add_source_text", {"notebook_id": NB, "title": "t", "text": "   "}
        )


async def test_research_flow(mcp_client, fake):
    out = await call(mcp_client, "start_research", notebook_id=NB, query="cells", mode="deep")
    assert out["task_id"] == "r1"
    status = await call(mcp_client, "get_research_status", notebook_id=NB, task_id="r1")
    assert [s["index"] for s in status["sources"]] == [0, 1]
    imp = await call(
        mcp_client, "import_research_sources", notebook_id=NB, task_id="r1", indices=[1]
    )
    assert imp["imported_count"] == 1
    assert fake.rec.last("research.import_sources")[0][2][0].title == "B"
    with pytest.raises(ToolError, match="Invalid indices"):
        await mcp_client.call_tool(
            "import_research_sources", {"notebook_id": NB, "task_id": "r1", "indices": [5]}
        )


# ------------------------------------------------------------------ studio
async def test_generate_quiz_maps_enums_and_profile(mcp_client, fake, store):
    store.update(quiz_example="Q1: Define osmosis. A: ...", learner_context="Year 1 bio")
    out = await call(
        mcp_client, "generate_quiz", notebook_id=NB, difficulty="hard", quantity="more"
    )
    assert out["task_id"] == "t-quiz"
    kw = fake.rec.last("artifacts.generate_quiz")[1]
    assert kw["difficulty"] is nlm.QuizDifficulty.HARD
    assert kw["quantity"] is nlm.QuizQuantity.MORE
    assert "Define osmosis" in kw["instructions"] and "Year 1 bio" in kw["instructions"]


async def test_generate_report_and_media(mcp_client, fake):
    await call(mcp_client, "generate_report", notebook_id=NB, use_study_profile=False)
    kw = fake.rec.last("artifacts.generate_report")[1]
    assert kw["report_format"] is nlm.ReportFormat.STUDY_GUIDE
    with pytest.raises(ToolError, match="instructions"):
        await mcp_client.call_tool(
            "generate_report", {"notebook_id": NB, "format": "custom", "use_study_profile": False}
        )
    await call(mcp_client, "generate_audio_overview", notebook_id=NB, format="debate")
    assert fake.rec.last("artifacts.generate_audio")[1]["audio_format"] is nlm.AudioFormat.DEBATE
    await call(mcp_client, "generate_video_overview", notebook_id=NB, style="whiteboard")
    assert fake.rec.last("artifacts.generate_video")[1]["video_style"] is nlm.VideoStyle.WHITEBOARD
    await call(mcp_client, "generate_video_overview", notebook_id=NB, format="cinematic")
    fake.rec.last("artifacts.generate_cinematic_video")
    await call(mcp_client, "generate_infographic", notebook_id=NB, style="scientific")
    await call(mcp_client, "generate_slide_deck", notebook_id=NB, length="short")
    mm = await call(mcp_client, "generate_mind_map", notebook_id=NB)
    assert mm["note_id"] == "mm1" and mm["mind_map"] == {"name": "Cells"}


async def test_wait_and_read_artifacts(mcp_client, fake):
    done = await call(mcp_client, "wait_for_artifact", notebook_id=NB, task_id="q1")
    assert done["done"] is True and done["status"] == "completed"
    slow = await call(mcp_client, "wait_for_artifact", notebook_id=NB, task_id="slow")
    assert slow["done"] is False

    quiz = await call(mcp_client, "read_artifact", notebook_id=NB, artifact_id="q1")
    q = quiz["content"]["questions"][0]
    assert q["options"][0] == {"text": "Mitochondria", "correct": True, "rationale": "Makes ATP."}
    # Content was read from a temp dir that no longer exists: nothing persisted.
    written = fake.rec.last("artifacts.download_quiz")[0][0]
    assert not os.path.exists(written)

    media = await call(mcp_client, "read_artifact", notebook_id=NB, artifact_id="a1")
    assert "open_in_notebooklm" in media and "content" not in media
    pending = await call(mcp_client, "read_artifact", notebook_id=NB, artifact_id="p1")
    assert pending["ready"] is False


# ------------------------------------------------------------------ study
async def test_study_profile_roundtrip_and_permissions(mcp_client, store):
    empty = await call(mcp_client, "get_study_profile")
    assert empty["is_empty"] is True
    await call(mcp_client, "update_study_profile", reading_style="Bullets, bold terms")
    await call(mcp_client, "update_study_profile", quiz_example="Q: ...")
    prof = await call(mcp_client, "get_study_profile")
    assert prof["reading_style"] == "Bullets, bold terms" and prof["quiz_example"] == "Q: ..."
    if sys.platform != "win32":
        assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
        assert stat.S_IMODE(store.home.stat().st_mode) == 0o700
    with pytest.raises(ToolError, match="too long"):
        await mcp_client.call_tool("update_study_profile", {"reading_style": "x" * 5000})


async def test_build_study_pack(mcp_client, fake, store):
    store.update(reading_style="Feynman style", quiz_example="1) ... a) b) c)")
    pack = await call(mcp_client, "build_study_pack", notebook_id=NB, topic="mitochondria")
    assert pack["study_profile"]["reading_style"] == "Feynman style"
    assert pack["sources"][0]["key_terms"] == ["cell", "ATP"]
    assert pack["explanation"]["cited_sources"] == ["Cell Biology Ch.1"]
    assert "mitochondria" in fake.rec.last("chat.ask")[0][1]
    kinds = [e["kind"] for e in pack["existing_notebooklm_quizzes"]]
    assert kinds == ["quiz"]  # flashcards download failed gracefully / none present


# ------------------------------------------------------------------ helpers
def test_validate_url():
    assert validate_url(" https://example.com/a ") == "https://example.com/a"
    for bad in (
        "javascript:alert(1)",
        "ftp://x.com",
        "https://",
        "not a url",
        "http://localhost:8080/admin",
        "http://127.0.0.1/",
        "http://192.168.1.10/router",
        "http://[::1]/",
        "http://printer.local/",
    ):
        with pytest.raises(ToolError):
            validate_url(bad)


def test_parse_drive_id():
    assert parse_drive_id("1AbCdEfGhIjKlMnOp") == "1AbCdEfGhIjKlMnOp"
    assert parse_drive_id("https://drive.google.com/open?id=1AbCdEfGhIjK") == "1AbCdEfGhIjK"
    with pytest.raises(ToolError):
        parse_drive_id("https://evil.example.com/d/1AbCdEfGhIjKlMn")


def test_blend_profile_caps_length():
    p = StudyProfile(
        reading_style="s" * 4000,
        quiz_example="q" * 20000,
        learner_context="l" * 4000,
        quiz_preferences="p" * 4000,
    )
    assert len(blend_profile("i" * 4000, p, quiz=True)) <= 4000
    assert blend_profile("", StudyProfile(), quiz=False) is None


def test_scrub_removes_tokens_and_paths():
    msg = scrub("bad cookie SIDabcdefghijklmnopqrstuvwxyz0123456789 at /home/me/.notebooklm/x")
    assert "abcdefghijklmnop" not in msg and "/home/me" not in msg


def test_login_hint_mentions_command():
    assert "uv run notebooklm login" in LOGIN_HINT

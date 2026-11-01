"""Tests for the document workflow, answer notes, per-subject profiles and weak spots."""

import json
import stat
import sys

import notebooklm as nlm
import pytest
from conftest import NB, S1, S2, call, make_server
from fastmcp import Client
from fastmcp.exceptions import ToolError

from notebooklm_study_mcp import citations as cite
from notebooklm_study_mcp.errors import to_tool_error
from notebooklm_study_mcp.profile import ProfileStore
from notebooklm_study_mcp.progress import ProgressStore

T1, T2 = cite.source_token(S1), cite.source_token(S2)


# ------------------------------------------------------------------ citations (pure)
class Ref:
    def __init__(self, source_id, citation_number=None):
        self.source_id, self.citation_number = source_id, citation_number


class Src:
    def __init__(self, id, title, url=None):
        self.id, self.title, self.url = id, title, url


def test_tokenize_replaces_markers_and_keeps_non_citations():
    text, cited, unresolved = cite.tokenize_answer(
        "A is true [1]. B too [2][1]. Founded in [1999]. See [1, 2].",
        [Ref(S1, 1), Ref(S2, 2)],
    )
    assert text == f"A is true {T1}. B too {T2} {T1}. Founded in [1999]. See {T1}{T2}."
    assert cited == [S1, S2] and unresolved == 0


def test_tokenize_index_fallback_and_unresolved():
    text, cited, unresolved = cite.tokenize_answer("X [1]. Y [2].", [Ref(S1), Ref(None, 2)])
    assert text == f"X {T1}. Y."
    assert cited == [S1] and unresolved == 1


def test_finalize_numbers_by_first_appearance_and_builds_references():
    draft = f"# Doc\n\nIntro {T2}.\n\nMore {T1} and again {T2}{T2}. Bad [src:deadbeef]."
    out = cite.finalize(draft, [Src(S1, "Cells", "https://e.x/c"), Src(S2, "Metabolism")])
    assert "Intro [1]." in out["markdown"]
    assert "More [2] and again [1]." in out["markdown"]
    assert out["markdown"].rstrip().endswith("1. Metabolism\n2. Cells — <https://e.x/c>")
    assert [r["title"] for r in out["references"]] == ["Metabolism", "Cells"]
    assert out["unresolved_tokens"] == ["deadbeef"]


def test_finalize_without_tokens_adds_no_reference_section():
    out = cite.finalize("Plain text.", [Src(S1, "Cells")])
    assert out["markdown"] == "Plain text." and out["references"] == []


# ------------------------------------------------------------------ document workflow
async def test_batch_is_independent_tokenized_and_isolates_failures(mcp_client, fake):
    out = await call(
        mcp_client,
        "ask_notebook_batch",
        notebook_id=NB,
        prompts_list=["Section 1: explain using two sources", "Section 2: FAIL please", "Sec 3"],
    )
    r0, r1, r2 = out["results"]
    assert out["failed"] == 1
    assert r0["answer"].startswith(f"Glycolysis happens in the cytosol {T2}.")
    assert "[2024]" in r0["answer"]  # non-citation brackets untouched
    assert [s["title"] for s in r0["sources_cited"]] == ["Metabolism Notes", "Cell Biology Ch.1"]
    assert "rate limit" in r1["error"].lower()
    assert r2["answer"] == f"Mitochondria make ATP {T1}."
    # every prompt was sent as an independent ask (no conversation carried over)
    asks = [kw for name, _, kw in fake.rec.calls if name == "chat.ask"]
    assert len(asks) == 3 and all(kw["conversation_id"] is None for kw in asks)


async def test_batch_limits(mcp_client):
    with pytest.raises(ToolError):
        await mcp_client.call_tool("ask_notebook_batch", {"notebook_id": NB, "prompts_list": []})
    with pytest.raises(ToolError):
        await mcp_client.call_tool(
            "ask_notebook_batch", {"notebook_id": NB, "prompts_list": ["q"] * 9}
        )


async def test_end_to_end_document_flow(mcp_client):
    batch = await call(
        mcp_client,
        "ask_notebook_batch",
        notebook_id=NB,
        prompts_list=["intro with two sources", "detail"],
    )
    draft = "# Cellular respiration\n\n" + "\n\n".join(r["answer"] for r in batch["results"])
    final = await call(mcp_client, "finalize_citations", notebook_id=NB, markdown=draft)
    md = final["markdown"]
    assert "[src:" not in md
    assert "cytosol [1]" in md and "mitochondria [2]" in md and "make ATP [2]" in md
    assert "## References\n\n1. Metabolism Notes\n2. Cell Biology Ch.1" in md
    assert "warning" not in final


async def test_finalize_warns_on_unknown_tokens(mcp_client):
    final = await call(
        mcp_client, "finalize_citations", notebook_id=NB, markdown="Claim [src:00000000]."
    )
    assert final["unresolved_tokens"] == ["00000000"] and "warning" in final


# ------------------------------------------------------------------ save answer as note
async def test_save_answer_as_note_keeps_interactive_citations(mcp_client, fake):
    ans = await call(mcp_client, "ask_notebook", notebook_id=NB, question="What makes ATP?")
    note = await call(
        mcp_client, "save_answer_as_note", notebook_id=NB, answer_id=ans["answer_id"], title="ATP"
    )
    assert note == {"note_id": "n9", "title": "ATP", "interactive_citations": True}
    saved = fake.rec.last("chat.save_answer_as_note")[0][1]
    assert isinstance(saved, nlm.AskResult) and saved.references
    with pytest.raises(ToolError, match="Unknown or expired"):
        await mcp_client.call_tool("save_answer_as_note", {"notebook_id": NB, "answer_id": "nope"})
    with pytest.raises(ToolError, match="different notebook"):
        await mcp_client.call_tool(
            "save_answer_as_note", {"notebook_id": "other", "answer_id": ans["answer_id"]}
        )


async def test_batch_answers_can_be_saved_as_notes(mcp_client):
    batch = await call(mcp_client, "ask_notebook_batch", notebook_id=NB, prompts_list=["x"])
    note = await call(
        mcp_client,
        "save_answer_as_note",
        notebook_id=NB,
        answer_id=batch["results"][0]["answer_id"],
    )
    assert note["interactive_citations"] is True


# ------------------------------------------------------------------ profiles per subject
def test_v1_profile_file_is_migrated(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "study_profile.json").write_text(json.dumps({"reading_style": "Bullets"}))
    store = ProfileStore(home)
    assert store.load().reading_style == "Bullets"
    assert store.names() == ["default"]


async def test_profiles_per_subject_and_notebook_assignment(mcp_client, fake, store):
    await call(mcp_client, "update_study_profile", reading_style="Plain English")
    await call(
        mcp_client,
        "update_study_profile",
        profile="Biology",
        quiz_example="Q: Name the organelle...",
        assign_to_notebooks=[NB],
    )
    prof = await call(mcp_client, "get_study_profile", notebook_id=NB)
    assert prof["profile"] == "biology"
    assert prof["quiz_example"].startswith("Q: Name the organelle")
    assert prof["all_profiles"] == ["biology", "default"]
    assert prof["notebook_assignments"] == {NB: "biology"}
    other = await call(mcp_client, "get_study_profile", notebook_id="unassigned")
    assert other["profile"] == "default" and other["reading_style"] == "Plain English"
    # generation for this notebook uses the biology profile
    await call(mcp_client, "generate_quiz", notebook_id=NB)
    assert "Name the organelle" in fake.rec.last("artifacts.generate_quiz")[1]["instructions"]
    with pytest.raises(ToolError, match="Profile names"):
        await mcp_client.call_tool("update_study_profile", {"profile": "../etc"})


# ------------------------------------------------------------------ weak spots
async def test_record_and_use_weak_spots(mcp_client, fake, store):
    empty = await call(mcp_client, "get_study_progress", notebook_id=NB)
    assert empty["has_history"] is False
    await call(
        mcp_client,
        "record_quiz_result",
        notebook_id=NB,
        score=6,
        total=10,
        topic="Respiration",
        missed_topics=["Krebs cycle", "ATP yield"],
        covered_topics=["Glycolysis"],
    )
    summary = await call(
        mcp_client,
        "record_quiz_result",
        notebook_id=NB,
        score=8,
        total=10,
        missed_topics=["krebs cycle"],
        covered_topics=["ATP yield"],
    )
    assert summary["sessions"] == 2 and summary["average_score_pct"] == 70
    weak = [w["topic"] for w in summary["weak_spots"]]
    assert weak[0] == "Krebs cycle"  # missed 2/2, labels merged case-insensitively
    assert "ATP yield" in weak  # missed 1/2
    assert "Glycolysis" not in weak

    pack = await call(mcp_client, "build_study_pack", notebook_id=NB)
    assert pack["progress"]["weak_spots"][0]["topic"] == "Krebs cycle"
    assert "Krebs cycle" in fake.rec.last("chat.ask")[0][1]  # explanation targets weak spots

    if sys.platform != "win32":
        path = ProgressStore(store.home).path
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(ToolError):
        await mcp_client.call_tool(
            "record_quiz_result", {"notebook_id": NB, "score": 11, "total": 10}
        )


# ------------------------------------------------------------------ upstream issue checks
def test_rpc_timeout_maps_to_clear_message():
    # alfredang/notebooklm-mcp#5 (ask hangs): the library bounds chat reads; make sure the
    # timeout surfaces as a clear message rather than a generic error.
    err = to_tool_error(nlm.RPCTimeoutError("read timed out"))
    assert "Timed out" in str(err)


async def test_read_only_server_still_offers_document_tools(fake, store):
    async with Client(make_server(fake, store, read_only=True)) as c:
        out = await call(c, "ask_notebook_batch", notebook_id=NB, prompts_list=["x"])
        assert out["results"][0]["answer"]


# ------------------------------------------------------------------ skill stays in sync
async def test_skill_references_only_real_tools(mcp_client):
    import re
    from pathlib import Path

    skill = Path(__file__).parent.parent / "skills" / "notebooklm-study" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    front = text.split("---")[1]
    assert re.search(r"^name: notebooklm-study$", front, re.M)
    assert re.search(r"^description: .{40,}", front, re.M)

    tools = {t.name for t in await mcp_client.list_tools()}
    prompt_names = {p.name for p in await mcp_client.list_prompts()}
    fields = {
        "reading_style",
        "quiz_example",
        "learner_context",
        "quiz_preferences",
        "assign_to_notebooks",
        "source_ids",
    }
    referenced = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", text))
    unknown = referenced - tools - prompt_names - fields
    assert not unknown, f"SKILL.md mentions unknown tools: {sorted(unknown)}"
    # the core workflow tools must be documented
    assert {
        "ask_notebook_batch",
        "finalize_citations",
        "build_study_pack",
        "record_quiz_result",
        "save_answer_as_note",
    } <= referenced

"""Test fixtures: a fake NotebookLM client that returns the library's REAL data types.

Using real dataclasses (AskResult, Source, Artifact, ...) means attribute mistakes like
the original ``result.text`` bug fail here instead of in Claude Desktop.
"""

import json
from pathlib import Path
from typing import Any

import notebooklm as nlm
import pytest
from fastmcp import Client

from notebooklm_study_mcp.client import ClientProvider
from notebooklm_study_mcp.profile import ProfileStore
from notebooklm_study_mcp.server import build_server

NB = "nb1"
S1 = "3f9a2c1b-0000-4000-8000-000000000001"
S2 = "7d4e8a90-0000-4000-8000-000000000002"
SRC = nlm.Source(
    id=S1,
    title="Cell Biology Ch.1",
    status=nlm.SourceStatus.READY,
    url="https://example.com/cells",
)
SRC2 = nlm.Source(id=S2, title="Metabolism Notes", status=nlm.SourceStatus.READY)
QUIZ_JSON = {
    "title": "Cells quiz",
    "questions": [
        {
            "question": "What is the powerhouse of the cell?",
            "answerOptions": [
                {"text": "Mitochondria", "isCorrect": True, "rationale": "Makes ATP."},
                {"text": "Nucleus", "isCorrect": False},
            ],
            "hint": "Think ATP.",
        }
    ],
}


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def last(self, name: str) -> tuple[tuple, dict]:
        for n, a, k in reversed(self.calls):
            if n == name:
                return a, k
        raise AssertionError(f"{name} was not called")


class _Api:
    def __init__(self, rec: Recorder, prefix: str) -> None:
        self._rec, self._prefix = rec, prefix


class Notebooks(_Api):
    async def list(self):
        self._rec.record("notebooks.list")
        return [nlm.Notebook(id=NB, title="Biology", sources_count=1)]

    async def get(self, notebook_id):
        if notebook_id != NB:
            raise nlm.NotebookNotFoundError(notebook_id)
        return nlm.Notebook(id=NB, title="Biology", sources_count=1)

    async def get_description(self, notebook_id):
        return nlm.NotebookDescription(
            summary="All about cells.",
            suggested_topics=[nlm.SuggestedTopic(question="What is ATP?", prompt="p")],
        )

    async def create(self, title):
        self._rec.record("notebooks.create", title)
        return nlm.Notebook(id="new", title=title)


class Sources(_Api):
    async def list(self, notebook_id):
        return [SRC, SRC2]

    async def get_guide(self, notebook_id, source_id):
        return nlm.SourceGuide(summary="Cells are units of life.", keywords=("cell", "ATP"))

    async def get_fulltext(self, notebook_id, source_id, output_format="text"):
        return nlm.SourceFulltext(source_id=source_id, title=SRC.title, content="x" * 1500)

    async def add_url(self, notebook_id, url, *, wait=False, wait_timeout=120.0):
        self._rec.record("sources.add_url", notebook_id, url, wait=wait)
        return nlm.Source(id="s2", title=url, status=nlm.SourceStatus.READY, url=url)

    async def add_text(self, notebook_id, title, content, *, wait=False, wait_timeout=120.0):
        self._rec.record("sources.add_text", notebook_id, title, content, wait=wait)
        return nlm.Source(id="s3", title=title, status=nlm.SourceStatus.PROCESSING)

    async def add_drive(
        self, notebook_id, file_id, title, mime_type, *, wait=False, wait_timeout=120.0
    ):
        self._rec.record("sources.add_drive", notebook_id, file_id, title, mime_type)
        return nlm.Source(id="s4", title=title, status=nlm.SourceStatus.READY)


class Chat(_Api):
    async def ask(self, notebook_id, question, source_ids=None, conversation_id=None):
        self._rec.record(
            "chat.ask",
            notebook_id,
            question,
            source_ids=source_ids,
            conversation_id=conversation_id,
        )
        if "FAIL" in question:
            raise nlm.RateLimitError("quota")
        if "two sources" in question:
            return nlm.AskResult(
                answer="Glycolysis happens in the cytosol [1]. The Krebs cycle runs in the "
                "mitochondria [2]. Published in [2024].",
                conversation_id="conv1",
                turn_number=1,
                is_follow_up=False,
                references=[
                    nlm.ChatReference(source_id=S2, citation_number=1),
                    nlm.ChatReference(source_id=S1, citation_number=2),
                ],
            )
        return nlm.AskResult(
            answer="Mitochondria make ATP [1].",
            conversation_id="conv1",
            turn_number=1,
            is_follow_up=conversation_id is not None,
            references=[
                nlm.ChatReference(
                    source_id=S1, citation_number=1, cited_text="The mitochondria..."
                ),
                nlm.ChatReference(source_id=S1, citation_number=1, cited_text="dup"),
            ],
            next_steps=[nlm.NextStepSuggestion(question="What is ATP?", type_code=1)],
        )

    async def save_answer_as_note(self, notebook_id, ask_result, *, title=None):
        self._rec.record("chat.save_answer_as_note", notebook_id, ask_result, title=title)
        return nlm.Note(
            id="n9", notebook_id=notebook_id, title=title or "Chat: ...", content=ask_result.answer
        )


class Notes(_Api):
    async def list(self, notebook_id):
        return [nlm.Note(id="n1", notebook_id=NB, title="Summary", content="Long " * 100)]

    async def get(self, notebook_id, note_id):
        return nlm.Note(id=note_id, notebook_id=NB, title="Summary", content="Body")

    async def create(self, notebook_id, title="New Note", content=""):
        self._rec.record("notes.create", notebook_id, title, content)
        return nlm.Note(id="n2", notebook_id=NB, title=title, content=content)


class Research(_Api):
    task = nlm.ResearchTask(
        task_id="r1",
        status=nlm.types.ResearchStatus.COMPLETED,
        query="cells",
        sources=(
            nlm.ResearchSource(url="https://a.example", title="A"),
            nlm.ResearchSource(url="https://b.example", title="B"),
        ),
        summary="Found 2",
        report="",
    )

    async def start(self, notebook_id, query, source="web", mode="fast"):
        self._rec.record("research.start", notebook_id, query, source=source, mode=mode)
        return nlm.ResearchStart(
            task_id="r1", report_id=None, notebook_id=notebook_id, query=query, mode=mode
        )

    async def poll(self, notebook_id, task_id=None):
        return self.task

    async def import_sources(self, notebook_id, task_id, sources):
        self._rec.record("research.import_sources", notebook_id, task_id, list(sources))
        return [{"id": f"i{i}", "title": s.title} for i, s in enumerate(sources)]


class Artifacts(_Api):
    def _status(self, kind: str) -> nlm.GenerationStatus:
        return nlm.GenerationStatus(task_id=f"t-{kind}", status=nlm.GenerationState.PENDING)

    def __getattr__(self, name: str):
        if name.startswith("generate_"):

            async def gen(notebook_id, **kwargs):
                self._rec.record(f"artifacts.{name}", notebook_id, **kwargs)
                if name == "generate_mind_map":
                    return nlm.MindMapResult(mind_map={"name": "Cells"}, note_id="mm1")
                return self._status(name.removeprefix("generate_"))

            return gen
        raise AttributeError(name)

    async def list(self, notebook_id, artifact_type=None):
        return [
            nlm.Artifact(id="q1", title="Cells quiz", _artifact_type=4, _variant=2, status=3),
            nlm.Artifact(id="a1", title="Podcast", _artifact_type=1, status=3),
            nlm.Artifact(id="p1", title="Pending report", _artifact_type=2, status=2),
        ]

    async def get(self, notebook_id, artifact_id):
        for a in await self.list(notebook_id):
            if a.id == artifact_id:
                return a
        raise nlm.ArtifactNotFoundError(artifact_id)

    async def wait_for_completion(self, notebook_id, task_id, timeout=300.0, **_):
        if task_id == "slow":
            raise nlm.WaitTimeoutError("still going")
        return nlm.GenerationStatus(task_id=task_id, status=nlm.GenerationState.COMPLETED)

    async def download_quiz(self, notebook_id, output_path, artifact_id=None, output_format="json"):
        self._rec.record("artifacts.download_quiz", output_path)
        Path(output_path).write_text(json.dumps(QUIZ_JSON), encoding="utf-8")
        return output_path

    async def download_flashcards(
        self, notebook_id, output_path, artifact_id=None, output_format="json"
    ):
        raise nlm.ArtifactNotFoundError("none")


class FakeClient:
    def __init__(self) -> None:
        self.rec = Recorder()
        self.notebooks = Notebooks(self.rec, "notebooks")
        self.sources = Sources(self.rec, "sources")
        self.chat = Chat(self.rec, "chat")
        self.notes = Notes(self.rec, "notes")
        self.research = Research(self.rec, "research")
        self.artifacts = Artifacts(self.rec, "artifacts")

    async def get_account_email(self, *, live_fallback=True):
        return "study@example.com"


class _FakeCM:
    def __init__(self, client: Any) -> None:
        self.client = client

    async def __aenter__(self):
        if isinstance(self.client, BaseException):
            raise self.client
        return self.client

    async def __aexit__(self, *exc):
        return None


@pytest.fixture
def fake() -> FakeClient:
    return FakeClient()


@pytest.fixture
def store(tmp_path) -> ProfileStore:
    return ProfileStore(tmp_path / "home")


def make_server(client_or_exc: Any, store: ProfileStore, **kw):
    return build_server(ClientProvider(lambda: _FakeCM(client_or_exc)), store, **kw)


@pytest.fixture
async def mcp_client(fake, store):
    async with Client(make_server(fake, store)) as c:
        yield c


async def call(client: Client, tool: str, **args: Any) -> Any:
    result = await client.call_tool(tool, args)
    return result.data if result.data is not None else result.structured_content

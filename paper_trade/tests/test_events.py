import json

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from paper_trade import events


class State(TypedDict, total=False):
    out: str


def test_feed_tags_llm_and_tool_calls_with_the_graph_node(tmp_path):
    path = tmp_path / "feed.jsonl"
    handler = events.install(path)
    handler.set_cell("AAPL", "2026-09-02")
    model = FakeListChatModel(responses=["Overweight, momentum is constructive."])

    @tool
    def get_close(ticker: str) -> str:
        """price"""
        return "123"

    def market_analyst(state: State) -> State:
        get_close.invoke({"ticker": "AAPL"})
        return {"out": model.invoke("rate AAPL").content}

    graph = StateGraph(State)
    graph.add_node("Market Analyst", market_analyst)
    graph.add_edge(START, "Market Analyst")
    graph.add_edge("Market Analyst", END)
    assert graph.compile().invoke({})["out"].startswith("Overweight")

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    kinds = {row["kind"]: row for row in rows}
    assert kinds["llm"]["node"] == "Market Analyst"
    assert "Overweight" in kinds["llm"]["text"]
    assert kinds["llm"]["cell"] == "AAPL 2026-09-02"
    assert kinds["tool"]["tool"] == "get_close" and kinds["tool"]["node"] == "Market Analyst"
    events._HANDLER.set(None)


def test_subgraph_agents_are_named_by_their_outer_node(tmp_path):
    path = tmp_path / "feed.jsonl"
    events.install(path)
    model = FakeListChatModel(responses=["Buy"])

    def agent(state: State) -> State:               # the inner node is just called "agent"
        return {"out": model.invoke("rate").content}

    inner = StateGraph(State)
    inner.add_node("agent", agent)
    inner.add_edge(START, "agent")
    inner.add_edge("agent", END)
    outer = StateGraph(State)
    outer.add_node("News Analyst", inner.compile())
    outer.add_edge(START, "News Analyst")
    outer.add_edge("News Analyst", END)
    outer.compile().invoke({})

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["node"] for row in rows if row["kind"] == "llm"] == ["News Analyst"]
    events._HANDLER.set(None)


def test_long_answers_are_recorded_in_full(tmp_path):
    path = tmp_path / "feed.jsonl"
    events.install(path)
    long_answer = "Rating: Underweight. " + "The debate favours caution. " * 300      # about 8,500 characters
    model = FakeListChatModel(responses=[long_answer])
    model.invoke("go")
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert row["text"] == long_answer
    events._HANDLER.set(None)


def test_each_call_records_its_response_time_in_milliseconds(tmp_path):
    path = tmp_path / "feed.jsonl"
    events.install(path)
    FakeListChatModel(responses=["ok"], sleep=0.05).invoke("go")
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert isinstance(row["ms"], int) and row["ms"] >= 50
    assert abs(row["seconds"] - row["ms"] / 1000) <= 0.06
    events._HANDLER.set(None)


def test_nothing_is_written_when_no_feed_is_installed(tmp_path):
    events._HANDLER.set(None)
    model = FakeListChatModel(responses=["ok"])
    assert model.invoke("hi").content == "ok"
    assert not list(tmp_path.iterdir())

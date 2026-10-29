import io
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from paper_trade.dashboard import server, stream


@pytest.fixture
def running(monkeypatch):
    """The real dashboard server on a free local port, with every data read faked."""
    monkeypatch.setitem(server.ROUTES, "/api/boom", lambda run, query: 1 / 0)
    monkeypatch.setitem(server.ROUTES, "/api/echo", lambda run, query: {"run": run, "query": {k: v[0] for k, v in query.items()}})
    monkeypatch.setattr(server.stream, "serve", lambda wfile, run, mode: wfile.write(f"event: hello\ndata: {run} {mode}\n\n".encode()))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler("live_gemma_short"))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as reply:
            return reply.status, reply.headers.get("Content-Type"), reply.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type"), error.read()


def test_the_pages_and_page_files_are_served_with_the_right_types(running):
    status, kind, body = get(running + "/")
    assert status == 200 and kind.startswith("text/html") and b"Paper Trading Live" in body
    assert get(running + "/charts")[0] == 200
    status, kind, body = get(running + "/static/main.js")
    assert status == 200 and kind.startswith("text/javascript") and b"startStream" in body
    assert get(running + "/static/styles.css")[1].startswith("text/css")


def test_names_that_are_not_page_files_are_refused(running):
    assert get(running + "/static/../config.py")[0] == 404
    assert get(running + "/static/nothing.js")[0] == 404
    assert get(running + "/static/server.py")[0] == 404
    assert get(running + "/nope")[0] == 404


def test_the_api_returns_the_wrapper_and_a_bad_read_does_not_kill_the_page(running):
    status, kind, body = get(running + "/api/echo?run=abc&x=1")
    assert status == 200 and json.loads(body) == {"ok": True, "data": {"run": "abc", "query": {"run": "abc", "x": "1"}}}
    assert json.loads(get(running + "/api/echo")[2])["data"]["run"] == "live_gemma_short"          # the default run
    broken = json.loads(get(running + "/api/boom")[2])
    assert broken["ok"] is False and "division by zero" in broken["error"]


def test_the_live_stream_is_an_event_stream(running):
    status, kind, body = get(running + "/api/stream?run=r1&mode=fixed_lot")
    assert status == 200 and kind.startswith("text/event-stream") and body == b"event: hello\ndata: r1 fixed_lot\n\n"


# --- the push stream itself ---

def test_a_message_carries_the_state_or_the_error(monkeypatch):
    monkeypatch.setattr(stream, "build_state", lambda run, mode: {"run": run, "mode": mode})
    ok = stream.message("r", "fixed_lot").decode()
    assert ok.startswith("event: state\ndata: ") and json.loads(ok.split("data: ")[1])["data"] == {"run": "r", "mode": "fixed_lot"}
    monkeypatch.setattr(stream, "build_state", lambda run, mode: 1 / 0)
    assert json.loads(stream.message("r", "m").decode().split("data: ")[1])["ok"] is False


def test_the_signature_changes_when_a_watched_file_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(stream, "run_dir", lambda run: tmp_path)
    before = stream.signature("r")
    assert before == (None, None, None, None)
    (tmp_path / "events.jsonl").write_text("x", encoding="utf-8")
    assert stream.signature("r") != before


def test_the_stream_sends_state_then_keep_alives_and_stops_when_the_page_goes_away(monkeypatch, tmp_path):
    monkeypatch.setattr(stream, "run_dir", lambda run: tmp_path)
    monkeypatch.setattr(stream, "build_state", lambda run, mode: {})
    monkeypatch.setattr(stream.time, "sleep", lambda seconds: None)

    class Page(io.BytesIO):
        writes = 0

        def write(self, data):
            Page.writes += 1
            if Page.writes > 3:
                raise BrokenPipeError
            return super().write(data)

    page = Page()
    stream.serve(page, "r", "fixed_lot")
    sent = page.getvalue()
    assert sent.startswith(b"event: state") and b": keep-alive" in sent

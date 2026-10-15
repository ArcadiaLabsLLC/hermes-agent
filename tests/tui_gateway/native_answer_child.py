"""Real compute protocol fixture; only question creation is seeded."""
import sys

wire = sys.stdout

from tui_gateway import server, server_requests
from tui_gateway.compute_host import run_host


def main():
    session = server._deferred_session_record(
        "answer-session", cols=80, cwd=".", history=[], lease=None, lazy=True)
    server._sessions["answer-session"] = session
    server._sessions["other-session"] = {**session, "session_key": "other-session"}
    request = server_requests.ServerRequest("answer-session", "clarify", {"question": "Continue?"})
    request.id = "native-question"
    with server_requests._lock:
        server_requests._open[request.id] = request
    run_host(stdout=wire)


if __name__ == "__main__":
    main()

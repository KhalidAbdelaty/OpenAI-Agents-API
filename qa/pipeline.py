"""One Agents API session: buggy release, browser QA, verdict, fix, same-session retest.

run_experiment() is a generator. The CLI prints its events and the Streamlit app renders
them. Every event is also appended to runs/<run_id>/events.jsonl.
"""

import base64
import json
import time
import urllib.request
from datetime import datetime
from urllib.parse import urlsplit

from openai import APIStatusError, OpenAI

from qa.config import (BUGGY_BUILD, FIXED_BUILD, INSTRUCTIONS, MODEL, PRICES, QA_OBJECTIVE,
                       REASONING_EFFORT, RECORD_QA_RESULT, RETEST, RUNS)
from qa.verdict import judge, no_record

TERMINAL_FAILURES = {"agent.session.turn.failed", "agent.session.turn.cancelled",
                     "agent.session.failed", "agent.session.environment.failed", "error"}


class Recorder:
    """Stamps events with elapsed seconds and appends them to events.jsonl."""

    def __init__(self, run_dir):
        self.run_dir, self.start = run_dir, time.monotonic()
        self.log = (run_dir / "events.jsonl").open("a", encoding="utf-8")

    def __call__(self, kind, **fields):
        event = {"t": round(time.monotonic() - self.start, 2), "type": kind, **fields}
        self.log.write(json.dumps(event) + "\n")
        self.log.flush()
        return event

    def save(self, name, data):
        (self.run_dir / name).write_text(json.dumps(data, indent=2), encoding="utf-8")


def read_build(staging_url, build):
    """Confirm which release the staging host serves before a turn starts."""
    with urllib.request.urlopen(f"{staging_url}/b/{build}/build.json", timeout=20) as response:
        return json.load(response)["build"]


def message(text):
    return {"type": "agent.session.input.message",
            "input": [{"role": "user", "content": [{"type": "input_text", "text": text}]}]}


def wait_for_usage(fetch, limit=120):
    """Usage is best-effort and can be null right after a turn ends. Poll, then give up."""
    began = time.time()
    while True:
        usage = fetch().usage
        if usage is not None or time.time() - began > limit:
            return (usage.to_dict() if usage else None), round(time.time() - began, 1)
        time.sleep(5)


def estimate_cost(usage):
    """Usage-based estimate at standard rates. Usage has no cache-write counter."""
    if not usage:
        return None
    cached = usage["input_tokens_details"]["cached_tokens"]
    uncached = usage["input_tokens"] - cached
    return round((uncached * PRICES["input"] + cached * PRICES["cached"]
                  + usage["output_tokens"] * PRICES["output"]) / 1_000_000, 4)


class QATurn:
    """Runs one root turn: streams events, answers approvals, executes record_qa_result."""

    def __init__(self, client, session_id, origin, rec, label, build):
        self.client, self.session_id, self.origin = client, session_id, origin
        self.rec, self.label, self.build = rec, label, build
        self.turn_id, self.record, self.result, self.last_shot = None, None, None, None
        self.handled, self.completed, self.approvals = set(), False, []

    def run(self, text):
        sent = False
        while not self.completed:
            with self.client.beta.agents.sessions.events.stream(self.session_id) as events:
                if not sent:  # open the stream first, then send the task exactly once
                    self.client.beta.agents.sessions.events.create(self.session_id, events=[message(text)])
                    sent = True
                    yield self.rec("turn", label=self.label, status="sent", build=self.build)
                else:  # reconnected: act on what is still pending, never resend the task
                    yield from self.handle_required_actions()
                for event in events:
                    yield from self.handle(event)
                    if self.completed:
                        break
            if not self.completed:
                yield self.rec("note", text="Stream closed early. Retrieving the session before continuing.")
                status = self.client.beta.agents.sessions.retrieve(self.session_id).status
                if status == "idle" and self.turn_id:
                    turn = self.client.beta.agents.sessions.turns.retrieve(self.turn_id, session_id=self.session_id)
                    self.completed = turn.status == "completed"
                    if turn.status in ("failed", "cancelled"):
                        raise RuntimeError(f"Turn {self.turn_id} ended: {turn.status}")

    def handle(self, event):
        kind = event.type
        if kind == "agent.session.turn.created" and event.turn.subagent_id is None and not self.turn_id:
            self.turn_id = event.turn.id
            yield self.rec("turn", label=self.label, status="created", turn_id=self.turn_id)
        elif kind == "agent.session.turn.item.done" and event.item.type == "computer_use_call":
            item = event.item
            if item.output is not None:
                self.last_shot = item.id
            yield self.rec("browser", label=self.label, item_id=item.id, title=item.title,
                           status=item.status, screenshot=item.output is not None)
        elif kind == "agent.session.requires_action":
            yield from self.handle_required_actions()
        elif kind == "agent.session.turn.output_text.done":
            yield self.rec("agent_text", label=self.label, text=event.text)
        elif kind == "agent.session.environment.reset":
            yield self.rec("note", text=f"Hosted environment replaced (reset_count={event.reset_count}).")
        elif kind == "agent.session.turn.completed" and event.turn.subagent_id is None:
            self.completed = True
            yield self.rec("turn", label=self.label, status="completed", turn_id=event.turn.id)
        elif kind in TERMINAL_FAILURES:
            if kind.startswith("agent.session.turn.") and event.turn.subagent_id is not None:
                return
            yield self.rec("error", text=kind)
            raise RuntimeError(f"{self.label}: {kind}")

    def handle_required_actions(self):
        # The event says when to look. The retrieved session says what is pending.
        session = self.client.beta.agents.sessions.retrieve(self.session_id)
        for action in session.required_actions:
            if action.type == "computer_use_approval_request" and action.request_id not in self.handled:
                self.handled.add(action.request_id)
                yield from self.answer_approval(action)
            elif action.type == "function_call" and action.call_id not in self.handled:
                self.handled.add(action.call_id)
                yield from self.run_function(action)

    def answer_approval(self, action):
        request = action.request
        if request.type == "browser_origin_access":
            decision = "approve" if request.origin.rstrip("/") == self.origin else "deny"
            response = {"type": "browser_origin_access", "decision": decision}
            yield self.rec("approval", label=self.label, origin=request.origin,
                           reason=request.reason, decision=decision)
        else:  # browser_authentication: Northstar has no login, so sign-in is refused
            response = {"type": "browser_authentication", "action": "cancel"}
            yield self.rec("approval", label=self.label, origin=request.credential_origin,
                           reason=request.reason, decision="cancel sign-in")
        self.approvals.append({"request_id": action.request_id, "type": request.type, **response})
        self.client.beta.agents.sessions.events.create(self.session_id, events=[{
            "type": "agent.session.input.computer_use_approval_request_result",
            "request_id": action.request_id, "response": response}])

    def run_function(self, action):
        reply = {"type": "agent.session.input.tool_result",
                 "turn_id": action.turn_id, "call_id": action.call_id}
        if action.name != "record_qa_result":
            reply.update(success=False, error=f"Unknown function {action.name}")
        else:
            args = action.arguments if isinstance(action.arguments, dict) else json.loads(action.arguments)
            self.record = {**args, "session_id": self.session_id, "turn_id": action.turn_id,
                           "release": self.build,
                           "evidence_id": f"ev-{self.label}-{action.call_id[-8:]}",
                           "evidence_item_id": self.last_shot}
            self.result = judge(args)
            yield self.rec("qa_record", label=self.label, record=self.record, result=self.result)
            reply.update(success=True, output=json.dumps({
                "verdict": self.result["verdict"], "failed_checks": self.result["failed_checks"],
                "evidence_id": self.record["evidence_id"]}))
        self.client.beta.agents.sessions.events.create(self.session_id, events=[reply])


def save_turn_items(client, session_id, turn_id, label, rec):
    """Archive the turn's items. Screenshots go to shots/, never into the JSON log."""
    shots_dir = rec.run_dir / "shots"
    shots_dir.mkdir(exist_ok=True)
    items, shots = [], []
    for item in client.beta.agents.sessions.items.list(session_id, order="asc", limit=100):
        data = item.to_dict()
        if data.get("turn_id") != turn_id:
            continue
        output = data.get("output")
        if data["type"] == "computer_use_call" and isinstance(output, dict) and output.get("image_url"):
            header, _, payload = output["image_url"].partition(",")
            name = f"{label}-{len(shots) + 1:02d}-{data['id'][-8:]}.jpg"
            (shots_dir / name).write_bytes(base64.b64decode(payload))
            data["output"] = {"type": output["type"], "file": f"shots/{name}"}
            shots.append({"file": f"shots/{name}", "item_id": data["id"], "title": data.get("title"),
                          "status": data.get("status")})
        items.append(data)
    rec.save(f"items_{label}.json", items)
    return items, shots


def run_experiment(staging_url):
    staging_url = staging_url.rstrip("/")
    parts = urlsplit(staging_url)
    origin, host = f"{parts.scheme}://{parts.netloc}", parts.hostname
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True)
    rec = Recorder(run_dir)
    client = OpenAI()
    summary = {"run_id": run_id, "model": MODEL, "reasoning_effort": REASONING_EFFORT,
               "staging_url": staging_url, "allowed_domains": [host], "turns": {}}
    started = time.time()

    yield rec("phase", name="Create session")
    session = client.beta.agents.sessions.create(
        agent={"model": MODEL, "instructions": INSTRUCTIONS,
               "reasoning": {"effort": REASONING_EFFORT},  # "medium", set explicitly
               "tools": [{"type": "computer_use", "include_screenshots": True}, RECORD_QA_RESULT]},
        environment={"type": "openai_hosted", "desktop": {"enabled": True},
                     "network": {"access": "restricted", "allowed_domains": [host]}},
        metadata={"experiment": "northstar-browser-qa"},
    )
    summary.update(session_id=session.id, session_created_at=session.created_at,
                   environment=session.environment.to_dict())
    yield rec("session", session_id=session.id, environment_id=session.environment.id,
              network=summary["environment"].get("network"))

    for label, build, template in (("run1", BUGGY_BUILD, QA_OBJECTIVE), ("retest", FIXED_BUILD, RETEST)):
        served = read_build(staging_url, build)
        start_url = f"{staging_url}/b/{build}/?reset=1"
        yield rec("phase", name=f"{label}: build {served}")
        yield rec("release", label=label, build=served, start_url=start_url,
                  reset="?reset=1 clears the cart and route state; each build has its own path")
        turn = QATurn(client, session.id, origin, rec, label, served)
        began = time.time()
        yield from turn.run(template.format(build=served, url=start_url))
        ended = time.time()

        result, record = turn.result, turn.record
        if record is None:
            result = no_record()
            yield rec("qa_record", label=label, record=None, result=result)
        items, shots = save_turn_items(client, session.id, turn.turn_id, label, rec)
        usage, usage_wait = wait_for_usage(
            lambda: client.beta.agents.sessions.turns.retrieve(turn.turn_id, session_id=session.id))
        current = client.beta.agents.sessions.retrieve(session.id)
        summary["turns"][label] = {
            "build": served, "turn_id": turn.turn_id, "session_id": session.id,
            "environment_id": current.environment.id, "record": record, "result": result,
            "approvals": turn.approvals,
            "browser_items": sum(1 for i in items if i["type"] == "computer_use_call"),
            "screenshots": shots, "usage": usage, "usage_wait_seconds": usage_wait,
            "usage_cost_estimate": estimate_cost(usage),
            "wall_seconds": round(ended - began, 1), "started_at": began, "ended_at": ended}
        yield rec("usage", label=label, usage=usage, estimate=estimate_cost(usage), waited=usage_wait)
        yield rec("verdict", label=label, verdict=result["verdict"], result=result)

    first, second = summary["turns"]["run1"], summary["turns"]["retest"]
    summary["same_session"] = first["session_id"] == second["session_id"]
    summary["same_environment"] = first["environment_id"] == second["environment_id"]
    summary["session_usage"], _ = wait_for_usage(lambda: client.beta.agents.sessions.retrieve(session.id))
    summary["session_usage_cost_estimate"] = estimate_cost(summary["session_usage"])
    rec.save("summary.json", summary)  # save everything before deleting anything
    yield rec("phase", name="Delete session")

    for attempt in range(5):
        try:
            deleted = client.beta.agents.sessions.delete(session.id)
            summary["deleted"] = {"deleted": deleted.deleted, "at": time.time()}
            break
        except APIStatusError as err:
            if err.status_code != 409 or attempt == 4:
                summary["deleted"] = {"deleted": False, "error": str(err.status_code)}
                break
            time.sleep(5 * (attempt + 1))
    summary["session_lifetime_minutes"] = round((time.time() - started) / 60, 1)
    rec.save("summary.json", summary)
    yield rec("done", run_id=run_id, verdicts={k: v["result"]["verdict"] for k, v in summary["turns"].items()})

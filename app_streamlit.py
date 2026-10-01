"""Streamlit front end for the Northstar Checkout browser QA experiment.

    streamlit run app_streamlit.py

"Replay a recorded run" renders the newest run under runs/ and makes no API call.
"Run live" starts the same pipeline as run_qa.py, bills the .env key, and streams its events.
"""

import base64
import json
import os
from datetime import datetime
from html import escape
from pathlib import Path

import streamlit as st

from qa.config import EXPECTED, MODEL, PRICES, ROOT, RUNS, STAGING_URL

ASSETS = ROOT / "assets"
DATACAMP_LOGO = ASSETS / "datacamp-logo.png"              # navy wordmark, for white backgrounds
DATACAMP_LOGO_WHITE = ASSETS / "datacamp-logo-white.png"  # white wordmark, for the navy sidebar
OPENAI_MARK_WHITE = ASSETS / "openai-logo-white.png"
DATACAMP_URL = "https://www.datacamp.com/blog"

STAGES = [
    ("QA goal", "The agent gets acceptance criteria for one checkout journey, not a click script. The planted bug is never mentioned."),
    ("Hosted browser", "One Agents API session runs gpt-6-astra with Computer Use in an OpenAI-hosted desktop, restricted to the staging host."),
    ("Origin approval", "The harness approves only the Northstar staging origin. Any other origin is denied and sign-in is cancelled."),
    ("Harness verdict", "The agent calls record_qa_result with the build id and separate cart and review values. Application code checks the build, then compares the values with the answer key."),
    ("Fix", "Build ns-1042 changes one line: the review subtotal multiplies by quantity. Instructions, tool, and session stay the same."),
    ("Same-session retest", "A follow-up message on the same session reruns the objective from an empty cart. Artifacts are saved, then the session is deleted."),
]
LABELS = {"run1": "Buggy release", "retest": "Retest after fix"}
FIELDS = [("Cart quantity", "cart_quantity", "cart_quantity", False),
          ("Cart subtotal", "cart_subtotal", "cart_subtotal_cents", True),
          ("Review quantity", "review_quantity", "review_quantity", False),
          ("Review subtotal", "review_subtotal", "review_subtotal_cents", True)]
LOG_KINDS = {
    "Phases": {"phase", "turn", "done"},
    "Session and release": {"session", "release"},
    "Browser activity": {"browser"},
    "Origin approval": {"approval"},
    "QA function": {"qa_record", "verdict"},
    "Tokens": {"usage"},
    "Agent messages": {"agent_text"},
    "Notes and errors": {"note", "error"},
}
PILL = {"pass": ("ok", "Pass"), "fail": ("bad", "Fail"), "incomplete": ("warn", "Incomplete")}


# ---------- helpers ----------

def b64(path):
    return base64.b64encode(path.read_bytes()).decode() if path.is_file() else ""


def recorded_runs():
    return sorted((p for p in RUNS.glob("2*") if (p / "summary.json").exists()), reverse=True)


def run_label(path):
    try:
        return datetime.strptime(path.name, "%Y%m%d-%H%M%S").strftime("%d %b %Y, %H:%M:%S")
    except ValueError:
        return path.name


def md(text):
    """Streamlit Markdown treats $...$ as math, so escape dollar signs in prose."""
    return str(text).replace("$", "\\$")


def dollars(cents):
    return "not seen" if cents is None else f"${cents / 100:.2f}"


def pill(verdict):
    css, text = PILL.get(verdict, PILL["incomplete"])
    return f"<span class='pill {css}'>{text}</span>"


def short(value, keep=10):
    prefix, _, rest = (value or "").partition("_")
    return f"{prefix}_…{rest[-keep:]}" if len(rest) > keep + 4 else (value or "–")


def event_row(event):
    """(category, tag, escaped HTML body) for one pipeline event, or None to skip it."""
    kind = event["type"]
    if kind == "phase":
        return "Phases", "phase", f"<b>{escape(event['name'])}</b>"
    if kind == "turn":
        return "Phases", "turn", f"{escape(LABELS.get(event['label'], event['label']))}: turn {escape(event['status'])}"
    if kind == "session":
        hosts = ", ".join((event.get("network") or {}).get("allowed_domains") or [])
        return "Session and release", "session", f"Session <code>{escape(short(event['session_id']))}</code> · restricted to {escape(hosts)}"
    if kind == "release":
        return "Session and release", "release", f"Build <b>{escape(event['build'])}</b> · start <code>{escape(event['start_url'])}</code>"
    if kind == "browser":
        shot = " · screenshot" if event.get("screenshot") else ""
        status = event["status"] if event["status"] == "completed" else f"<span class='bad'>{escape(event['status'])}</span>"
        return "Browser activity", "browser", f"{escape(event['title'] or 'Browser activity')} · {status}{shot}"
    if kind == "approval":
        return "Origin approval", "approval", f"<b>{escape(event['decision'])}</b> <code>{escape(str(event['origin']))}</code>"
    if kind == "qa_record":
        r = event.get("record")
        if not r:
            return "QA function", "qa", "<span class='bad'>record_qa_result never arrived · fallback verdict</span>"
        return ("QA function", "qa", f"<code>record_qa_result</code> cart {escape(str(r.get('cart_quantity')))} · "
                f"{escape(str(r.get('cart_subtotal')))} · review {escape(str(r.get('review_quantity')))} · "
                f"{escape(str(r.get('review_subtotal')))}")
    if kind == "verdict":
        return "QA function", "verdict", f"Harness verdict for {escape(LABELS.get(event['label'], event['label']))}: {pill(event['verdict'])}"
    if kind == "usage":
        u = event.get("usage")
        if not u:
            return "Tokens", "usage", "Usage not reported yet (best-effort field)"
        return ("Tokens", "usage", f"in {u['input_tokens']:,} · cached {u['input_tokens_details']['cached_tokens']:,} · "
                f"out {u['output_tokens']:,} · estimate ${event['estimate']:.4f}")
    if kind == "agent_text":
        text = event["text"]
        return "Agent messages", "agent", escape(text if len(text) <= 500 else text[:500] + "…")
    if kind in ("note", "error"):
        return "Notes and errors", kind, f"<span class='bad'>{escape(event['text'])}</span>"
    if kind == "done":
        return "Phases", "done", "<b>Run finished · session deleted after artifacts were saved</b>"
    return None


def log_html(events, kinds=None):
    rows = []
    for event in events:
        row = event_row(event)
        if row and (kinds is None or row[0] in kinds):
            category, tag, body = row
            css = " phase" if category == "Phases" else ""
            rows.append(f"<div class='log-row{css}'><span class='log-t'>{event['t']:.1f}s</span>"
                        f"<span class='log-tag tag-{tag}'>{tag}</span><span class='log-body'>{body}</span></div>")
    return "<div class='log'>" + "".join(rows) + "</div>" if rows else "<p class='muted'>No events match.</p>"


# ---------- page setup ----------

st.set_page_config(page_title="Northstar Browser QA Agent", page_icon="🧭", layout="wide")
st.logo(str(DATACAMP_LOGO_WHITE), size="large", link=DATACAMP_URL, icon_image=str(DATACAMP_LOGO))

st.html(
    """
    <style>
      [data-testid="stMainBlockContainer"] { max-width: 1200px; padding-top: 4rem; padding-bottom: 4rem; }
      .hero-title { font-size: clamp(1.55rem, 1.1rem + 1.8vw, 2.2rem); font-weight: 800; line-height: 1.15;
        color: #080808; background: #FFFFFF; margin: 0 0 .6rem; }
      .hero-sub { color: #3B4450; background: #FFFFFF; font-size: 1.02rem; line-height: 1.6; max-width: 70ch; margin: .7rem 0 0; }
      .model-chip { display: inline-flex; align-items: center; gap: .55rem; background: #05192D; color: #FFFFFF;
        border-radius: 999px; padding: .3rem .9rem .3rem .35rem; font-size: .85rem; font-weight: 600; }
      .model-chip img { width: 22px; height: 22px; display: block; }
      .model-chip .m { color: #03EF62; background: #05192D; font-family: 'JetBrains Mono', ui-monospace, monospace; }

      .stage-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: .75rem; }
      .stage { background: #F7F7F5; color: #3B4450; border: 1px solid #E6E4DD; border-radius: 12px; padding: .9rem 1rem; }
      .stage-head { display: flex; align-items: center; gap: .55rem; font-weight: 700; color: #080808; background: #F7F7F5; }
      .stage-num { width: 1.6rem; height: 1.6rem; border-radius: 50%; background: #05192D; color: #03EF62;
        display: grid; place-items: center; font-size: .8rem; font-weight: 800; }
      .stage p { color: #3B4450; background: #F7F7F5; font-size: .9rem; line-height: 1.5; margin: .45rem 0 0; }

      .turn-card { background: #FFFFFF; color: #080808; border: 1px solid #E6E4DD; border-radius: 12px; padding: 1rem 1.1rem; }
      .turn-head { display: flex; justify-content: space-between; align-items: center; gap: .5rem; margin-bottom: .6rem;
        font-weight: 700; color: #080808; background: #FFFFFF; }
      .turn-meta { color: #5B6573; background: #FFFFFF; font-size: .85rem; margin: .5rem 0 0; }
      table.qa { width: 100%; border-collapse: collapse; font-size: .92rem; background: #FFFFFF; }
      table.qa th { text-align: left; color: #3B4450; background: #F7F7F5; font-weight: 700; padding: .45rem .5rem;
        border-bottom: 1px solid #E6E4DD; }
      table.qa td { color: #080808; background: #FFFFFF; padding: .45rem .5rem; border-bottom: 1px solid #E6E4DD;
        font-variant-numeric: tabular-nums; }
      .pill { display: inline-block; font-size: .75rem; font-weight: 700; border-radius: 999px; padding: .1rem .6rem; }
      .pill.ok { background: #E3FCEC; color: #026B33; }
      .pill.warn { background: #FFF4E5; color: #8A4B00; }
      .pill.bad { background: #FDECEA; color: #A12622; }

      .log { font-size: .88rem; line-height: 1.5; background: #FFFFFF; }
      .log-row { display: grid; grid-template-columns: 4.2rem 5.6rem minmax(0, 1fr); gap: .75rem; align-items: baseline;
        padding: .38rem .6rem; background: #FFFFFF; border-bottom: 1px solid #EFEDE7; border-left: 3px solid transparent; }
      .log-row.phase { background: #F7F7F5; border-left-color: #03EF62; }
      .log-t { color: #5B6573; text-align: right; font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: .8rem; }
      .log-tag { justify-self: start; font-size: .72rem; font-weight: 700; text-transform: uppercase;
        padding: .08rem .45rem; border-radius: 6px; background: #EEF0F3; color: #2F3A48; }
      .tag-approval, .tag-session, .tag-release { background: #E8EEF6; color: #05192D; }
      .tag-qa, .tag-verdict, .tag-done { background: #E3FCEC; color: #026B33; }
      .tag-agent { background: #05192D; color: #FFFFFF; }
      .tag-note, .tag-error { background: #FDECEA; color: #A12622; }
      .log-body { color: #080808; overflow-wrap: anywhere; }
      .log-body code { font-size: .82rem; background: #F7F7F5; color: #05192D; padding: 0 .25rem; }
      .log-body .pill { vertical-align: baseline; }
      .bad { color: #A12622; font-weight: 700; }
      .note-box { background: #FFF4E5; color: #8A4B00; border: 1px solid #F5D9A6; border-radius: 10px;
        padding: .75rem 1rem; font-size: .95rem; line-height: 1.5; }
      .note-box b { color: #8A4B00; background: #FFF4E5; }
      .muted { color: #5B6573; background: #FFFFFF; }
      @media (max-width: 640px) {
        .log-row { grid-template-columns: auto minmax(0, 1fr); }
        .log-body { grid-column: 1 / -1; }
      }

      .price-table { width: 100%; border-collapse: collapse; font-size: .86rem; background: #05192D; }
      .price-table th, .price-table td { padding: .32rem .2rem; text-align: right; border-bottom: 1px solid #2A4661;
        background: #05192D; color: #FFFFFF; }
      .price-table td:first-child { text-align: left; color: #C9D3DE; }
      .price-table th { color: #03EF62; font-weight: 700; font-size: .78rem; }

      .st-key-run_agent button { background: #03EF62; color: #05192D; border: 1px solid #03EF62; font-weight: 700;
        padding: .6rem 1.4rem; }
      .st-key-run_agent button p { font-weight: 700; color: #05192D; }
      .st-key-run_agent button:hover { background: #02C853; border-color: #02C853; color: #05192D; }
      .st-key-run_agent button:focus-visible { outline: 3px solid #05192D; outline-offset: 2px; }
      .st-key-run_agent button:disabled { background: #E6E4DD; border-color: #E6E4DD; color: #5B6573; }
      .st-key-run_agent button:disabled p { color: #5B6573; }
    </style>
    """
)

# ---------- header ----------

st.html(
    f"""
    <h1 class="hero-title">Northstar Checkout Browser QA Agent</h1>
    <span class="model-chip"><img src="data:image/png;base64,{b64(OPENAI_MARK_WHITE)}" alt="OpenAI"/>
      <span class="m">{MODEL}</span></span>
    <p class="hero-sub">One Agents API session gets a QA objective, tests a fictional checkout in an
    OpenAI-hosted browser, and reports what it saw through <code>record_qa_result</code>. Application code,
    not the model, decides pass or fail. After the fix ships, the same session runs the test again.</p>
    """
)

with st.expander("How each run works: 6 stages"):
    st.html("<div class='stage-grid'>" + "".join(
        f"<div class='stage'><div class='stage-head'><span class='stage-num'>{i}</span>{escape(name)}</div>"
        f"<p>{escape(desc)}</p></div>" for i, (name, desc) in enumerate(STAGES, 1)) + "</div>")

# ---------- sidebar ----------

with st.sidebar:
    mode = st.radio("Mode", ["Replay a recorded run", "Run live"])
    runs = recorded_runs()
    chosen = st.selectbox("Recorded run", runs, format_func=run_label) if mode.startswith("Replay") and runs else None
    st.divider()
    st.markdown("**Pricing** · USD per 1M tokens")
    rows = "".join(f"<tr><td>{label}</td><td>${PRICES[key]:.2f}</td></tr>"
                   for label, key in (("Input", "input"), ("Cached input", "cached"),
                                      ("Cache writes", "cache_write"), ("Output", "output")))
    st.html(f"<table class='price-table'><tr><th></th><th>Standard</th></tr>{rows}</table>")
    st.caption(md("Prompts over 272K input tokens are billed at $20, $2, $25, and $75 for the whole request. "
                  "Session usage is best-effort and is not the invoice."))


# ---------- results ----------

def verdict_card(label, turn):
    record, result = turn.get("record") or {}, turn["result"]
    observed = result.get("observed", {})
    reported = record.get("build_id")
    build_check = pill("pass") if reported == turn["build"] else pill("incomplete")
    rows = [f"<tr><td>Build</td><td>{escape(turn['build'])}</td>"
            f"<td>{escape(reported or 'not seen')}</td><td>{build_check}</td></tr>"]
    for name, raw_key, key, money in FIELDS:
        expected = dollars(EXPECTED[key]) if money else EXPECTED[key]
        seen = observed.get(key)
        shown = dollars(seen) if money else ("not seen" if seen is None else seen)
        match = pill("pass") if seen == EXPECTED[key] else pill("fail" if seen is not None else "incomplete")
        rows.append(f"<tr><td>{name}</td><td>{expected}</td><td>{escape(str(shown))}</td><td>{match}</td></tr>")
    return (f"<div class='turn-card'><div class='turn-head'><span>{LABELS[label]} · build {escape(turn['build'])}</span>"
            f"{pill(result['verdict'])}</div><table class='qa'><tr><th>Field</th><th>Expected</th><th>Observed</th>"
            f"<th>Check</th></tr>{''.join(rows)}</table>"
            f"<p class='turn-meta'>Evidence id {escape(str(record.get('evidence_id', '–')))} · "
            f"purchase control: {escape(str(record.get('purchase_control', 'not reported')))}</p></div>")


def render_results(run_dir):
    s = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    turns = s["turns"]
    tabs = st.tabs(["Verdict", "Evidence", "Session", "Cost", "Event log"])

    with tabs[0]:
        cols = st.columns(2, gap="medium")
        for col, label in zip(cols, ("run1", "retest")):
            with col:
                st.html(verdict_card(label, turns[label]))
        st.caption("Pass, Fail, and Incomplete come from qa/verdict.py. Incomplete means the agent never submitted a "
                   "complete record for the expected build, so the turn cannot pass.")
        for label in ("run1", "retest"):
            note = (turns[label].get("record") or {}).get("evidence_note")
            if note:
                st.markdown(f"**{LABELS[label]}, agent's evidence note.** {md(note)}")

    with tabs[1]:
        for label in ("run1", "retest"):
            turn = turns[label]
            st.markdown(f"##### {LABELS[label]} · build {turn['build']}")
            st.caption(f"{turn['browser_items']} browser activity items, {len(turn['screenshots'])} returned a screenshot. "
                       "Screenshots appear only because include_screenshots is true, and some items return none.")
            for shot in turn["screenshots"]:
                st.image(str(run_dir / shot["file"]), width=860,
                         caption=f"{shot['title']} ({shot['item_id'][-12:]})")

    with tabs[2]:
        env = s.get("environment", {})
        with st.container(horizontal=True, gap="small"):
            st.metric("Session reused for retest", "Yes" if s.get("same_session") else "No", border=True)
            st.metric("Same hosted environment", "Yes" if s.get("same_environment") else "No", border=True)
            st.metric("Session lifetime", f"{s.get('session_lifetime_minutes', 0)} min", border=True)
            st.metric("Deleted after saving", "Yes" if (s.get("deleted") or {}).get("deleted") else "No", border=True)
        st.markdown(f"Session `{s['session_id']}` · environment `{env.get('type')}`, "
                    f"size `{env.get('container_size', 'default')}`, network `{env.get('network', {}).get('access')}` "
                    f"to `{', '.join(env.get('network', {}).get('allowed_domains') or [])}`.")
        for label in ("run1", "retest"):
            turn = turns[label]
            approvals = ", ".join(f"{a['decision']} ({a['type']})" for a in turn["approvals"]) or "none requested"
            st.markdown(f"- **{LABELS[label]}:** build `{turn['build']}`, turn `{short(turn['turn_id'])}`, "
                        f"{turn['wall_seconds']} s, origin approvals: {approvals}.")
        st.caption("Kept across turns: the session, its conversation, and the hosted environment id. "
                   "Not relied on: browser state. Each turn starts from a build URL with ?reset=1.")

    with tabs[3]:
        rows = []
        for label in ("run1", "retest"):
            u = turns[label].get("usage")
            if u:
                cached = u["input_tokens_details"]["cached_tokens"]
                rows.append({"Turn": LABELS[label], "Input": u["input_tokens"], "Cached input": cached,
                             "Uncached input": u["input_tokens"] - cached, "Output": u["output_tokens"],
                             "Reasoning": u["output_tokens_details"]["reasoning_tokens"],
                             "Estimate (USD)": turns[label]["usage_cost_estimate"]})
            else:
                rows.append({"Turn": LABELS[label], "Input": None, "Cached input": None, "Uncached input": None,
                             "Output": None, "Reasoning": None, "Estimate (USD)": None})
        st.markdown("##### Token usage by turn")
        st.dataframe(rows, hide_index=True, column_config={
            "Estimate (USD)": st.column_config.NumberColumn(format="$%.4f")})
        total = s.get("session_usage_cost_estimate")
        st.markdown(md(f"**Usage estimate for the session:** "
                       f"{'$' + format(total, '.4f') if total is not None else 'usage was null when read'}"))
        st.markdown(f"**Hosted-environment charge:** not returned by the API. The session ran for "
                    f"{s.get('session_lifetime_minutes')} minutes on a `{env.get('container_size', 'medium')}` "
                    f"environment. Check platform billing for the charged amount.")
        st.html("<div class='note-box'><b>Usage is not the invoice.</b> It is best-effort and has no cache-write "
                "counter, so cache writes are not in this estimate. Model tokens and sandbox time are separate "
                "billing lines.</div>")

    with tabs[4]:
        events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        kinds = st.pills("Show events", list(LOG_KINDS), selection_mode="multi", default=list(LOG_KINDS), key="log_filter")
        st.caption(f"{len(events)} events in run {run_dir.name}. Times are seconds since the run started.")
        with st.container(height=560, border=True):
            st.html(log_html(events, set(kinds)))


# ---------- main ----------

if mode.startswith("Replay"):
    if chosen is None:
        st.info("No recorded runs yet. Switch to live mode or run `python run_qa.py`.")
    else:
        render_results(chosen)
else:
    has_key = bool(os.getenv("OPENAI_API_KEY"))
    staging_url = st.text_input("Northstar staging URL", STAGING_URL,
                                help="Any public host serving the northstar/ folder. It becomes the only allowed domain.")
    st.markdown("This creates one Agents API session, runs the buggy build and the retest, then deletes the session. "
                "It takes about 3 minutes and bills your key.")
    if not has_key:
        st.warning("No `OPENAI_API_KEY` found. Add it to `.env` in the project folder, then reload.", icon=":material/key:")
    if st.button("Run the QA agent", key="run_agent", disabled=not has_key, icon=":material/play_arrow:"):
        from qa.pipeline import run_experiment

        run_id, events = None, []
        with st.status("Running the QA agent…", expanded=True) as status:
            with st.container(height=460, border=False, autoscroll=True):
                log_box = st.empty()
            for event in run_experiment(staging_url):
                events.append(event)
                if event["type"] == "phase":
                    status.update(label=f"Running: {event['name']}…")
                if event_row(event):
                    log_box.html(log_html(events))
                if event["type"] == "done":
                    run_id = event["run_id"]
                    status.update(label="Run finished", state="complete", expanded=False)
        if run_id:
            render_results(RUNS / run_id)

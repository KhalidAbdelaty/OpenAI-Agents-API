"""Run the Northstar Checkout QA experiment from the terminal.

    python run_qa.py [--staging-url https://your-northstar-host]

Needs OPENAI_API_KEY in .env and a Northstar URL the OpenAI-hosted browser can reach.
"""

import argparse

from qa.config import STAGING_URL
from qa.pipeline import run_experiment


def line(event):
    kind = event["type"]
    if kind == "browser":
        return f"browser  {event['status']:<10} {event['title'] or 'Browser activity'}"
    if kind == "approval":
        return f"approval {event['decision']:<10} {event['origin']}"
    if kind == "qa_record":
        return f"record   {event['label']:<10} {event['record']}"
    if kind == "verdict":
        return f"VERDICT  {event['label']:<10} {event['verdict'].upper()} {event['result']['failed_checks']}"
    if kind == "usage":
        return f"usage    {event['label']:<10} {event['usage']} estimate ${event['estimate']}"
    if kind == "agent_text":
        return f"agent    {event['text']}"
    return f"{kind:<8} " + ", ".join(f"{k}={v}" for k, v in event.items() if k not in ("t", "type"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging-url", default=STAGING_URL, help="Base URL that serves the northstar/ folder")
    args = parser.parse_args()
    for event in run_experiment(args.staging_url):
        print(f"{event['t']:>7.1f}s  {line(event)}", flush=True)

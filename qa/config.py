"""Settings for the Northstar Checkout QA experiment. The API key comes from .env only."""

from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
load_dotenv(ROOT / ".env")

# Public staging host that serves the northstar/ folder. Any host the hosted browser can reach works.
STAGING_URL = "https://northstar-checkout-staging.vercel.app"

MODEL = "gpt-6-astra"
REASONING_EFFORT = "medium"
BUGGY_BUILD = "ns-1041"
FIXED_BUILD = "ns-1042"

# The answer key lives here, in application code. The agent never sees it.
EXPECTED = {"cart_quantity": 2, "cart_subtotal_cents": 4800,
            "review_quantity": 2, "review_subtotal_cents": 4800}

# Standard GPT-6 Astra rates, USD per 1M tokens, for prompts up to 272K input tokens.
# Checked on the model and pricing pages on September 30, 2026.
PRICES = {"input": 10.00, "cached": 1.00, "cache_write": 12.50, "output": 50.00}

# Identical for the failed run and the retest. Only the release changes.
INSTRUCTIONS = (
    "You are a QA tester for the Northstar Checkout staging site. "
    "Use the browser to run the test you are given. "
    "Stay on the approved staging origin and do not visit any other website. "
    "Inspect what is visible on a page before you make any claim about it. "
    "Stop before any purchase: never place, submit, or pay for an order. "
    "Never invent an observed value. If you could not see a value, report null. "
    "Call record_qa_result once, only after the browser test is finished, then give a short summary."
)

QA_OBJECTIVE = (
    "QA objective for Northstar Checkout staging build {build}. Start at {url}\n"
    "Scenario: a customer adds 2 Trail Bottles to the cart and continues through checkout "
    "to the order review page.\n"
    "Acceptance criteria:\n"
    "- The cart shows quantity 2 and a subtotal of $48.00 (unit price $24.00, no shipping or taxes).\n"
    "- The order review page shows the same quantity and subtotal as the cart.\n"
    "- The purchase step is never used.\n"
    "Record the cart values and the review values as separate fields."
)

RETEST = (
    "A fix is deployed as staging build {build} at {url}\n"
    "That link starts from an empty cart. Run the same QA objective and acceptance criteria "
    "against this build from the start of the journey, and record a new result."
)

RECORD_QA_RESULT = {
    "type": "function",
    "name": "record_qa_result",
    "description": ("Submit the values you observed in the browser. The application compares them "
                    "with the acceptance criteria and returns the verdict."),
    "parameters": {
        "type": "object",
        "properties": {
            "build_id": {"type": "string", "description": "Build id shown on the page."},
            "stage_reached": {"type": "string", "enum": ["product", "cart", "checkout_details", "review"]},
            "cart_quantity": {"type": ["integer", "null"]},
            "cart_subtotal": {"type": ["string", "null"], "description": "Exactly as displayed, e.g. $10.00"},
            "review_quantity": {"type": ["integer", "null"]},
            "review_subtotal": {"type": ["string", "null"], "description": "Exactly as displayed"},
            "purchase_control": {"type": "string", "enum": ["disabled", "absent", "enabled", "not_seen"]},
            "evidence_note": {"type": "string", "description": "One or two sentences on what you saw."},
        },
        "required": ["build_id", "stage_reached", "cart_quantity", "cart_subtotal",
                     "review_quantity", "review_subtotal", "purchase_control", "evidence_note"],
        "additionalProperties": False,
    },
}

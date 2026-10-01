# Northstar Checkout Browser QA Agent (OpenAI Agents API + Computer Use)

One OpenAI Agents API session gets a QA goal for a small fictional checkout, tests it in an OpenAI-hosted browser with `gpt-6-astra` and Computer Use, and reports what it saw through a function tool called `record_qa_result`. Your code, not the model, decides pass or fail. After the fix ships, a follow-up message on the same session runs the test again.

The agent is never told where the bug is. The answer key lives in `qa/config.py` and is only used by the harness.

## How a run works

- **Buggy release:** staging build `ns-1041` shows the right cart subtotal ($48.00 for 2 Trail Bottles) and the wrong review subtotal ($24.00).
- **Session:** `gpt-6-astra`, Computer Use with `include_screenshots: true`, an OpenAI-hosted desktop, and `restricted` network access to the staging host only.
- **Origin approval:** the harness approves the staging origin and denies every other one. Sign-in requests are cancelled.
- **Verdict:** the agent calls `record_qa_result` with the build id it saw and separate cart and review values. `qa/verdict.py` first checks that the build id matches the build under test, then compares the values with the answer key and returns `pass`, `fail`, or `incomplete`. A record for the wrong build, a missing value, or a turn that never calls the function is `incomplete` and cannot pass.
- **No purchase:** the task states this as a safety constraint, not an acceptance criterion, because the verdict cannot prove a button was never pressed. The real guard is the disabled Place order button on the staging page. `purchase_control` is saved as evidence and does not affect the verdict.
- **Fix and retest:** build `ns-1042` changes one line (the review subtotal multiplies by quantity). The same session gets a follow-up message and tests it from an empty cart.
- **Cleanup:** items, screenshots, usage, and the summary are saved under `runs/`, and only then is the session deleted.

## Files

- `northstar/` is the static staging site. Each build lives at its own path, `/b/ns-1041/` and `/b/ns-1042/`, and `?reset=1` clears the cart.
- `qa/config.py` holds the model, the agent instructions, the QA task, the answer key, the `record_qa_result` schema, and the token prices.
- `qa/pipeline.py` is the whole experiment as one generator: create the session, stream events, answer approvals, run the function, save artifacts, delete the session.
- `qa/verdict.py` turns the agent's report into a verdict.
- `run_qa.py` runs the experiment from the terminal.
- `app_streamlit.py` replays a saved run with no API call, or starts a live run.
- `runs/20261001-162927/` is a sample run you can open in the Streamlit app without an API key.

## Setup (Windows PowerShell)

```powershell
git clone https://github.com/KhalidAbdelaty/OpenAI-Agents-API.git
cd OpenAI-Agents-API
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # then put your OPENAI_API_KEY in .env
```

On macOS or Linux, use `source .venv/bin/activate` and `cp .env.example .env`.

Your API key needs the `api.agents.read`, `api.agents.write`, and `api.responses.write` scopes, and your project needs access to `gpt-6-astra`.

## Staging site

The hosted browser runs on OpenAI's servers, so it needs a URL it can reach over the internet. By default the harness uses `https://northstar-checkout-staging.vercel.app`.

To use your own copy, deploy the `northstar/` folder to any static host so that `northstar/` is the site root, then pass its URL with `--staging-url` or type it in the Streamlit app. That host becomes the only allowed domain.

## Watching the agent's browser

The API returns a title for each browser action and only an occasional screenshot, so Northstar records itself. `northstar/rec.js` uses [rrweb](https://github.com/rrweb-io/rrweb) (self-hosted in `northstar/vendor/`) to record clicks, mouse movement, and page changes in whatever browser opens a build, including the OpenAI-hosted one. It sends the events to `/api/rec` on the same host, so the network allowlist still needs only one hostname. The footer tells visitors that page activity is recorded, and `maskAllInputs` masks anything typed into form fields. Northstar has no form fields, so this only matters if you reuse the recorder on a page that has them.

Deleting the Agents API session does not delete these recordings. They stay in your Blob store until you remove them.

- `northstar/api/rec.js` is a Vercel function that saves each batch to a private [Vercel Blob](https://vercel.com/docs/vercel-blob) store and returns a full recording on request.
- `northstar/replay/` plays recordings back with rrweb-player. Open `/replay/` to pick one, or `/replay/?ids=<first>,<second>` to play two in a row.

To record on your own copy, deploy `northstar/` to Vercel and connect a private Blob store to the project. On a host without functions, the store still works and the recorder simply stops sending.

## Run

```powershell
python run_qa.py                                        # the full experiment
python run_qa.py --staging-url https://your-host.example # against your own deploy
streamlit run app_streamlit.py                          # replay or live mode
```

`run_qa.py` and the Streamlit live mode make real API calls and bill your key. The sample run took about 3 minutes, and its token usage came to about $0.95 at standard GPT-6 Astra rates. Usage is best-effort and is not the invoice: it has no cache-write counter, and the hosted environment is billed separately.

The Agents API is in public beta, so event names and fields can change. The code was tested with `openai==3.22.1`.

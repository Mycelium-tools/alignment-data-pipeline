# Prompt Studio

A small local app for **viewing, editing, and running the pipeline prompts** —
no need to touch the Python scripts. Built for non-technical use.

## Launch

**Nothing to install** — `gui/app.py` uses only the Python standard library. You just
need Python 3 (already on most Macs and Linux; on Windows install it once from
[python.org](https://www.python.org/downloads/)).

Pick whichever is easiest:

| You are… | Do this |
|---|---|
| Using **Claude Code** | Say *"launch the prompt GUI"* — it runs the command for you. |
| Comfortable with a terminal | From the repo folder: `python3 gui/app.py` (or `python gui/app.py`) |
| Prefer not to use a terminal | **macOS:** double-click `start.command` · **Windows:** double-click `start.bat` |

Any of these starts a local app and opens **http://localhost:8765** (or the next free
port). Leave the window open while you use it; press `Ctrl-C` (or close the window) to
stop. Only the *Anthropic API* run-mode needs a key or any `pip install`; the *Claude
Code CLI* mode and everything else work out of the box.

> The plain `gui/index.html` file on its own only shows the shell — the buttons,
> editing, running, and outputs need the server (the commands above) so it can
> read/write files and call the model.

## The four tabs

- **Prompts** — pick any stage on the left, read its prompt, edit it, **Save**, and
  **Run** it. Fill in the inputs (the `{placeholders}` in the prompt), choose where
  the input comes from, and press Run. The result appears below and is saved to
  *My prompt runs*.
- **Outputs** — browse the data each stage produced. Switch between *Pipeline stage
  outputs* (the real per-stage files, with the source prompt and the parent-record
  lineage shown) and *My prompt runs* (everything you've Run, tagged with which
  prompt and inputs produced it).
- **Pipeline** — a left-to-right map of both pipelines. Each box shows the stage,
  its prompt file, and its output file. Click a box to jump to that prompt.
- **Settings** — choose the run mode and (for API mode) save your key.

## Two ways to run a prompt

- **Claude Code CLI** *(default)* — runs `claude` on your machine using your existing
  Claude login. **No API key or credits needed.** Best for quick iteration.
- **Anthropic API** — uses a key you save in Settings (stored only in this repo's
  local `.env`). Billed to that account.

## How prompts and outputs relate

`gui/pipeline.json` is the single source of truth for the stages, which prompt drives
each one, what it takes as input, and what file it writes. The Outputs tab uses the
parent IDs inside each record (`type_id → subtype_id → doc_id`; `principle_id →
scenario_id → prompt_id → response_id`) to show lineage, so you can always see which
prompt and which upstream record produced a given output.

## Notes / current gaps

- The **Run** button executes a single prompt and stores the raw result. The full
  multi-stage pipeline (parsing, checkpointing, filtering) is still the Python
  scripts (`sdf_pipeline/run.py`, `dad_pipeline/run.py`). Prompt Studio is for
  *iterating on prompts and inspecting data*, not replacing the orchestrator.
- The sample data under `outputs/` was hand-authored (faithful stand-ins for model
  output) so the tabs aren't empty before you run anything real.
- **DAD reasoning scratchpad:** the GUI shows a `scratchpad` field beside the final
  answer when present (see the step-5 samples). The current DAD pipeline does **not**
  emit one — adding it is a pipeline change.
- **DAD system prompts** are the fixed injection templates in
  `prompts/dad/step5_injections.yaml` (editable like any prompt), not per-scenario
  generated artifacts.

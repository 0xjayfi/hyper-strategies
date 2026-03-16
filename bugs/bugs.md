# Content Pipeline Bugs

## Confirmed Bugs

### 1. Stale `content_selections.json` can trigger wrong posts

- **Files involved**
  - `src/content/dispatcher.py`
  - `scripts/run-content-pipeline.sh`
- **Issue**
  - When `detect_and_select()` finds no qualifying angles, it returns early but does not delete any existing `data/content_selections.json`.
  - The shell script only checks whether that file exists before proceeding.
- **Impact**
  - A stale selections file from a previous run can cause the pipeline to capture screenshots and generate/post content for old angles even when the current day has no valid selections.
- **Suggested fix**
  - Delete `data/content_selections.json` at the start of detection or explicitly remove it before returning with no selections.
  - Optionally also have the shell script validate that the file was generated during the current run.

### 2. Daily cron path never provides a `NansenClient`

- **Files involved**
  - `scripts/run-content-pipeline.sh`
  - `src/content/dispatcher.py`
- **Issue**
  - The dispatcher CLI path creates only `DataStore()` and never initializes or passes a `NansenClient` into snapshot or detect flows.
- **Impact**
  - `take_consensus_snapshot()` always skips.
  - `wallet_spotlight` payloads always have empty `current_positions` in the real cron run.
  - Any angle or payload path that depends on live Nansen-backed data is degraded or non-functional.
- **Suggested fix**
  - Instantiate `NansenClient` in the dispatcher CLI path and pass it into `take_daily_snapshots()` and `detect_and_select()`.

### 3. `smart_money_consensus` is effectively non-functional in the scheduled pipeline

- **Files involved**
  - `src/content/dispatcher.py`
  - `src/content/angles/smart_money_consensus.py`
- **Issue**
  - Consensus snapshots are required for this angle, but `take_consensus_snapshot()` is still a placeholder and is not populated in the real scheduled flow.
- **Impact**
  - The angle cannot reliably detect fresh day-over-day changes in production.
- **Suggested fix**
  - Implement `take_consensus_snapshot()` and make sure the cron path provides the required client/data.

### 4. `index_portfolio` is effectively non-functional in the scheduled pipeline

- **Files involved**
  - `src/content/dispatcher.py`
  - `src/content/angles/index_portfolio.py`
- **Issue**
  - Index portfolio snapshots are required for detection, but `take_index_portfolio_snapshot()` is still a placeholder.
- **Impact**
  - The angle has no real daily snapshot population path in production.
- **Suggested fix**
  - Implement `take_index_portfolio_snapshot()` and wire it into the daily snapshot flow.

## Likely Risks / High-Risk Issues

### 5. Vite health check can attach to the wrong server

- **Files involved**
  - `scripts/run-content-pipeline.sh`
- **Issue**
  - The script starts Vite and then only checks whether `http://localhost:5173/` responds.
  - If another process is already bound to port `5173`, the check can pass even if the newly started Vite process failed.
- **Impact**
  - Screenshots may be captured from the wrong frontend instance.
- **Suggested fix**
  - Check that the spawned Vite process is still alive and/or use a dedicated port or stronger health validation.

### 6. Cooldown tracking depends on prompt compliance

- **Files involved**
  - `src/content/prompts/*.md`
  - `src/datastore.py`
- **Issue**
  - Post recording into `content_posts` is done inside prompt-driven workflow steps rather than enforced by a single Python posting module.
- **Impact**
  - If a draft gets created in Typefully but the DB insert step is skipped or fails, cooldown logic becomes inaccurate.
- **Suggested fix**
  - Move final draft creation and `content_posts` insertion into a single code-owned posting function with clearer success/failure handling.

## Validation Notes

- `python scripts/test_content_angles.py` passes for the in-memory integration smoke test.
- The main pipeline concerns above come from reviewing the production shell-script path and dispatcher CLI behavior.
- A local pytest import failure was observed under Python 3.8, but `pyproject.toml` requires Python `>=3.11`, so that environment mismatch is not itself a pipeline bug.

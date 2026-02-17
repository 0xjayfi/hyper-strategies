# Parallelized Execution Plan

**Source**: specs/terminal-tui-app.md
**Generated**: 2026-02-17
**Max concurrent agents per track**: 8
**Max agents per phase**: 3

---

## Dependency Graph

Phase 1 -> (no dependencies)
Phase 2 -> (no dependencies)
Phase 3 -> Phase 1, Phase 2
Phase 4 -> Phase 3

---

## Completed Phases (Skipped)

- [x] **Phase 1: Rich display module (`tui.py`)** — all 5 tasks complete
- [x] **Phase 2: Add leverage column to `our_positions`** — all 3 tasks complete
- [x] **Phase 3: Interactive command loop in `main.py`** — all 6 tasks complete

---

## ~~Track 1: Display Module & Schema Update~~ DONE

### Phase 1: Rich display module (`tui.py`) (agents: 2) — DONE
- [x] Add `rich>=13.0` to `pyproject.toml` dependencies
- [x] Create `src/snap/tui.py` with `render_portfolio_table(db_path) -> rich.Table`
- [x] Create `render_scores_table(db_path) -> rich.Table`
- [x] Create `render_status_bar(state, mode, account_value, last_refresh, last_rebalance) -> rich.Panel`
- [x] Create `print_portfolio(db_path)` and `print_scores(db_path)` convenience functions

### Phase 2: Add leverage column to `our_positions` (agents: 1) — DONE
- [x] Add `leverage REAL DEFAULT 5.0` column to `_CREATE_OUR_POSITIONS` in `database.py`
- [x] Update `execute_rebalance()` in `execution.py` to store leverage when inserting/updating `our_positions`
- [x] Update `close_position_market()` in `monitoring.py` if it touches `our_positions` columns

---

## ~~Track 2: Interactive Command Loop~~ DONE

### Phase 3: Interactive command loop in `main.py` (agents: 1) — DONE
- [x] Rewrite `main.py` to show a startup banner via `rich.Console`
- [x] Replace the single `await scheduler.run()` with a dual-task pattern: async input loop + scheduler loop via `asyncio.gather`
- [x] Implement key command dispatch: `r` (refresh), `b` (rebalance), `m` (monitor), `s` (scores), `p` (portfolio), `q` (quit)
- [x] On startup, print status bar + portfolio (if positions exist) + command hint line
- [x] After each stage completes (refresh/rebalance/monitor), re-print the status bar
- [x] Keep existing argparse CLI flags and SIGINT/SIGTERM graceful shutdown

---

## ~~Track 3: Testing~~ DONE

Phases in this track run **in parallel**. Starts after Track 2 completes.

### Phase 4: Tests (agents: 2) — DONE
- [x] `test_tui.py`: test `render_portfolio_table` with mock DB data (in-memory SQLite), verify column count and row content
- [x] `test_tui.py`: test `render_scores_table` with mock scored traders
- [x] `test_tui.py`: test `render_status_bar` output
- [x] Update `test_main.py` if `parse_args` or `run()` signature changed
- [x] Verify `leverage` column exists after `init_db` in `test_database.py`

---

## Execution Summary

| Track | Phases | Total Agents | Total Tasks |
|-------|--------|-------------|-------------|
| Track 1 | Phase 1, Phase 2 | 3 | 8 |
| Track 2 | Phase 3 | 1 | 6 |
| Track 3 | Phase 4 | 2 | 5 |
| **Total** | **4 phases** | — | **19** |

# Terminal TUI Application

## Objective

Replace the current headless `main.py` with an interactive terminal application. The user launches `snap` and sees a concise dashboard with a command bar. They can trigger stages manually, view trader scores, and inspect the portfolio — all without leaving the terminal.

## Approach

Use **`rich`** for tables/panels/layout and **`prompt_toolkit`** (or a simple `asyncio` stdin reader) for non-blocking keyboard input. Avoid heavy TUI frameworks (textual/curses) — keep it minimal and fast.

New dependency: `rich>=13.0`.

The core idea: the scheduler loop runs in the background as before, but we layer a lightweight input handler on top so the user can press keys to trigger actions or view data at any time.

## Screen Layout

```
┌─ SNAP ─────────────────────────────── PAPER │ IDLE ─┐
│                                                      │
│  Portfolio (5 positions)              Acct: $10,000  │
│ ┌──────┬──────┬────────┬────────┬──────┬──────────┐  │
│ │Token │ Side │Size USD│  PnL   │PnL % │ Leverage │  │
│ ├──────┼──────┼────────┼────────┼──────┼──────────┤  │
│ │ BTC  │ Long │ $1,200 │  +$48  │+4.0% │   3.2x   │  │
│ │ ETH  │Short │   $800 │  -$16  │-2.0% │   2.1x   │  │
│ └──────┴──────┴────────┴────────┴──────┴──────────┘  │
│                                                      │
│  [r] Refresh traders  [b] Rebalance  [m] Monitor     │
│  [s] Show scores      [p] Show portfolio  [q] Quit   │
└──────────────────────────────────────────────────────┘
```

## Data Queries

**Portfolio table** — read from `our_positions`:
```sql
SELECT token_symbol, side, size, entry_price, current_price,
       position_usd, unrealized_pnl,
       -- margin ≈ position_usd / leverage
       -- PnL % to margin = unrealized_pnl / margin_used * 100
       stop_loss_price, trailing_stop_price, opened_at
FROM our_positions
```
Columns to display:
| Column | Source |
|--------|--------|
| Token | `token_symbol` |
| Side | `side` |
| Size (USD) | `position_usd` |
| PnL | `unrealized_pnl` |
| PnL % | `unrealized_pnl / (position_usd / leverage) * 100` (PnL to margin) |
| Leverage | `position_usd / (position_usd - unrealized_pnl)` or from snapshot |
| Margin | `position_usd / leverage` |

Need to add or derive leverage per position. The `our_positions` table doesn't store leverage directly — we'll need to either:
- (a) Add a `leverage` column to `our_positions`, or
- (b) Derive from `position_usd / margin_used` using the latest snapshot.

Option (a) is simpler and self-contained. We'll add the column and populate it during `execute_rebalance`.

**Trader scores table** — read from `trader_scores`:
```sql
SELECT ts.address, t.label, ts.composite_score, ts.style,
       ts.roi_30d, ts.win_rate, ts.profit_factor, ts.trade_count,
       ts.is_eligible, ts.fail_reason
FROM trader_scores ts
JOIN traders t ON ts.address = t.address
WHERE ts.id IN (
    SELECT MAX(id) FROM trader_scores GROUP BY address
)
ORDER BY ts.composite_score DESC
LIMIT 20
```

---

## Phases

### Phase 1: Rich display module (`tui.py`)

**Depends on:** None

- [x] Add `rich>=13.0` to `pyproject.toml` dependencies
- [x] Create `src/snap/tui.py` with:
  - [x] `render_portfolio_table(db_path) -> rich.Table` — query `our_positions`, format columns: Token, Side, Size USD, PnL, PnL %, Leverage, Margin. Color PnL green/red. Show totals row.
  - [x] `render_scores_table(db_path) -> rich.Table` — query latest `trader_scores` joined with `traders`. Columns: Rank, Address (short), Score, Style, ROI 30d, Win Rate, PF, Trades, Eligible. Top 15 only.
  - [x] `render_status_bar(state, mode, account_value, last_refresh, last_rebalance) -> rich.Panel` — one-line status showing scheduler state, mode (PAPER/LIVE), account value, time since last refresh/rebalance.
  - [x] `print_portfolio(db_path)` — prints portfolio table to console
  - [x] `print_scores(db_path)` — prints scores table to console

### Phase 2: Add leverage column to `our_positions`

**Depends on:** None

- [x] Add `leverage REAL DEFAULT 5.0` column to `_CREATE_OUR_POSITIONS` in `database.py`
- [x] Update `execute_rebalance()` in `execution.py` to store leverage when inserting/updating `our_positions`
- [x] Update `close_position_market()` in `monitoring.py` if it touches `our_positions` columns

### Phase 3: Interactive command loop in `main.py`

**Depends on:** Phase 1, Phase 2

- [x] Rewrite `main.py` to show a startup banner via `rich.Console`
- [x] Replace the single `await scheduler.run()` with a dual-task pattern:
  ```python
  async def _input_loop(scheduler, db_path, console):
      """Non-blocking stdin reader for key commands."""
      loop = asyncio.get_running_loop()
      while not scheduler._stop_event.is_set():
          key = await loop.run_in_executor(None, sys.stdin.readline)
          key = key.strip().lower()
          match key:
              case "r": await scheduler._run_trader_refresh()
              case "b": await scheduler._run_rebalance()
              case "m": await scheduler._run_monitor()
              case "s": print_scores(db_path)
              case "p": print_portfolio(db_path)
              case "q": scheduler.request_shutdown()
  ```
- [x] Run scheduler loop and input loop concurrently via `asyncio.gather`
- [x] On startup, print status bar + portfolio (if positions exist) + command hint line
- [x] After each stage completes (refresh/rebalance/monitor), re-print the status bar
- [x] Keep existing argparse CLI flags (`--live`, `--paper`, `--db-path`, etc.)
- [x] Keep SIGINT/SIGTERM graceful shutdown

### Phase 4: Tests

**Depends on:** Phase 1, Phase 2, Phase 3

- [x] `test_tui.py`: test `render_portfolio_table` with mock DB data (in-memory SQLite), verify column count and row content
- [x] `test_tui.py`: test `render_scores_table` with mock scored traders
- [x] `test_tui.py`: test `render_status_bar` output
- [x] Update `test_main.py` if `parse_args` or `run()` signature changed
- [x] Verify `leverage` column exists after `init_db` in `test_database.py`

---

## Non-goals

- No live-updating/auto-refreshing dashboard (user explicitly presses keys)
- No mouse support
- No multi-pane split screen
- No config editing from TUI

## Success criteria

1. `snap` launches and shows status + command hints
2. Pressing `s` prints a formatted trader scores table
3. Pressing `p` prints a formatted portfolio table with PnL, PnL %, leverage, margin per position
4. Pressing `r`/`b`/`m` triggers the corresponding stage
5. Pressing `q` or Ctrl+C shuts down gracefully
6. All existing tests still pass; new tests cover the display functions

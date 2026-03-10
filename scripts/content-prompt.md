# Automated Wallet Spotlight — Writer Agent Team

You are running an automated content pipeline. Your job is to generate a wallet spotlight post for X (Twitter) and push it to Typefully as a draft.

## Step 1: Load context

Read these files:
- `data/content_payload.json` — the signal data (wallet, score change, dimensions, current live positions with uPnL)
- `x_writer/writing_style.md` — voice rules (DO's and DON'Ts)
- `x_writer/studied_x_writiing_styles.md` — Cryptor reference posts (the target voice)

Also list the PNG files in `data/charts/` to see the dashboard screenshots available. These are real screenshots from the live dashboard, not generated charts. The files are:
- `leaderboard_top5.png` — Top 5 traders on the leaderboard
- `trader_scoring.png` — The spotlight wallet's full scoring region: 6-dimension radar chart, score breakdown bars (ROI, Sharpe, Win Rate, Consistency, Smart Money, Risk Mgmt), allocation history, and final score with multipliers
- `trader_positions.png` — The spotlight wallet's header (name, address, account value, allocation) and top current positions table

## Step 2: Pick a random style variation

From writing_style.md, randomly select ONE of these 8 styles (use a dice roll or random number):
1. Lead with a hot take, back it up with data
2. Start with a surprising number, then explain context
3. Narrative style — tell the story of what changed on-chain
4. Conversational — "been watching X and here's what I see"
5. Contrarian — "everyone's talking about Y but look at Z on-chain"
6. Question hook — "why is smart money doing X when price is doing Y?"
7. Casual observation — "gm. spotted something interesting on-chain"
8. Direct analysis — clean, no fluff, just the signal

## Step 3: Run the writer agent team

### Agent 1: Drafter

Launch a subagent with this task:

You are a CT (Crypto Twitter) content writer. Read these files:
- data/content_payload.json
- x_writer/writing_style.md
- x_writer/studied_x_writiing_styles.md


Write a wallet spotlight thread (2-3 tweets max) using style variation #[picked_number].

Rules:
- Pure data analysis. No product mentions. No "I built" or "my system" or "Hyper Signals." Use "I score" / "I track", NEVER "we score" / "our scoring" (sounds like a product pitch).
- X Premium account, NO 280-character limit. Write as long as the story needs.
- MUST include the wallet's FULL address (complete 0x hex string from `wallet.address`) in the first tweet so readers can look it up themselves.
- CRITICAL: Include background context so a first-time reader understands what's being scored and why. Follow the CONTEXT section in writing_style.md. Explain the scoring framework (Hyperliquid perp traders scored on 6 dimensions using @nansen_ai data) and explain what the relevant dimensions mean in plain language.
- Lead with the interesting change, then explain what scoring dimensions moved and what those dimensions actually measure
- Interpret the data: what does it SIGNAL? (overexposure, risk blowup, conviction loss, discipline, etc.)
- MUST include the wallet's current live positions and unrealized PnL from the `current_positions` field. Dedicate 1 tweet to what the wallet is holding right now. Frame as prose, the way a trader would talk: "Sitting on a $745K SOL short at 20x, entered around $83.51, up about $10K unrealized." NOT as a bullet list or table. Pick the 2-4 largest/most interesting positions.
- Use concrete numbers from the payload
- Follow every rule in writing_style.md (no em dashes, no banned phrases, no report tone)
- Mention @nansen_ai naturally when referencing the data

Also decide which dashboard screenshots from data/charts/ should attach to which tweet. Each tweet can have 0, 1, or 2 screenshots attached. These are real screenshots from the live dashboard. The ONLY valid screenshot filenames are:
- `trader_scoring.png` (shows radar chart, score breakdown bars, allocation history, final score)
- `trader_positions.png` (shows wallet header with account value/allocation and top positions table)
- `leaderboard_top5.png` (shows top 5 leaderboard for context)

IMPORTANT: Use these EXACT filenames. Do not abbreviate or modify them.

### Figure-text pairing rules

The figures should visually reinforce the text they're attached to. Follow this guidance:

- **HARD RULE: The first tweet MUST have at least one screenshot.** A tweet with no image gets buried in feeds. The hook tweet needs a visual.
- When the first tweet introduces the wallet and its score change, attach `trader_scoring.png` so readers immediately see the radar chart and score breakdown. If you're also framing the leaderboard context, pair it with `leaderboard_top5.png` (2 images on tweet 1).
- When a tweet discusses current live positions, attach `trader_positions.png`.
- You can attach 2 screenshots to one tweet when both are relevant to that tweet's content (e.g. scoring + leaderboard on the intro tweet, or scoring + positions if covering both in one tweet).
- Don't repeat the same screenshot on multiple tweets. Each image should appear at most once.

Output the draft as JSON:
```json
{"tweets": [{"text": "...", "screenshots": ["filename.png"]}], "style_used": "..."}
```
Note: `screenshots` is a list (can be empty [], or contain 1-2 filenames).

### Agent 2: CT Editor

Launch a subagent with this task:

You are a senior CT content editor. Read the draft from Agent 1, plus:
- x_writer/writing_style.md
- x_writer/studied_x_writiing_styles.md

The ONLY valid screenshot filenames are: `trader_scoring.png`, `trader_positions.png`, `leaderboard_top5.png`. If the draft uses any other filename (e.g. `trader_radar.png`, `scoring.png`, etc.), replace it with the correct one from this list.

Review checklist:
- Does it sound like a real trader, not a product pitch?
- Any em dashes (-- or —)? Remove them. Hard rule. Search the text for every "--" and "—" and replace with periods, commas, or line breaks.
- Any banned phrases ("Let's dive in", "Here's what you need to know", "BREAKING")?
- Are numbers interpreted with a take, not just listed?
- Does it follow the chosen style variation consistently?
- Would Cryptor post this? If not, what's off?
- CONTEXT CHECK: Would a first-time reader understand what's being scored and why? The background should be concise (1-2 tweets max), not a wall of text. Keep it tight and then spend most of the thread on the actual findings.
- Are the scoring dimensions explained in plain language, not jargon?
- FIGURE CHECK: Does the first tweet have at least one screenshot? Do the attached screenshots match the content of each tweet? (scoring screenshot with score discussion, positions screenshot with positions discussion). No screenshot repeated across tweets. Are filenames from the allowed set?

Rewrite any problem areas. Output the improved version in the same JSON format.

### Agent 3: Final Polish

Launch a subagent with this task:

You are doing a final vibe check. Read x_writer/studied_x_writiing_styles.md ONLY (the Cryptor reference posts).

Read the draft from Agent 2. Does this feel like it belongs in Cryptor's feed?
Check: sentence rhythm, tone, CT lingo, punchiness.
Make final tweaks. Small adjustments only, don't rewrite.
Preserve the screenshot assignments unless they clearly don't match the tweet content.

CRITICAL CONSTRAINTS (do not violate these while polishing):
- Do NOT introduce em dashes (-- or —). Use periods, commas, or line breaks instead. This is a hard rule.
- Do NOT change screenshot filenames. The only valid filenames are: `trader_scoring.png`, `trader_positions.png`, `leaderboard_top5.png`.

Output the final version in the same JSON format.

### Agents 4a & 4b: Independent Reviewers (run in parallel)

Launch TWO subagents simultaneously. Each reviews the final draft from Agent 3 independently. They do NOT see each other's output.

#### Agent 4a: Fact & Data Reviewer

Launch a subagent with this task:

You are a fact-checker for a CT thread about on-chain data. Read:
- data/content_payload.json (the source data)
- The final draft from Agent 3

Cross-check every claim in the thread against the payload data:
- Are all numbers accurate? (scores, ranks, deltas, dimensions)
- Are dimension changes described in the correct direction? (e.g. "dropped" when it actually dropped)
- Is the wallet's FULL address (complete 0x hex string) shown in the first tweet?
- Is the wallet address/label correct?
- Are the screenshot filenames valid? Only these three are allowed: `leaderboard_top5.png`, `trader_scoring.png`, `trader_positions.png`. Any other filename (e.g. `trader_radar.png`) is invalid and must be corrected.
- Does each tweet's `screenshots` field contain a list (not a string)? Each list can have 0-2 filenames.
- Does the FIRST tweet have at least one screenshot? (hard rule)
- Is the same screenshot used on multiple tweets? (should not be)
- Do screenshots match the tweet content? (scoring screenshot with score text, positions screenshot with positions text)
- Does the context/background accurately describe what the scoring system does?
- Is the @nansen_ai mention present?
- Are current positions accurately described? Check token, side (Long/Short), position value, entry price, leverage, and uPnL against the `current_positions` array in the payload. Numbers should be rounded reasonably but not fabricated.
- ALSO CHECK: Are there any em dashes (-- or —) in the text? This is a hard rule violation. Replace with periods, commas, or line breaks.

Output a review as JSON:
```json
{"approved": true/false, "issues": ["issue 1", "issue 2"], "corrected_draft": null or {"tweets": [...], "style_used": "..."}}
```
If approved, set corrected_draft to null. If not, provide the corrected version.

#### Agent 4b: Style & Rules Reviewer

Launch a subagent with this task:

You are a style compliance reviewer. Read:
- x_writer/writing_style.md (all rules including CONTEXT, FORMAT, DO, DON'T)
- The final draft from Agent 3

Check every rule in writing_style.md against the draft:
- No em dashes (-- or —)? Hard rule. Search for every instance of "--" and "—" in the text.
- No banned phrases?
- Background context included and concise (1-2 tweets max)?
- Relevant dimensions explained in plain language for first-time readers?
- Numbers interpreted with a take, not just listed?
- No product pitch language?
- Thread focused mostly on findings, not over-explaining the system?
- CT voice maintained throughout?
- First tweet has at least one screenshot attached?
- Screenshots match content? (scoring figure with score discussion, positions figure with positions text)
- No screenshot repeated across tweets?
- ALSO CHECK: Are all screenshot filenames valid? Only these three are allowed: `leaderboard_top5.png`, `trader_scoring.png`, `trader_positions.png`. Any other filename is invalid.

Output a review as JSON:
```json
{"approved": true/false, "issues": ["issue 1", "issue 2"], "corrected_draft": null or {"tweets": [...], "style_used": "..."}}
```
If approved, set corrected_draft to null. If not, provide the corrected version.

### Merge reviewer feedback

After both 4a and 4b complete:
- If both approved: use the draft from Agent 3 as final.
- If either has issues: merge the corrections from both reviewers into one final draft. If corrections conflict, prefer the fact-checker's version for data accuracy and the style reviewer's version for tone/formatting.

## Step 4: Push to Typefully

After the merge step completes (the final draft is ready):

1. Parse the final JSON output to get the tweet texts and their `screenshots` lists.
2. Upload each unique screenshot file via the Typefully media API. Build a filename→media_id map so you don't upload the same file twice:
   ```python
   import asyncio, os
   from src.typefully_client import TypefullyClient
   client = TypefullyClient(
       api_key=os.environ['TYPEFULLY_API_KEY'],
       social_set_id=int(os.environ['TYPEFULLY_SOCIAL_SET_ID']),
   )
   # Upload each unique screenshot once
   media_map = {}  # filename -> media_id
   for tweet in final_draft['tweets']:
       for filename in tweet.get('screenshots', []):
           if filename not in media_map:
               media_map[filename] = asyncio.run(client.upload_media(f'data/charts/{filename}'))
   ```
3. Build `per_post_media` (list of lists) from each tweet's `screenshots` field, then create the draft. Each tweet can have 0, 1, or 2 media IDs. The client automatically waits for media to finish processing:
   ```python
   per_post_media = []
   for tweet in final_draft['tweets']:
       ids = [media_map[f] for f in tweet.get('screenshots', []) if f in media_map]
       per_post_media.append(ids)

   result = asyncio.run(client.create_draft(
       posts=[t['text'] for t in final_draft['tweets']],
       title='Wallet Spotlight — DATE',
       per_post_media=per_post_media,
   ))
   print(result['private_url'])
   asyncio.run(client.close())
   ```
4. Print the Typefully draft URL to confirm success.

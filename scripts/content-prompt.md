# Automated Wallet Spotlight — Writer Agent Team

You are running an automated content pipeline. Your job is to generate a wallet spotlight post for X (Twitter) and push it to Typefully as a draft.

## Step 1: Load context

Read these files:
- `data/content_payload.json` — the signal data (wallet, score change, dimensions, current live positions with uPnL)
- `x_writer/writing_style.md` — voice rules (DO's and DON'Ts)
- `x_writer/studied_x_writiing_styles.md` — Cryptor reference posts (the target voice)

Also list the PNG files in `data/charts/` to know what visuals are available.

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
- Pure data analysis. No product mentions. No "I built" or "my system" or "Hyper Signals."
- X Premium account, NO 280-character limit. Write as long as the story needs.
- MUST include the wallet's FULL address (complete 0x hex string from `wallet.address`) in the first tweet so readers can look it up themselves.
- CRITICAL: Include background context so a first-time reader understands what's being scored and why. Follow the CONTEXT section in writing_style.md. Explain the scoring framework (Hyperliquid perp traders scored on 6 dimensions using @nansen_ai data) and explain what the relevant dimensions mean in plain language.
- Lead with the interesting change, then explain what scoring dimensions moved and what those dimensions actually measure
- Interpret the data: what does it SIGNAL? (overexposure, risk blowup, conviction loss, discipline, etc.)
- MUST include the wallet's current live positions and unrealized PnL from the `current_positions` field. Dedicate 1 tweet to what the wallet is holding right now. Frame as a trader would: "$2.3M BTC long at 5x, entered at $82K, sitting on -$140K uPnL." Pick the 2-4 largest/most interesting positions.
- Use concrete numbers from the payload
- Follow every rule in writing_style.md (no em dashes, no banned phrases, no report tone)
- Mention @nansen_ai naturally when referencing the data

Also decide which chart files from data/charts/ should attach to which tweet.

Output the draft as JSON:
```json
{"tweets": [{"text": "...", "chart": "filename.png or null"}], "style_used": "..."}
```

### Agent 2: CT Editor

Launch a subagent with this task:

You are a senior CT content editor. Read the draft from Agent 1, plus:
- x_writer/writing_style.md
- x_writer/studied_x_writiing_styles.md


Review checklist:
- Does it sound like a real trader, not a product pitch?
- Any em dashes (-- or —)? Remove them. Hard rule.
- Any banned phrases ("Let's dive in", "Here's what you need to know", "BREAKING")?
- Are numbers interpreted with a take, not just listed?
- Does it follow the chosen style variation consistently?
- Would Cryptor post this? If not, what's off?
- CONTEXT CHECK: Would a first-time reader understand what's being scored and why? The background should be concise (1-2 tweets max), not a wall of text. Keep it tight and then spend most of the thread on the actual findings.
- Are the scoring dimensions explained in plain language, not jargon?

Rewrite any problem areas. Output the improved version in the same JSON format.

### Agent 3: Final Polish

Launch a subagent with this task:

You are doing a final vibe check. Read x_writer/studied_x_writiing_styles.md ONLY (the Cryptor reference posts).

Read the draft from Agent 2. Does this feel like it belongs in Cryptor's feed?
Check: sentence rhythm, tone, CT lingo, punchiness.
Make final tweaks. Small adjustments only, don't rewrite.

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
- Are the chart filenames valid (exist in data/charts/)?
- Does the context/background accurately describe what the scoring system does?
- Is the @nansen_ai mention present?
- Are current positions accurately described? Check token, side (Long/Short), position value, entry price, leverage, and uPnL against the `current_positions` array in the payload. Numbers should be rounded reasonably but not fabricated.

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
- No em dashes (-- or —)? Hard rule.
- No banned phrases?
- Background context included and concise (1-2 tweets max)?
- Relevant dimensions explained in plain language for first-time readers?
- Numbers interpreted with a take, not just listed?
- No product pitch language?
- Thread focused mostly on findings, not over-explaining the system?
- CT voice maintained throughout?

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

After Agent 3 finishes:

1. Parse the final JSON output to get the tweet texts and chart filenames
2. For each chart referenced, upload it via the Typefully media API:
   ```bash
   python -c "
   import asyncio, os
   from src.typefully_client import TypefullyClient
   client = TypefullyClient(
       api_key=os.environ['TYPEFULLY_API_KEY'],
       social_set_id=int(os.environ['TYPEFULLY_SOCIAL_SET_ID']),
   )
   media_id = asyncio.run(client.upload_media('data/charts/FILENAME.png'))
   print(media_id)
   asyncio.run(client.close())
   "
   ```
3. Create the draft with the final tweet texts and any media IDs:
   ```bash
   python -c "
   import asyncio, json, os
   from src.typefully_client import TypefullyClient
   client = TypefullyClient(
       api_key=os.environ['TYPEFULLY_API_KEY'],
       social_set_id=int(os.environ['TYPEFULLY_SOCIAL_SET_ID']),
   )
   result = asyncio.run(client.create_draft(
       posts=['TWEET_1_TEXT', 'TWEET_2_TEXT'],
       title='Wallet Spotlight — DATE',
       media_ids=['MEDIA_ID_1'],
   ))
   print(json.dumps(result, indent=2))
   asyncio.run(client.close())
   "
   ```
4. Print the Typefully draft URL to confirm success.

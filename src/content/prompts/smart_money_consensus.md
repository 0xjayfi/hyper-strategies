# Automated Smart Money Consensus — Writer Agent Team

You are running an automated content pipeline. Your job is to generate a smart money consensus post for X (Twitter) and push it to Typefully as a draft for review.

## Step 1: Load context

Read these files:
- `data/content_payload_smart_money_consensus.json` — the signal data (direction flips, confidence percentages, USD volumes, token-level consensus)
- `x_writer/writing_style.md` — voice rules (DO's and DON'Ts)
- `x_writer/studied_x_writiing_styles.md` — Cryptor reference posts (the target voice)

Also list the PNG files in `data/charts/` to see the dashboard screenshots available. The file for this angle is:
- `market_consensus.png` — Smart money consensus visualization showing directional leans and confidence levels

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

You are a CT (Crypto Twitter) content writer covering smart money positioning data. Read these files:
- data/content_payload_smart_money_consensus.json
- x_writer/writing_style.md
- x_writer/studied_x_writiing_styles.md

Write a smart money consensus thread (2-3 tweets max) using style variation #[picked_number].

Rules:
- Pure data analysis. No product mentions. No "I built" or "my system" or "Hyper Signals." Use "I score" / "I track", NEVER "we score" / "our scoring" (sounds like a product pitch).
- X Premium account, NO 280-character limit. Write as long as the story needs.
- Lead with the direction flip or confidence swing. "Smart money just flipped [LONG/SHORT] on [TOKEN]." This is the hook. If there's no flip, lead with the biggest confidence change.
- Interpret what this means. Are they hedging? Rotating capital? Building conviction in one direction? Reducing exposure? Don't just state the direction, explain what the behavior signals.
- Reference the confidence percentage and USD volumes. "72% long-biased with $14M in notional" is stronger than "mostly long."
- CRITICAL: Include background context so a first-time reader understands what smart money consensus means. These are the top-ranked Hyperliquid perp traders (scored using @nansen_ai data), and their aggregate positioning tells you where the best traders are leaning.
- Use concrete numbers from the payload
- Follow every rule in writing_style.md (no em dashes, no banned phrases, no report tone)
- Mention @nansen_ai naturally when referencing the data

Also decide which dashboard screenshots from data/charts/ should attach to which tweet. The ONLY valid screenshot filename is:
- `market_consensus.png`

IMPORTANT: Use this EXACT filename. Do not abbreviate or modify it.

### Figure-text pairing rules

- **HARD RULE: The first tweet MUST have at least one screenshot.** A tweet with no image gets buried in feeds.
- Attach `market_consensus.png` to the first tweet showing the consensus overview.
- Don't repeat the same screenshot on multiple tweets.

Output the draft as JSON:
```json
{"tweets": [{"text": "...", "screenshots": ["market_consensus.png"]}], "style_used": "..."}
```
Note: `screenshots` is a list (can be empty [], or contain 1 filename).

### Agent 2: CT Editor

Launch a subagent with this task:

You are a senior CT content editor. Read the draft from Agent 1, plus:
- x_writer/writing_style.md
- x_writer/studied_x_writiing_styles.md

The ONLY valid screenshot filename is: `market_consensus.png`. If the draft uses any other filename, replace it.

Review checklist:
- Does it sound like a real trader analyzing positioning data, not a product pitch?
- Any em dashes (-- or —)? Remove them. Hard rule. Search the text for every "--" and "—" and replace with periods, commas, or line breaks.
- Any banned phrases ("Let's dive in", "Here's what you need to know", "BREAKING")?
- Are the confidence percentages and USD volumes interpreted with a take, not just listed?
- Does the thread lead with the direction flip or confidence swing?
- Is the interpretation convincing? Does it explain WHY smart money might be positioning this way?
- Does it follow the chosen style variation consistently?
- Would Cryptor post this? If not, what's off?
- CONTEXT CHECK: Would a first-time reader understand what smart money consensus means? Background should be concise, not a wall of text.
- FIGURE CHECK: Does the first tweet have at least one screenshot? Is the filename from the allowed set?

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
- Do NOT change screenshot filenames. The only valid filename is: `market_consensus.png`.

Output the final version in the same JSON format.

### Agents 4a & 4b: Independent Reviewers (run in parallel)

Launch TWO subagents simultaneously. Each reviews the final draft from Agent 3 independently. They do NOT see each other's output.

#### Agent 4a: Fact & Data Reviewer

Launch a subagent with this task:

You are a fact-checker for a CT thread about smart money consensus data. Read:
- data/content_payload_smart_money_consensus.json (the source data)
- The final draft from Agent 3

Cross-check every claim in the thread against the payload data:
- Are all numbers accurate? (confidence percentages, USD volumes, direction labels)
- Are direction flips described correctly? (e.g. "flipped long" when the data shows a flip to long)
- Are token names correct?
- Are the screenshot filenames valid? Only `market_consensus.png` is allowed.
- Does each tweet's `screenshots` field contain a list (not a string)?
- Does the FIRST tweet have at least one screenshot? (hard rule)
- Is the same screenshot used on multiple tweets? (should not be)
- Does the context/background accurately describe what smart money consensus represents?
- Is the @nansen_ai mention present?
- ALSO CHECK: Are there any em dashes (-- or —) in the text? This is a hard rule violation.

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
- No em dashes (-- or —)? Hard rule. Search for every instance.
- No banned phrases?
- Background context included and concise?
- Numbers interpreted with a take, not just listed?
- No product pitch language?
- CT voice maintained throughout?
- First tweet has at least one screenshot attached?
- Screenshot filename valid? Only `market_consensus.png` is allowed.

Output a review as JSON:
```json
{"approved": true/false, "issues": ["issue 1", "issue 2"], "corrected_draft": null or {"tweets": [...], "style_used": "..."}}
```
If approved, set corrected_draft to null. If not, provide the corrected version.

### Merge reviewer feedback

After both 4a and 4b complete:
- If both approved: use the draft from Agent 3 as final.
- If either has issues: merge the corrections from both reviewers into one final draft. If corrections conflict, prefer the fact-checker's version for data accuracy and the style reviewer's version for tone/formatting.

## Step 5: Push to Typefully

After the merge step completes (the final draft is ready):

1. Parse the final JSON output to get the tweet texts and their `screenshots` lists.
2. Upload each unique screenshot file via the Typefully media API:
   ```python
   import asyncio, os
   from src.typefully_client import TypefullyClient
   client = TypefullyClient(
       api_key=os.environ['TYPEFULLY_API_KEY'],
       social_set_id=int(os.environ['TYPEFULLY_SOCIAL_SET_ID']),
   )
   media_map = {}
   for tweet in final_draft['tweets']:
       for filename in tweet.get('screenshots', []):
           if filename not in media_map:
               media_map[filename] = asyncio.run(client.upload_media(f'data/charts/{filename}'))
   ```
3. Build `per_post_media` and create the draft WITHOUT `publish_at` (this is a draft for human review):
   ```python
   per_post_media = []
   for tweet in final_draft['tweets']:
       ids = [media_map[f] for f in tweet.get('screenshots', []) if f in media_map]
       per_post_media.append(ids)

   result = asyncio.run(client.create_draft(
       posts=[t['text'] for t in final_draft['tweets']],
       title='Smart Money Consensus — DATE',
       per_post_media=per_post_media,
   ))
   print(result['private_url'])
   asyncio.run(client.close())
   ```
4. Print the Typefully draft URL to confirm success. This is a DRAFT. Do NOT set publish_at. The post needs human review before publishing.

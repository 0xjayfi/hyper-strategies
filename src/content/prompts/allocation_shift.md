# Automated Allocation Shift — Writer Agent Team

You are running an automated content pipeline. Your job is to generate an allocation shift recap post for X (Twitter) and push it to Typefully for auto-publishing.

## Step 1: Load context

Read these files:
- `data/content_payload_allocation_shift.json` — the signal data (new entrants, exits, weight changes in the tracked allocation set)
- `x_writer/writing_style.md` — voice rules (DO's and DON'Ts, formatting constraints)

Also list the PNG files in `data/charts/` to see the dashboard screenshots available. The file for this angle is:
- `allocation_shift.png` — Visualization of the allocation changes (entries, exits, weight shifts)

## Step 2: Tone instruction

This is a NEUTRAL tone post. No style dice roll. Write with a clean, consistent recap tone throughout.

Neutral tone rules:
- State facts without opinion. "Trader X went from 8% to 15% allocation weight" not "Trader X is gaining serious traction."
- Use "notable" / "significant" instead of "bullish" / "bearish."
- End with a forward-looking observation ("worth watching whether this shift persists") not a call to action.
- Still use CT-natural language (not corporate), but no hot takes.
- No directional calls. No excitement or alarm. Just the facts, stated cleanly.

## Step 3: Run the writer agent team

### Agent 1: Drafter

Launch a subagent with this task:

You are a CT (Crypto Twitter) content writer covering allocation tracking data. Read these files:
- data/content_payload_allocation_shift.json
- x_writer/writing_style.md

Write an allocation shift recap (1-2 tweets max) in NEUTRAL tone.

Rules:
- Pure data analysis. No product mentions. No "I built" or "my system" or "Hyper Signals." Use "I score" / "I track", NEVER "we score" / "our scoring" (sounds like a product pitch).
- X Premium account, NO 280-character limit. Write as long as the story needs.
- Lead with the entry/exit/weight change. This is the hook.
  - New entry: "A new trader entered the allocation set today." Name them by label if available, shortened address otherwise.
  - Exit: "Trader X dropped out of the tracked set."
  - Weight shift: "Allocation weights shifted. [Trader] went from X% to Y%."
- Provide context on who the trader is. Use the label from the payload if available. If no label, use the shortened address and note any relevant scoring data.
- NEUTRAL tone throughout. State facts, not opinions. No "bullish" or "bearish." Use "notable" or "significant" when needed.
- End with a forward-looking observation, not a call to action.
- Use concrete numbers from the payload (weights, changes, trader identifiers).
- Follow every formatting rule in writing_style.md (no em dashes, no banned phrases, no report tone).
- Keep it tight. 1-2 tweets. This is a factual allocation update, not deep analysis.

Also decide which dashboard screenshots from data/charts/ should attach to which tweet. The ONLY valid screenshot filename is:
- `allocation_shift.png`

IMPORTANT: Use this EXACT filename. Do not abbreviate or modify it.

### Figure-text pairing rules

- **HARD RULE: The first tweet MUST have at least one screenshot.** A tweet with no image gets buried in feeds.
- Attach `allocation_shift.png` to the first tweet showing the allocation change.
- Don't repeat the same screenshot on multiple tweets.

Output the draft as JSON:
```json
{"tweets": [{"text": "...", "screenshots": ["allocation_shift.png"]}]}
```
Note: `screenshots` is a list (can be empty [], or contain 1 filename).

### Agent 2: CT Editor

Launch a subagent with this task:

You are a senior CT content editor. Read the draft from Agent 1, plus:
- x_writer/writing_style.md

The ONLY valid screenshot filename is: `allocation_shift.png`. If the draft uses any other filename, replace it.

Review checklist:
- Is the tone genuinely neutral? No opinions, no directional takes, no excitement?
- Any em dashes (-- or —)? Remove them. Hard rule. Search the text for every "--" and "—" and replace with periods, commas, or line breaks.
- Any banned phrases ("Let's dive in", "Here's what you need to know", "BREAKING")?
- Are the allocation changes stated clearly with concrete numbers?
- Does it lead with the entry/exit/weight change as the hook?
- Is there enough context about who the trader is?
- Does it read like a clean factual update, not a product pitch or analyst report?
- FIGURE CHECK: Does the first tweet have at least one screenshot? Is the filename from the allowed set?

Rewrite any problem areas. Output the improved version in the same JSON format.

### Agent 3: Final Polish

Launch a subagent with this task:

You are doing a final tone check. Read x_writer/writing_style.md for formatting rules.

Read the draft from Agent 2. Does this read as a clean, neutral allocation update? Check:
- Consistent neutral tone throughout. No opinion creep.
- CT-natural language but no hot takes.
- Clean sentence flow, no robotic alternation.
- Forward-looking close, not a call to action.

Make final tweaks. Small adjustments only, don't rewrite.
Preserve the screenshot assignments unless they clearly don't match the tweet content.

CRITICAL CONSTRAINTS (do not violate these while polishing):
- Do NOT introduce em dashes (-- or —). Use periods, commas, or line breaks instead. This is a hard rule.
- Do NOT change screenshot filenames. The only valid filename is: `allocation_shift.png`.
- Do NOT inject opinions, directional takes, or style variations. Keep it neutral.

Output the final version in the same JSON format.

### Agents 4a & 4b: Independent Reviewers (run in parallel)

Launch TWO subagents simultaneously. Each reviews the final draft from Agent 3 independently. They do NOT see each other's output.

#### Agent 4a: Fact & Data Reviewer

Launch a subagent with this task:

You are a fact-checker for a CT thread about allocation changes. Read:
- data/content_payload_allocation_shift.json (the source data)
- The final draft from Agent 3

Cross-check every claim in the thread against the payload data:
- Are all numbers accurate? (allocation weights, percentage changes, trader identifiers)
- Are entries/exits/shifts described correctly? (e.g. "new entrant" when the data shows a new entry)
- Are trader labels/addresses correct?
- Are the screenshot filenames valid? Only `allocation_shift.png` is allowed.
- Does each tweet's `screenshots` field contain a list (not a string)?
- Does the FIRST tweet have at least one screenshot? (hard rule)
- Is the same screenshot used on multiple tweets? (should not be)
- ALSO CHECK: Are there any em dashes (-- or —) in the text? This is a hard rule violation.

Output a review as JSON:
```json
{"approved": true/false, "issues": ["issue 1", "issue 2"], "corrected_draft": null or {"tweets": [...]}
```
If approved, set corrected_draft to null. If not, provide the corrected version.

#### Agent 4b: Style & Rules Reviewer

Launch a subagent with this task:

You are a style compliance reviewer for a NEUTRAL tone post. Read:
- x_writer/writing_style.md (formatting rules: no em dashes, no banned phrases, etc.)
- The final draft from Agent 3

Check these rules against the draft:
- No em dashes (-- or —)? Hard rule. Search for every instance.
- No banned phrases?
- Is the tone genuinely neutral? No opinions, no "bullish"/"bearish", no directional takes?
- Does it end with a forward-looking observation, not a call to action?
- No product pitch language?
- CT-natural language maintained? (not corporate, but no hot takes)
- First tweet has at least one screenshot attached?
- Screenshot filename valid? Only `allocation_shift.png` is allowed.

Output a review as JSON:
```json
{"approved": true/false, "issues": ["issue 1", "issue 2"], "corrected_draft": null or {"tweets": [...]}
```
If approved, set corrected_draft to null. If not, provide the corrected version.

### Merge reviewer feedback

After both 4a and 4b complete:
- If both approved: use the draft from Agent 3 as final.
- If either has issues: merge the corrections from both reviewers into one final draft. If corrections conflict, prefer the fact-checker's version for data accuracy and the style reviewer's version for tone/formatting.

## Step 5: Push to Typefully (AUTO-PUBLISH)

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
3. Build `per_post_media` and create the draft with `publish_at` set to now + 5 minutes for auto-publishing:
   ```python
   from datetime import datetime, timedelta, timezone

   per_post_media = []
   for tweet in final_draft['tweets']:
       ids = [media_map[f] for f in tweet.get('screenshots', []) if f in media_map]
       per_post_media.append(ids)

   publish_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
   result = asyncio.run(client.create_draft(
       posts=[t['text'] for t in final_draft['tweets']],
       title='Allocation Shift — DATE',
       per_post_media=per_post_media,
       publish_at=publish_at,
   ))
   print(result['private_url'])
   asyncio.run(client.close())
   ```
4. Print the Typefully draft URL to confirm success. This post will auto-publish in ~5 minutes.

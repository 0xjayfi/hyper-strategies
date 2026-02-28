# Article Draft Review: "Why Most People Fail at Copy Trading on Hyperliquid"

**Reviewer:** Senior CT Content Editor
**Date:** 2026-02-27
**Compared Against:** Cryptor's Post #3 (Myth of ROI), Post #4 (Cracking the Crypto Game), Post #6 ($PIPPIN)

---

## Grade: B-

Strong opening energy that fades into a product pitch by mid-thread. Tweets 1-4 feel like a real trader. Tweets 5-7 and 11 feel like a startup demo day. Fixable, but needs a significant rewrite in the middle section.

---

## Top 3 Strengths

1. **The hook is legitimately good.** "Everyone on CT is copy trading Hyperliquid leaderboards based on total PnL. That's exactly why most of them lose money." Contrarian, specific, and attackable. People will quote-tweet this to argue. That's engagement.

2. **Tweets 3-4 are the best part of the thread.** The Pension vs 40x leverage traders comparison is concrete, visual, and makes the argument better than any abstract explanation could. This is exactly how Cryptor works: specific wallet, specific numbers, specific take.

3. **Tweet 9 is quotable.** "Most people pick traders the same way they pick memecoins. Find the biggest number, ape in, hope for the best. That's not a strategy. That's gambling with a nicer UI." This has the punchy rhythm and attitude that makes CT threads stick.

---

## Top 5 Issues

### Issue 1: FACTUAL ERROR on Liquidation Prices (Tweet 3)

> "Their liquidation prices sit around $23K."

Looking at the Position Explorer screenshot: "Top 100 on WBTC Leaderboard" has a liq price of $23,696. But "Former Smart Trader" has a liq price of **$49,992**. These are not "around $23K." One is $23K, the other is nearly $50K. This undermines credibility on a data-driven thread.

**Suggested rewrite:**
```
Look at this. Two traders both long BTC at $24M+, both running 40x leverage.

One gets liquidated at $23K. The other at $50K. Both are one bad wick away from total wipeout. If you copied these wallets, you'd be staring at the same liquidation screen.
```

### Issue 2: Tweet 7 is a Product Spec, Not a Trader's Insight

> "The system uses softmax to convert scores into portfolio weights. No single trader gets more than ~22%. Weights rebalance every 6 hours based on updated performance. If a trader starts deteriorating or gets liquidated, capital shifts automatically."

This reads like documentation. No trader on CT talks like this. Cryptor never describes tools in technical terms. He describes WHAT HE DOES with the tools. Compare to Cryptor's actual voice: "I label them into tiers (1-3)... Then I set alert and based on the new signals I get from them, I reassess and reorder their tiers." He describes his personal process, not system architecture.

**Suggested rewrite:**
```
Scoring traders is half the equation. You also need to size your bets.

I cap any single trader at ~22% of the portfolio. Every 6 hours the weights shift based on who's actually performing. If someone gets liquidated or starts bleeding, their allocation drops automatically. No manual babysitting.
```

Notice: "I cap" instead of "the system uses softmax." First person. Personal process. Same information, completely different energy.

### Issue 3: Tweet 11 is a Straight Product Pitch

> "Been building Hyper Signals to automate all of this. Multi-dimensional scoring, dynamic allocation with softmax weighting, liquidation auto-blacklisting, and live position monitoring across Hyperliquid. All powered by @nansen_ai perp data."

This is a feature bullet list wearing a tweet costume. "Multi-dimensional scoring, dynamic allocation with softmax weighting, liquidation auto-blacklisting" is literally product copy. Compare this to how Cryptor closes threads:

- Post #4: "This is how you stop guessing and start playing crypto with an edge. This is the game of cracking crypto."
- Post #3: "Alpha is found by understanding behavior, not blindly trusting surface-level metrics."
- Post #6: "The moment one of them does, I'll know first."

Cryptor ends with a PHILOSOPHY or a PROMISE, not a feature list.

**Suggested rewrite:**
```
Been building this into a system I call Hyper Signals. Scores traders, sizes positions, kills exposure when someone blows up. All running on @nansen_ai perp data.

Still early. Still iterating. But if you're copy trading on Hyperliquid, at minimum stop picking traders by PnL alone. The leaderboard is bait. The edge is in the process. NFA.
```

### Issue 4: "Nine out of ten copy traders" is Lifted from Cryptor (Tweet 6)

> "Nine out of ten copy traders would have skipped these wallets based on PnL alone."

Cryptor in Post #4: "Nine out of ten people would have skipped this wallet."

This is nearly word-for-word. If Cryptor or his followers notice, this looks like copying, not homage. It also weakens the thread's own voice by borrowing someone else's phrasing too closely.

**Suggested rewrite:**
```
If you filtered by PnL alone, you'd skip every one of these wallets. Smart Money dominating the top of the leaderboard, not because they made the most, but because they trade the cleanest.
```

### Issue 5: Tweet 7 is Way Over 280 Characters

The full text of tweet 7 is approximately 335 characters. This is not tweetable without Twitter Blue's longer format. Tweets 3 and 10 are also borderline/over at ~300 and ~285 chars respectively.

Twitter threads from accounts like Cryptor's typically keep individual tweets tight. Even with Blue allowing longer posts, the visual rhythm of short punchy tweets is part of the CT aesthetic.

**For tweet 7, split or trim.** See the rewrite in Issue 2 above, which brings it closer to 280.

---

## Line-by-Line Notes

### Tweet 1
```
Everyone on CT is copy trading Hyperliquid leaderboards based on total PnL.

That's exactly why most of them lose money.
```
Good. Clean hook. The line break between the two sentences is smart for visual impact. Maybe slightly generic compared to Cryptor's openers which use specific dollar amounts or tokens ("Many platforms promote traders with 500% ROI and 90% win rates..."). Consider adding a specific claim.

Minor suggestion: "Everyone on CT" is broad. "Half of CT" or "90% of CT" with a number feels more like a take and less like a generalization.

### Tweet 2
```
The Hyperliquid leaderboard shows who made the most. It tells you nothing about how they made it.

40x leverage on a single coin with zero risk management? That's not skill. That's a coin flip that happened to land right. Copy that and you're not trading. You're praying.
```
Excellent. Best-written tweet in the thread. The rhythm is perfect: short declarative, then a question, then the punchline. "You're not trading. You're praying." is memorable. Keep as-is.

### Tweet 3
Apart from the factual error (see Issue 1), the structure is good. The image placement here is correct. You're showing the proof after making the claim.

> "One labeled 'Top 100 on WBTC Leaderboard.' The other tagged 'Former Smart Trader.'"

Good use of the actual trader labels from the screenshot. But "labeled" and "tagged" in back-to-back sentences feels repetitive. Use one word for both or vary more.

### Tweet 4
```
Now look at "Pension" sitting at $67M long BTC at 3x. Liquidation at $35K.
```
Good. Specific. Uses exact name and numbers from the screenshot.

> "The numbers that actually matter are always below the surface."

A bit cliche for a closer. Cryptor would be more direct. Something like: "PnL leaderboards hide this. Intentionally." More edge, less platitude.

### Tweet 5
```
So I built a scoring system that evaluates Hyperliquid perp traders across 6 dimensions, using @nansen_ai data:

Growth. Max Drawdown. Leverage Risk. Liquidation Distance. Diversity. Consistency.

No single number decides the ranking. A full profile does.
```
The @nansen_ai mention here feels natural. Good.

But "Growth. Max Drawdown. Leverage Risk. Liquidation Distance. Diversity. Consistency." listed out like this feels like a product features section. In Cryptor's Post #3, he lists what he looks for but frames them as personal criteria: "Here's what I look for: Early positioning in true runners... Conviction purchases... Focused portfolios..." That's personal. This is a spec sheet.

**Rewrite suggestion:**
```
So I built a scoring system. Not one number. Six dimensions, all from @nansen_ai perp data.

How fast are they growing? How bad do they draw down? Are they running insane leverage? How close to liquidation? How diversified? How consistent?

One metric lies. Six metrics tell a story.
```

### Tweet 6
> "The results are interesting."

Weak opener for a tweet. "Interesting" is a nothing word. Show, don't tell. Lead with what's actually interesting.

> "Smart Money wallets dominating the top, not because they made the most, but because they trade the smartest."

Good line. But it's carried by the structure, not the specifics. What does 0.80 score MEAN to someone who doesn't know the system? You need to ground this in something relatable.

**Rewrite suggestion:**
```
Top of the leaderboard is all Smart Money wallets. Not because they made the most. Because they score highest across all six axes.

Wallets most copy traders would never look at, consistently trading with controlled leverage, tight drawdowns, and diversified positions.
```

### Tweet 8
```
Then there's real time positioning.
```
"real time" should be "real-time" (compound adjective). Also, the transition from tweet 7 (allocation mechanics) to tweet 8 (market overview) is jarring. There's no connective tissue. It reads like two different threads stitched together.

**Rewrite suggestion for the transition:**
```
The scoring and allocation run on autopilot. But the market context matters just as much.

Right now, Smart Money Consensus across BTC, ETH, SOL, and HYPE is bearish. $850M in BTC positions, $932M in ETH. Meanwhile the leaderboard is packed with max leverage longs.

When the smart money and the leaderboard disagree, I trust the smart money.
```

### Tweet 9
Already flagged as strong. Keep mostly as-is. One note:

> "That's gambling with a nicer UI."

This is the best line in the thread. Consider using it as a pull quote or highlight.

### Tweet 10
```
Performance metrics without context are just noise. IMO this applies to both spot wallet tracking and perps.
```
The second sentence feels tacked on. "IMO this applies to both spot wallet tracking and perps" reads like a footnote, not a strong closer for a tweet. Either expand this into a real take or cut it.

**Rewrite suggestion:**
```
If you're allocating capital to perp traders, at minimum you should know their leverage habits, drawdown history, diversification, and how close they sit to liquidation.

PnL alone tells you who got lucky. Everything else tells you who'll stay profitable. IMO this is the same problem in spot wallet tracking. Everyone chases returns, nobody checks the risk.
```

### Tweet 11
See Issue 3. This needs a full rewrite. The "Still early, still iterating. But the edge is in the process, not the leaderboard. NFA." is good as a closer. Keep that energy. Kill the feature list.

---

## Screenshot Placement Review

| Tweet | Screenshot | Placement Quality |
|-------|-----------|------------------|
| 3 | position explorer.png | GOOD. Shows proof of the 40x leverage claim right after stating it. |
| 5 | trader leaderboard.png | OK. Shows the scoring system. But it's placed after the dimension list, making it feel like a product demo. Would be stronger placed after tweet 6 ("Smart Money wallets dominating the top") as proof of the claim. |
| 7 | allocation dashboard.png | WEAK. Placed in the most product-pitchy tweet. Makes it feel like a sales deck. |
| 8 | market overview.png | GOOD. The bearish consensus visual supports the narrative point about disagreement between smart money and leaderboard. |

**Recommendation:** Move the leaderboard screenshot to tweet 6 and rewrite tweet 5 without it. Consider whether the allocation dashboard screenshot is necessary at all. It might be stronger to just describe the concept and let people come find the tool, rather than showing a full product screenshot.

---

## Vibe Check

The first four tweets are genuinely good CT writing. Sharp, opinionated, backed by real data, with the right amount of attitude. If the whole thread had this energy, it would be an A-/B+ piece.

But starting at tweet 5, the thread has an identity crisis. It can't decide if it's an analyst sharing hard-won insights (Cryptor's lane) or a founder pitching a product (startup Twitter's lane). The word "softmax" appears TWICE. No one on CT uses "softmax" in a thread. That's a technical term that signals "I'm explaining my code" not "I'm sharing alpha."

Compare the overall arc to Cryptor's threads:
- **Cryptor Post #3:** Problem (metrics lie) -> Specific wallet example -> His personal evaluation criteria -> Takeaway (behavior > metrics). The tool (Nansen) is mentioned as part of his workflow, never the star.
- **Cryptor Post #4:** Who dominates crypto -> His process step-by-step -> Case study with $U1 -> Wallet tiers and alerts -> Philosophy closer. Again, tools are props, not protagonists.
- **This draft:** Problem (leaderboards lie) -> Specific examples (great) -> Product features (loses the plot) -> Market data (good) -> Product pitch (loses it again).

The fix is structural: make the PROCESS the hero, not the PRODUCT. Instead of "the system uses softmax," say "I weight the portfolio so no single trader dominates." Instead of listing six technical dimension names, frame them as questions you'd ask about any trader. Instead of a feature list at the end, close with a philosophy.

The thread is 80% of the way there. The 20% that needs fixing is the difference between "real trader sharing alpha" and "dev launching a product." CT can smell a shill from a mile away. Right now, tweets 7 and 11 smell like shill.

Kill the technical jargon. Make it personal. Let the product be discovered, not pitched.

---

## Quick Checklist Summary

| Criteria | Status | Notes |
|----------|--------|-------|
| Em dashes | PASS | None found |
| Banned phrases | PASS | None found |
| Voice authenticity | PARTIAL | Strong opening, product-pitchy middle |
| Data interpretation | GOOD | Most numbers have takes attached |
| CT lingo | PASS | Natural usage of ape, NFA, IMO, CT |
| Sentence rhythm | GOOD | Great in tweets 1-4, 9. Monotone in 7 |
| Hook strength | GOOD | Strong contrarian opener |
| Screenshot placement | MIXED | Tweets 3, 8 good. Tweet 7 feels salesy |
| Product shill vs insight | FAIL | Tweets 5-7, 11 cross the line |
| Thread flow | PARTIAL | Jarring transitions at 6->7 and 7->8 |
| Tweet length | PARTIAL | Tweets 3, 7 over 280 chars |
| Cryptor vibe match | PARTIAL | First half yes, second half no |
| Factual accuracy | FAIL | Liq prices in tweet 3 are wrong |
| Emoji usage | PASS | No overuse |
| @nansen_ai mention | PASS | Natural in tweet 5 context |

---

## Priority Fixes (in order)

1. **Fix the factual error** in tweet 3 (liquidation prices)
2. **Rewrite tweet 7** to remove "softmax" and product-spec language. Make it personal process, not system architecture
3. **Rewrite tweet 11** to close with philosophy, not a feature list. Kill the second "softmax" mention
4. **Rewrite tweet 6** opener. Drop "The results are interesting." Add specifics instead of the Cryptor-borrowed "nine out of ten" line
5. **Smooth the 7->8 transition.** Add connective tissue between allocation mechanics and market overview
6. **Trim tweets 3 and 7** to fit within or near 280 characters
7. **Move leaderboard screenshot** from tweet 5 to tweet 6
8. **Reframe tweet 5** dimensions as questions instead of a feature list

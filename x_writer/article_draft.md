# Why Most People Fail at Copy Trading on Hyperliquid

**Style:** Contrarian (#5) — "Everyone's doing X, that's why they lose"
**Topic:** PnL leaderboards lie, multi-dimensional scoring reveals the truth, introducing Hyper Signals

---

**1/**
Everyone on CT is copy trading Hyperliquid leaderboards based on total PnL.

That's exactly why most of them lose money.

**2/**
The Hyperliquid leaderboard shows who made the most. It tells you nothing about how they made it.

40x leverage on a single coin with zero risk management? That's not skill. That's a coin flip that happened to land right. Copy that and you're not trading. You're praying.

**3/**
Look at this. Two traders both long BTC at $24M+, both running 40x leverage. One labeled "Top 100 on WBTC Leaderboard." The other tagged "Former Smart Trader."

Their liquidation prices sit around $23K. One bad wick and $50M in positions gets vaporized. If you copied these wallets, you'd be gone too.

[IMAGE: position explorer.png]

**4/**
Now look at "Pension" sitting at $67M long BTC at 3x. Liquidation at $35K. That's conviction with actual risk management. Completely different trader profile, but a PnL leaderboard would never show you this difference.

The numbers that actually matter are always below the surface.

**5/**
So I built a scoring system that evaluates Hyperliquid perp traders across 6 dimensions, using @nansen_ai data:

Growth. Max Drawdown. Leverage Risk. Liquidation Distance. Diversity. Consistency.

No single number decides the ranking. A full profile does.

[IMAGE: trader leaderboard.png]

**6/**
The results are interesting. Traders you've never heard of score 0.80 across all six axes. Smart Money wallets dominating the top, not because they made the most, but because they trade the smartest.

Nine out of ten copy traders would have skipped these wallets based on PnL alone.

**7/**
Scoring is only half the problem. You also need to turn scores into capital allocation.

The system uses softmax to convert scores into portfolio weights. No single trader gets more than ~22%. Weights rebalance every 6 hours based on updated performance. If a trader starts deteriorating or gets liquidated, capital shifts automatically.

[IMAGE: allocation dashboard.png]

**8/**
Then there's real time positioning. Smart Money Consensus across BTC, ETH, SOL, and HYPE is bearish right now. $850M in BTC positions, $932M in ETH.

When every smart money signal says bearish and the leaderboard is packed with max leverage longs, that gap tells you everything.

[IMAGE: market overview.png]

**9/**
Copy trading isn't the problem. Blind copy trading is.

Most people pick traders the same way they pick memecoins. Find the biggest number, ape in, hope for the best. That's not a strategy. That's gambling with a nicer UI.

**10/**
If you're allocating capital to perp traders, at minimum you need to know their leverage habits, drawdown history, how diversified they are, and how close they sit to liquidation. Not just their PnL.

Performance metrics without context are just noise. IMO this applies to both spot wallet tracking and perps.

**11/**
Been building Hyper Signals to automate all of this. Multi-dimensional scoring, dynamic allocation with softmax weighting, liquidation auto-blacklisting, and live position monitoring across Hyperliquid. All powered by @nansen_ai perp data.

Still early, still iterating. But the edge is in the process, not the leaderboard. NFA.

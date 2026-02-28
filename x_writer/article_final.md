# The Hyperliquid Leaderboard Is Lying to You. I Built a Better Scoreboard.

### Why I built Hyper Signals

I got tired of the Hyperliquid leaderboard lying to me.

Copy trading on Hyperliquid is massive right now. Most people pick who to follow the same way they pick memecoins: find the biggest number on the PnL board and ape in. But PnL hides everything that actually matters. Leverage risk. Drawdown history. Concentration. How close a trader is sitting to liq at any given moment. Two wallets with the same profit can have completely different risk profiles, and one of them is a ticking bomb.

So I built something. I call it Hyper Signals. I pulled months of perp trade data from @nansen_ai and scored traders across six dimensions instead of one. Growth, drawdowns, leverage habits, liquidation distance, diversification, consistency. The scoring exposed what the leaderboard buries: some "top traders" are reckless, and some wallets nobody talks about trade cleaner than the whales at the top.

This article walks through the whole thing. How I read the market before touching any trade. How I evaluate individual positions. How I score and rank traders, size my allocations, and vet any wallet CT throws at me. All of it built on @nansen_ai API data, because without months of trade history you're just guessing.

I'll start with a position that proves the point.

------

The #2 BTC position on Hyperliquid right now is a $25M long at 40x leverage, entered at $100K, already down $14.5M unrealized. The wallet is labeled "Top 100 on WBTC Leaderboard." If you saw that label and copied the trade, you'd be staring at the same loss right now.

The Hyperliquid leaderboard ranks by total PnL. It tells you who made the most, not how they made it. Months of clean trading and one leveraged bet that happened to land right look identical on the board. That difference matters. Especially if you're about to put real capital behind one of these wallets.

I started tracking what these wallets actually do between the big wins. Leverage habits, how deep they've been in the red, how close they sit to liq. Pulled a few months of @nansen_ai trade data and scored them on the stuff that PnL hides. Some "top traders" scored worse than wallets I'd never heard of. I'll get to those scores. But it doesn't matter how good a trader is if you're copying them into a market that's about to move against everyone. 

------

### Where smart money is positioned right now

Before I look at any individual trader, I check the macro picture. Four tokens. BTC, ETH, SOL, HYPE. Open interest, direction, and where smart money is leaning.

[IMAGE: market overview.png]

Look at the bottom first. Smart Money Consensus: bearish across all four tokens. BTC bearish. ETH bearish. SOL bearish. HYPE bearish. When every smart money signal points the same direction across all four markets, that's not noise. Real money all saying the same thing.

BTC: $850M open interest, 48/52 long-short. Fine. But ETH is where it gets weird. $932M in positions, retail leaning long, smart money still bearish. When retail and smart money disagree, I pay attention. SOL thin at $227M, HYPE at $344M with longs paying shorts on funding. If you're about to enter a long on any of these, every smart money signal says the opposite.

------

### What individual positions actually look like

Aggregate numbers only tell half the story. You need to see who's holding what, at what leverage, and how close they are to getting wiped.

[IMAGE: position explorer.png]

This is BTC right now. $326M long vs $329M short, L/S ratio at 0.99, almost perfectly balanced. But look at the individual positions.

Pension is #1 with $67M long BTC at 3x. Entry at $66,865 with a liq at $35,835 gives a 47% buffer, and the position is already up $1.1M unrealized. Big position, low leverage, and it's printing.

Now look at #2. "Top 100 on WBTC Leaderboard." Long $24.9M at 40x, entered at $100,838, already bleeding $14.5M in unrealized losses. Liq price? $23,696, actually 65% below current mark, but that's not the real problem. They entered $33K above current price. Every day BTC doesn't rally back above $101K, this position bleeds harder.

Then there's "Former Smart Trader." Also 40x. Also ~$25M. But with liq at $49,992, only 26% below current price. One bad wick and it evaporates. Two traders both running 40x, both around $25M in size. One gets liquidated at a 65% drawdown. The other at 26%. Risk is not one number.

A PnL leaderboard treats all three the same. Pension at 3x survives a 47% drawdown before liquidation. The "Former Smart Trader" at 40x? Dead at 26%. Copy the wrong one and that distinction becomes your tuition.

------

### What separates traders who survive from traders who got lucky

Seeing those risk differences is one thing. Putting numbers on them is another. Instead of ranking by PnL, I score traders on six things that actually matter.

How fast are they growing? How well do they control drawdowns? How degen is their leverage? Are they running 50x into one coin, or running it clean like Pension? I also look at how far they are from liq, how spread out they are, and whether they keep printing or fall off after a hot streak.

Growth and not getting rekt matter most to me, as much as everything else put together. Survival over flash. The rest comes down to how reckless their leverage is, how close they sit to liq, and whether they spread risk or concentrate it. @nansen_ai Smart Money wallets? I trust those more right away because that label already cuts out most of the noise. Go quiet? Dropped.

Here's where it gets interesting. Look at who actually rises to the top when you score this way.

[IMAGE: trader leaderboard.png]

Current top 6 are all Smart Money labeled wallets. Every single one.

The #1 trader scores 0.80. Growth isn't flashy. But this wallet barely ever bleeds, sits nowhere close to getting wiped, and never goes heavy on one coin. Drawdown 0.99, liq distance 1.00, diversity 0.88. This trader would barely register on a PnL leaderboard. But if you're deciding who to follow with real money? That's what I'm looking for. Not flashy. Not reckless. Spread out.

Token Millionaire at #3 never loads up on one coin, always spread out and sitting far from liq. Yield Farmer at #5 barely ever takes an L. These wallets don't ape 40x into one coin and pray. They're not gambling.

When you stop sorting by profit and start looking at how they actually trade, the rankings look completely different. The top wallets? Ones most copy traders would scroll right past. I've seen addresses from the top of the PnL leaderboard score below 0.40. High growth, sure. But constantly in the red, reckless leverage, and all-in on one coin. The PnL number made them look elite. The numbers said otherwise.

------

### How I decide position sizing

So now I have a ranked list. But a high score alone doesn't get you into the pool if you're not actively putting on positions. Right now? Five wallets. The next question is the one most copy traders never ask: how much capital does each one get?

No single trader gets more than about a fifth of the bag. I move size around based on who's actually performing. Someone starts bleeding? I cut them. Liquidated? Benched. They need weeks of clean trading before I trust them with size again.

[IMAGE: allocation dashboard.png]

Five in the pool right now, with the top four getting roughly equal size. The fifth gets less. Not bad, just not as sharp. Most copy traders put everything behind one wallet and wonder why they blow up.

Over the past 10 days, I've been moving size between them based on who's hot. Someone slips? Cut. Whoever's hot gets more size. Not set-and-forget. I'm in the dashboard every day.

I also check whether my top traders are all leaning the same way on each token. When most are long BTC, that's a strong signal. When they're split? Reason to stay cautious. That's how I size each trade.

------

### Running any wallet through the same filter

That's how it runs day to day. But every week CT surfaces a new "alpha wallet" someone swears by. Before I add anyone to the pool, they go through the same scoring. Same filter every time.

I pull months of trade history from @nansen_ai. Either the numbers back up the hype or they don't.

The thing I watch closest is whether the returns are real or lucky. 90%+ win rate? That's suspicious, not impressive. High PnL from one oversized trade? I fade that immediately. Profitable over 7 days? Cool. Now show me 30 and 90. One lucky week doesn't cut it.

"This trader is printing" means nothing until you see the actual numbers behind it. IMO most wallets that get promoted as alpha would score average or below when you actually run the numbers. I've been wrong before. One whale was up 400% in 30 days and looked like a clear top scorer. Ran the full analysis. Weak. Single outsized trade carried the entire PnL, and their leverage was completely degen. That's the whole point. Numbers don't lie.

------

### What I'm still getting wrong

I don't have this dialed in yet. I'm too harsh on traders who go quiet a few days, even when they come back strong. Only tracking four tokens. And I'm still figuring out how fast to cut. Bad stretch vs a rough day? Haven't solved that yet.

But if you're going to follow another trader's positions, PnL is the last thing you should look at. Leverage habits and how deep they've been in the red. How spread out they are. How close they sit to liq.

Working on automated execution next. If it holds up with real capital, I'll post the results.

PnL is what happened. Everything else tells you what happens next. NFA.

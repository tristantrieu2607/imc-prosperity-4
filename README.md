# IMC Prosperity 4

A collection of algorithmic trading bots and research notebooks built for the **IMC Prosperity 4** trading competition. The competition runs across 5 rounds, with new products introduced each round. This repo contains per-round trader implementations, exploratory data analysis (EDA) notebooks, backtesting logs, and a custom log viewer.

---

## Repository Structure

```
imc-prosperity-4/
├── Trader.py              # Active trader submitted to the exchange (latest version)
├── traders/               # Per-round trader scripts
│   ├── tutorialTrader.py
│   ├── round1Trader.py
│   ├── round2Trader.py
│   ├── round3Trader.py
│   ├── round4Trader.py
│   ├── round5Trader.py
│   └── github_1.py
├── research/              # Jupyter notebooks for EDA per round
│   ├── eda_tutorial_round.ipynb
│   ├── eda_round_1.ipynb
│   ├── eda_round_2.ipynb
│   ├── eda_round_3.ipynb
│   ├── eda_round_4.ipynb
│   └── eda_round_5.ipynb
├── data/                  # Market data used for research and backtesting
├── backtests/             # Backtest log output files (timestamped .log)
├── traderVersions/        # Historical snapshots of trader versions
├── log_viewer.html        # Browser-based log viewer for inspecting backtest logs
└── __pycache__/
```

---

## Round-by-Round Breakdown

### Tutorial Round

**Products:** `EMERALDS`, `TOMATOES`

Simple market making: post passive buy/sell quotes around a fair value, and aggressively take when prices move enough. Inventory skewing keeps positions from drifting too large. The tutorial EDA established the baseline data pipeline used in all later rounds.

---

### Round 1

**Products:** `ASH_COATED_OSMIUM`, `INTARIAN_PEPPER_ROOT`

Two new products with distinct personalities — osmium is stationary (mean-reverting around 10,000) while pepper has an upward drift. The strategy uses a microprice (volume-weighted average of best bid and ask) with an EMA-smoothed fair value to quote around, combined with inventory skewing.

**EDA:** Price process analysis, autocorrelation, spread distribution, and order book depth inspection to characterise each product's behaviour.

---

### Round 2

**Products:** Same — `ASH_COATED_OSMIUM`, `INTARIAN_PEPPER_ROOT`

No new products — Round 2 is effectively three more sample days from the same distribution as Round 1. The trader was improved with a faster EMA for pepper (since it drifts) and a slower one for osmium (since it's stationary). The EDA confirmed the underlying process was unchanged and quantified the drift and mean-reversion parameters more precisely.

---

### Round 3

**Products:** `HYDROGEL_PACK`, `VELVETFRUIT_EXTRACT` (underlying), `VEV_4000` / `VEV_4500` / `VEV_5000` / `VEV_5100` / `VEV_5200` / `VEV_5300` / `VEV_5400` / `VEV_5500` / `VEV_6000` / `VEV_6500` (call options), `XIRECS` (currency)

The big new addition is an **options chain** on VELVETFRUIT_EXTRACT — each VEV_XXXX product is a call option at a different strike price.

- **HYDROGEL_PACK:** Passive market making using a Kalman filter to track fair value and quote just inside the best bid/ask.
- **VEV options:** Z-score mean reversion — each option's mid is compared to a rolling anchor price. If it drifts too far, the trader bets on reversion. A bullish bias signal is added when the VEV_5200/5300 spread is very tight, nudging the fair value estimate up by 2 ticks.

**EDA (5 passes):** Data integrity checks → underlying price behaviour (drift, volatility, autocorrelation) → option chain shape (calls vs intrinsic/time value) → implied volatility surface and vol smile → HYDROGEL_PACK parity and no-arb bounds.

---

### Round 4

**Products:** Same as Round 3 (HYDROGEL_PACK, VELVETFRUIT_EXTRACT, VEV_4000–VEV_5400)

The strategy was restructured into a cleaner two-piece architecture:

- **HYDROGEL_PACK:** Replaced the z-take approach with a proper passive market maker — quotes at floor(mid)−1 / ceil(mid)+1 by default, skews tighter when inventory builds, and respects a soft cap of ±40.
- **VEV options:** Z-score take system refined with order book imbalance signals — if the imbalance strongly favours the direction being traded against (i.e. liquidity is flowing the wrong way), the trade is vetoed. Boost multiplier applied when imbalance aligns.
- The bot also identifies market maker counterparties ("Mark 14", "Mark 01", "Mark 49") vs noise traders to inform sizing decisions.

**EDA:** PnL breakdown per counterparty (mark), bid-ask spread analysis, options intrinsic vs time value, and analysis of which marks generate consistent flow to trade against.

---

### Round 5

**Products (32 total across 8 groups):**
- **SNACKPACK:** `SNACKPACK_CHOCOLATE`, `SNACKPACK_VANILLA`, `SNACKPACK_PISTACHIO`, `SNACKPACK_RASPBERRY`, `SNACKPACK_STRAWBERRY`
- **PEBBLES:** `PEBBLES_XL`, `PEBBLES_L`, `PEBBLES_M`, `PEBBLES_S`, `PEBBLES_XS`
- **MICROCHIP:** `MICROCHIP_CIRCLE`, `MICROCHIP_OVAL`, `MICROCHIP_RECTANGLE`, `MICROCHIP_TRIANGLE`
- **GALAXY SOUNDS:** `GALAXY_SOUNDS_BLACK_HOLES`, `GALAXY_SOUNDS_DARK_MATTER`, `GALAXY_SOUNDS_PLANETARY_RINGS`, `GALAXY_SOUNDS_SOLAR_FLAMES`, `GALAXY_SOUNDS_SOLAR_WINDS`
- **UV VISOR:** `UV_VISOR_AMBER`, `UV_VISOR_MAGENTA`, `UV_VISOR_ORANGE`, `UV_VISOR_RED`, `UV_VISOR_YELLOW`
- **OXYGEN SHAKE:** `OXYGEN_SHAKE_CHOCOLATE`, `OXYGEN_SHAKE_EVENING_BREATH`, `OXYGEN_SHAKE_GARLIC`, `OXYGEN_SHAKE_MINT`, `OXYGEN_SHAKE_MORNING_BREATH`
- **Other:** `ROBOT_LAUNDRY`, `SLEEP_POD_LAMB_WOOL`, `PANEL_2X2`

A three-layer trading stack:

**Layer 1 — Stationary spread pairs (primary earner):**
- SNACKPACK_CHOCOLATE + SNACKPACK_VANILLA: their mid-prices sum to ~2000 and mean-revert. A z-score computed over a rolling 500-tick window triggers long/short the spread when it hits ±1.5σ, exits at ±0.3σ.
- PEBBLES_XL vs the basket {XS, S, M, L}: the XL price and the sum of the 4 smaller pebble mids are negatively correlated. Traded the same z-score way with a looser entry threshold.

**Layer 2 — Per-group directional (placeholder):**
Short-horizon mean reversion on 100-tick log returns for MICROCHIP, GALAXY_SOUNDS, UV_VISOR, and OXYGEN_SHAKE groups. Kept at very small size while signal weights were being validated.

**Layer 3 — Passive market making (fillers):**
Inventory-skewed passive quotes on the quietest products not already used by Layers 1 or 2 (SNACKPACK_PISTACHIO, SNACKPACK_RASPBERRY, SNACKPACK_STRAWBERRY, ROBOT_LAUNDRY, SLEEP_POD_LAMB_WOOL, PANEL_2X2). Hard position cap = 10.

**EDA (9 sections):** Load & sanity check → feature engineering (microprice deviation, L1/total imbalance, rolling volatility, log returns at multiple horizons) → per-group mid price plots → within-group correlation & lead-lag → imbalance→drift relationship → group-specific structure (PANEL areas, PEBBLES ladder, SNACKPACK persistence) → feature-to-future-return Spearman correlation table → **linear Ridge regression baseline** (sklearn) as a sanity check before considering heavier models. The EDA explicitly concluded that signal magnitudes were too small and training data too short (3 days) for an ML model to add reliable edge over the structural spread trades.

---

## Backtesting

Backtest logs are stored in `backtests/` as timestamped `.log` files. To inspect them visually, open `log_viewer.html` in your browser and load a log file.

---

## Contributors

- [tristantrieu2607](https://github.com/tristantrieu2607)
- [denisle06](https://github.com/denisle06)

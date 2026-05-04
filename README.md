# IMC Prosperity 4

A collection of algorithmic trading bots and research notebooks built for the **IMC Prosperity 4** trading competition. The competition runs across 5 rounds, introducing new tradeable products each round. This repository contains per-round trader implementations, exploratory data analysis (EDA) notebooks, backtesting infrastructure, and a custom log viewer.

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
├── backtests/             # Backtest log output files
├── traderVersions/        # Historical snapshots of trader versions
├── log_viewer.html        # Browser-based log viewer for inspecting backtest logs
└── __pycache__/
```

---

## Rounds & Products Traded

| Round    | Products |
|----------|----------|
| Tutorial | EMERALDS, TOMATOES |
| Round 1  | ASH_COATED_OSMIUM, INTARIAN_PEPPER_ROOT |
| Round 2  | + additional products |
| Round 3  | + additional products |
| Round 4  | + additional products |
| Round 5  | SNACKPACK_CHOCOLATE, SNACKPACK_VANILLA, PEBBLES_XL, MICROCHIP_*, GALAXY_SOUNDS_*, UV_VISOR_*, OXYGEN_SHAKE_*, SNACKPACK_PISTACHIO, SNACKPACK_RASPBERRY, SNACKPACK_STRAWBERRY, ROBOT_LAUNDRY, SLEEP_POD_LAMB_WOOL, PANEL_2X2 |

---

## Trading Strategies

### Tutorial / Early Rounds

- **Market Making with inventory skewing**: passive bid/ask quotes with spread and position-aware skew to manage inventory risk.
- **TAKE orders**: aggressively cross the spread when price is sufficiently favourable relative to a fair value estimate.

### Round 5 — Three-Layer Stack

**Layer 1 — Stationary Spreads (primary earner)**

- `SNACKPACK_CHOCOLATE` + `SNACKPACK_VANILLA`: the sum of their mid-prices is mean-reverting around ~2000. A z-score signal triggers long/short the spread.
- `PEBBLES_XL` vs the basket {XS, S, M, L}: the sum of all 5 pebble mids trades as one direction.

**Layer 2 — Per-group Directional (placeholder)**

- Short-horizon mean reversion on 100-tick returns for select products (MICROCHIP, GALAXY, UV_VISOR, OXYGEN_SHAKE). Kept at small size until signal weights are validated.

**Layer 3 — Passive Market Making (fillers)**

- Inventory-skewed passive quotes on the calmest, lowest-volume products not already consumed by Layers 1 or 2 (e.g. SNACKPACK_PISTACHIO, SNACKPACK_RASPBERRY, SNACKPACK_STRAWBERRY, ROBOT_LAUNDRY, SLEEP_POD_LAMB_WOOL, PANEL_2X2).

**Risk Overlay**

- Hard position cap = 10 (IMC limit). Soft cap = 7.
- Conflicts between layers resolved in order: spreads first, directional second, market making third.
- Each layer reads `state.position` fresh to avoid double-counting.

---

## Backtesting

Backtest logs are stored in `backtests/` as timestamped `.log` files. To inspect them visually, open `log_viewer.html` in your browser and load a log file.

---

## Contributors

- [tristantrieu2607](https://github.com/tristantrieu2607)
- [denisle06](https://github.com/denisle06)

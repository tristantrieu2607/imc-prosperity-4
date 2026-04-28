"""
Round 4 — z_take v5: v4 + HYDROGEL extension scale-out.

The drawdown analysis (cell-by-cell over round-4 day-1 data):

  Position pinned at -200 short for 1380 ticks.
  During those 1380 ticks, mid drifted from 9967 to 10081 (+114).
  z stayed in (+0.5, +1.5) range the whole time (still says "sell more").
  Existing logic: at limit -> can't sell, won't buy (z>0) -> watch the bleed.
  MTM cost: -114 * 200 = -22,800. Exactly the observed drawdown.

The fix is HYDROGEL-only and ONLY activates when we're at extension AND
price is still moving against us (adverse drift). It triggers a partial
scale-out at much weaker z than the normal flatten point (z=0).

  pos extension >= 80%, adverse drift -> scale out 5  at z=+0.6 (or -0.6)
  pos extension >= 90%, adverse drift -> scale out 10 at z=+0.4
  pos extension >= 95%, adverse drift -> scale out 20 at z=+0.2

Adverse drift = mid trend over last ~150 ticks moves further against position.
We persist a tiny ring buffer of recent mids in traderData, HP only.

Other products are NOT modified. Their structure is different (smaller
absolute sigma * limit product), they never get pinned in this regime.
"""

import json
from typing import Any
from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState



class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: str) -> None:
        base_length = len(self.to_json([self.compress_state(state, ""), self.compress_orders(orders), conversions, "", ""]))
        max_item_length = (self.max_log_length - base_length) // 3
        print(self.to_json([
            self.compress_state(state, self.truncate(state.traderData, max_item_length)),
            self.compress_orders(orders),
            conversions,
            self.truncate(trader_data, max_item_length),
            self.truncate(self.logs, max_item_length),
        ]))
        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [state.timestamp, trader_data, self.compress_listings(state.listings),
                self.compress_order_depths(state.order_depths), self.compress_trades(state.own_trades),
                self.compress_trades(state.market_trades), state.position, self.compress_observations(state.observations)]

    def compress_listings(self, listings):
        return [[l.symbol, l.product, l.denomination] for l in listings.values()]

    def compress_order_depths(self, order_depths):
        return {s: [od.buy_orders, od.sell_orders] for s, od in order_depths.items()}

    def compress_trades(self, trades):
        return [[t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp]
                for arr in trades.values() for t in arr]

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        for product, obs in observations.conversionObservations.items():
            conversion_observations[product] = [
                obs.bidPrice, obs.askPrice, obs.transportFees,
                obs.exportTariff, obs.importTariff, obs.sugarPrice, obs.sunlightIndex,
            ]
        return [observations.plainValueObservations, conversion_observations]

    def compress_orders(self, orders):
        return [[o.symbol, o.price, o.quantity] for arr in orders.values() for o in arr]

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        lo, hi = 0, min(len(value), max_length)
        out = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."
            if len(json.dumps(candidate)) <= max_length:
                out = candidate; lo = mid + 1
            else:
                hi = mid - 1
        return out


logger = Logger()

# ============================================================================
# Per-product config (UNCHANGED from v4)
# ============================================================================

CFGS = [
    {"symbol": "HYDROGEL_PACK",       "mean": 9994, "sd": 32.588, "z_thresh": 1.0, "take_size": 17, "limit": 200, "inv_penalty": False},
    {"symbol": "VELVETFRUIT_EXTRACT", "mean": 5247, "sd": 17.091, "z_thresh": 1.0, "take_size": 17, "limit": 200, "inv_penalty": False},
    {"symbol": "VEV_4000",            "mean": 1247, "sd": 17.114, "z_thresh": 1.0, "take_size": 17, "limit": 300, "inv_penalty": False},
    {"symbol": "VEV_4500",            "mean":  747, "sd": 17.105, "z_thresh": 1.0, "take_size": 17, "limit": 300, "inv_penalty": False},
    {"symbol": "VEV_5000",            "mean":  252, "sd": 16.381, "z_thresh": 1.2, "take_size": 17, "limit": 300, "inv_penalty": True},
    {"symbol": "VEV_5100",            "mean":  163, "sd": 15.327, "z_thresh": 1.2, "take_size": 17, "limit": 300, "inv_penalty": True},
    {"symbol": "VEV_5200",            "mean":   91, "sd": 12.796, "z_thresh": 1.2, "take_size": 17, "limit": 300, "inv_penalty": True},
    {"symbol": "VEV_5300",            "mean":   43, "sd":  8.976, "z_thresh": 1.0, "take_size": 17, "limit": 300, "inv_penalty": True},
    {"symbol": "VEV_5400",            "mean":   14, "sd":  4.608, "z_thresh": 1.0, "take_size": 17, "limit": 300, "inv_penalty": True},
]

IMB_VETO_THRESH    = 0.10
IMB_BOOST_THRESH   = 0.30
IMB_BOOST_MULT     = 1.40

SMART_MARKS = ("Mark 14", "Mark 01", "Mark 49")
DUMB_MARKS  = ("Mark 38", "Mark 55", "Mark 22")
RECENT_TRADE_LOOKBACK = 5

# ============================================================================
# HP extension scale-out tuning
# ============================================================================
# Extension thresholds, exit-z thresholds, and exit sizes are tiered.
# Numbers chosen to:
#   - Never fire below 80% extension (preserves normal MR edge)
#   - Get progressively more aggressive as we approach the wall
#   - Use modest sizes so we don't overshoot into a now-flat position
HP_EXIT_TIERS = [
    # (extension_min, z_threshold, exit_size)
    (0.80, 0.60,  5),
    (0.90, 0.40, 10),
    (0.95, 0.20, 20),
]
# Adverse-drift window in TIMESTAMP units (each call advances ts by 100 in IMC).
# 150 ticks = 15000 ts. We require the EMA-short to differ from EMA-long
# by at least HP_DRIFT_MIN_PTS in the adverse direction.
HP_DRIFT_LOOKBACK_TS = 15000
HP_DRIFT_MIN_PTS     = 2.0     # min adverse drift (in price units) to trigger
HP_MID_HISTORY_MAX   = 200     # cap on mid history we persist (~20k ts of memory)


# ============================================================================
# Top-of-book imbalance (UNCHANGED)
# ============================================================================

def _l1_imbalance(depth):
    if not depth.buy_orders or not depth.sell_orders:
        return 0.0
    best_bid = max(depth.buy_orders)
    best_ask = min(depth.sell_orders)
    bid_vol = abs(depth.buy_orders[best_bid])
    ask_vol = abs(depth.sell_orders[best_ask])
    total = bid_vol + ask_vol
    if total <= 0:
        return 0.0
    return (bid_vol - ask_vol) / total


# ============================================================================
# Counterparty modulator (UNCHANGED)
# ============================================================================

def _counterparty_mult(state, sym, our_side):
    trades = state.market_trades.get(sym, []) or []
    if not trades:
        return 1.0
    trades = sorted(trades, key=lambda t: t.timestamp, reverse=True)[:RECENT_TRADE_LOOKBACK]
    mult = 1.0
    for t in trades:
        filler    = t.seller if our_side > 0 else t.buyer
        same_side = t.buyer  if our_side > 0 else t.seller
        if filler in SMART_MARKS:
            mult *= 0.85
        if same_side in DUMB_MARKS:
            mult *= 1.10
    return max(0.5, min(1.15, mult))


# ============================================================================
# Book walker (UNCHANGED)
# ============================================================================

def _walk_book(depth, side, sym, ok, qty_target):
    if side > 0:
        prices = sorted(depth.sell_orders)
        book = depth.sell_orders
    else:
        prices = sorted(depth.buy_orders, reverse=True)
        book = depth.buy_orders
    out, filled = [], 0
    for px in prices:
        if filled >= qty_target or not ok(px):
            break
        qty = min(abs(book[px]), qty_target - filled)
        if qty <= 0:
            break
        out.append(Order(sym, px, side * qty))
        filled += qty
    return out, filled


# ============================================================================
# HP-only: extension scale-out
# ============================================================================

def _hp_check_scale_out(state, depth, mid, pos, limit, store):
    """
    Returns a list of orders if a scale-out should fire, else None.
    None means: defer to normal _z_take_orders logic.

    Conditions for scale-out (ALL must hold):
      1. |pos| / limit >= 0.80 (extension)
      2. We have at least HP_DRIFT_LOOKBACK_TS of mid history
      3. Drift in the last window is moving AGAINST our position
         (mid rising while we're short, or falling while we're long)
         by at least HP_DRIFT_MIN_PTS.
      4. The current z (signed by position direction) is past the tier's
         exit threshold but NOT yet at z=0 flatten (where normal logic
         would already be exiting).

    If all met, emit a closing order of the tier-appropriate size.
    """
    if pos == 0:
        return None
    extension = abs(pos) / limit
    if extension < HP_EXIT_TIERS[0][0]:
        return None

    # Update history (always, regardless of trigger). Use timestamp for proper time
    # spacing — the IMC engine advances by 100 ts per call.
    history = store.get("mids", [])
    history.append([state.timestamp, mid])
    # Drop entries older than 2x the lookback to bound memory
    cutoff = state.timestamp - 2 * HP_DRIFT_LOOKBACK_TS
    history = [h for h in history if h[0] >= cutoff]
    if len(history) > HP_MID_HISTORY_MAX:
        history = history[-HP_MID_HISTORY_MAX:]
    store["mids"] = history

    # Need a reference point at least HP_DRIFT_LOOKBACK_TS ago
    ref_ts = state.timestamp - HP_DRIFT_LOOKBACK_TS
    ref_mid = None
    for h in history:
        if h[0] <= ref_ts:
            ref_mid = h[1]
        else:
            break
    if ref_mid is None:
        return None  # not enough history yet

    drift = mid - ref_mid           # positive = mid rising over the window
    # Adverse direction: if pos > 0 (long), adverse drift is mid FALLING (drift < 0).
    # If pos < 0 (short), adverse drift is mid RISING (drift > 0).
    if pos > 0:
        adverse_drift = -drift      # long, falling = positive adverse
    else:
        adverse_drift = drift       # short, rising = positive adverse
    if adverse_drift < HP_DRIFT_MIN_PTS:
        return None  # drift not adverse enough

    # Current z and signed-z (relative to position)
    mean, sd = 9994, 32.588
    z = (mid - mean) / sd
    # signed_z: how much z still favors holding the current position.
    # If short (pos < 0), z > 0 means "still want to be short" — favorable for holding.
    # If long  (pos > 0), z < 0 means "still want to be long".
    if pos < 0:
        signed_z = z       # for shorts: positive z = still want to be short
    else:
        signed_z = -z      # for longs: negative z = still want to be long, flip sign

    # Pick the most aggressive tier whose extension threshold we meet
    tier = None
    for ext_min, z_thresh, size in HP_EXIT_TIERS:
        if extension >= ext_min:
            tier = (ext_min, z_thresh, size)
    if tier is None:
        return None
    ext_min, z_thresh, exit_size = tier

    # Trigger only if signed_z is in the band (z_thresh, 1.0).
    # Below z_thresh: not yet pinned-bleeding state.
    # Above 1.0: still strong reversion signal, holding still has high EV.
    # Inside the band: weak reversion + adverse drift = scale out.
    if signed_z <= z_thresh or signed_z >= 1.0:
        return None

    # Also: don't fire if the imbalance is screaming in our favor — that means
    # reversion may be imminent. Use the same threshold as the existing veto.
    imb = _l1_imbalance(depth)
    # Imbalance favorable to our position means: if short, imb < 0; if long, imb > 0.
    favorable_imb = imb if pos > 0 else -imb
    if favorable_imb > IMB_BOOST_THRESH:
        return None  # market saying reversion is coming, hold the line

    # Emit the exit order. Direction: opposite of current position sign.
    sym = "HYDROGEL_PACK"
    if pos < 0:
        # Short -> buy to cover. Walk the asks, take whatever's available.
        target = min(exit_size, abs(pos))
        orders, _ = _walk_book(depth, +1, sym, lambda px: True, target)
    else:
        # Long -> sell. Walk the bids.
        target = min(exit_size, pos)
        orders, _ = _walk_book(depth, -1, sym, lambda px: True, target)
    return orders if orders else None


# ============================================================================
# Per-product z-take with imbalance veto + boost (UNCHANGED from v4)
# ============================================================================

def _z_take_orders(state, cfg, hp_store=None):
    sym = cfg["symbol"]
    depth = state.order_depths.get(sym)
    if not depth or not depth.buy_orders or not depth.sell_orders:
        return []
    mid = (max(depth.buy_orders) + min(depth.sell_orders)) / 2.0
    mean, sd = cfg["mean"], cfg["sd"]
    if sd <= 0:
        return []
    z = (mid - mean) / sd

    pos = state.position.get(sym, 0)
    limit = cfg["limit"]

    # ================ NEW: HP scale-out check (HP only) ================
    if sym == "HYDROGEL_PACK" and hp_store is not None:
        scale_out = _hp_check_scale_out(state, depth, mid, pos, limit, hp_store)
        if scale_out is not None:
            return scale_out
    # ===================================================================

    base_thresh = cfg["z_thresh"]
    take_size = cfg["take_size"]

    if cfg.get("inv_penalty", False):
        if z > 0:
            inv_pressure = max(0, -pos) / limit
        else:
            inv_pressure = max(0, pos) / limit
        eff_thresh = base_thresh + 0.4 * inv_pressure
    else:
        eff_thresh = base_thresh

    if abs(z) < eff_thresh:
        return []

    imb = _l1_imbalance(depth)

    if z > 0:
        if imb > IMB_VETO_THRESH:
            return []
        room = max(0, min(take_size, limit + pos))
        if room <= 0:
            return []
        cp_mult = _counterparty_mult(state, sym, our_side=-1)
        imb_mult = IMB_BOOST_MULT if imb < -IMB_BOOST_THRESH else 1.0
        room = max(1, int(round(room * cp_mult * imb_mult)))
        room = min(room, limit + pos)
        orders, _ = _walk_book(depth, -1, sym, lambda px: px >= mean, room)
        return orders

    if imb < -IMB_VETO_THRESH:
        return []
    room = max(0, min(take_size, limit - pos))
    if room <= 0:
        return []
    cp_mult = _counterparty_mult(state, sym, our_side=+1)
    imb_mult = IMB_BOOST_MULT if imb > IMB_BOOST_THRESH else 1.0
    room = max(1, int(round(room * cp_mult * imb_mult)))
    room = min(room, limit - pos)
    orders, _ = _walk_book(depth, +1, sym, lambda px: px <= mean, room)
    return orders


# ============================================================================
# Trader
# ============================================================================

class Trader:
    def bid(self):
        return 0

    def run(self, state: TradingState):
        # Load HP-only state. Everything else is stateless. If parsing fails,
        # fall back to fresh state — degrades to v4 behavior, never crashes.
        try:
            store = json.loads(state.traderData) if state.traderData else {}
            if not isinstance(store, dict):
                store = {}
        except Exception:
            store = {}
        hp_store = store.setdefault("HP", {})

        orders: dict[str, list[Order]] = {}
        for cfg in CFGS:
            ors = _z_take_orders(state, cfg, hp_store=hp_store if cfg["symbol"] == "HYDROGEL_PACK" else None)
            if ors:
                orders[cfg["symbol"]] = ors

        # Persist only HP state. Keep payload tiny.
        try:
            out_data = json.dumps(store, separators=(",", ":"))
        except Exception:
            out_data = ""
        return orders, 0, out_data
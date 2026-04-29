"""
Round 4 — z_take v4 + HP-only passive market maker.

For HYDROGEL_PACK only, replaces the z-take with a tiny-position MM that
quotes both sides near fair and bounds drawdown by design.

Why the swap (HP only):
  - HP has the largest sigma * limit product in the book (32.6 * 200).
    That's the worst possible inventory failure mode.
  - Mark 14 makes +32k linear on HP doing exactly this — passive MM.
  - z-take builds inventory on the way out then pins at the limit during
    drift episodes. We've patched this 3 ways (scale-out, EMA, throttle)
    and none worked. Fix the architecture instead.

Design:
  Soft position cap: ±40 (20% of hard limit)
  Hard position cap: ±80 (we never quote past this)
  Quote at floor(mid)-1 / ceil(mid)+1 by default
  Skew quotes when inventory builds: tighten the side that flattens
  Skip the side that would cross the soft cap
  Imbalance veto kept (same threshold as v4): skip the side that would
    take adversely-flowing liquidity

PnL ceiling: lower than v4 by design. Drawdown ceiling: bounded.
Worst case: pinned at +80 long, mid drifts down 30 -> -2400 MTM.
That's the upper bound. v4 worst case was -22.8k.

Everything non-HP unchanged from v4.
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
# Per-product config — HYDROGEL_PACK row removed (handled separately below)
# ============================================================================

CFGS = [
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
# HP MM tuning — single place to adjust everything
# ============================================================================

HP_MEAN          = 9994        # for sanity-bounding fair
HP_SOFT_LIMIT    = 40          # don't quote past this on the building side
HP_HARD_LIMIT    = 80          # absolute max position we'll ever hold
HP_BASE_SIZE     = 15          # default quote size each side
HP_BASE_OFFSET   = 1           # ticks from floor(mid)/ceil(mid)
HP_SKEW_OFFSET   = 2           # extra ticks on the building side when inventoried
HP_SKEW_TRIGGER  = 20          # |pos| above which we start skewing


# ============================================================================
# Top-of-book imbalance (UNCHANGED from v4)
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
# Counterparty modulator (UNCHANGED from v4)
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
# Book walker (UNCHANGED from v4)
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
# HYDROGEL_PACK: small-position passive market maker
# ============================================================================

def _hp_mm_orders(state):
    """
    Quote both sides near fair, with inventory-aware skew and hard caps.

    Decisions per tick:
      1. fair = mid (book-derived, no state needed)
      2. bid_offset / ask_offset depend on inventory:
         - flat: symmetric (1/1)
         - long (pos > +SKEW_TRIGGER): widen bid (3), tighten ask (1)
           -> we sell more easily, buy less easily
         - short (pos < -SKEW_TRIGGER): tighten bid (1), widen ask (3)
      3. Skip the side that would push past soft limit
      4. Size capped by hard limit room
      5. L1 imbalance veto: don't post on the side that the book is fading

    This is stateless. No traderData needed.
    """
    sym = "HYDROGEL_PACK"
    depth = state.order_depths.get(sym)
    if not depth or not depth.buy_orders or not depth.sell_orders:
        return []

    best_bid = max(depth.buy_orders)
    best_ask = min(depth.sell_orders)
    if best_bid >= best_ask:
        return []  # crossed/locked book, skip

    mid = (best_bid + best_ask) / 2.0
    pos = state.position.get(sym, 0)

    # Sanity check: if mid is wildly off the long-run mean, the book is
    # in some unusual state. Don't be a maker into possible regime change.
    if abs(mid - HP_MEAN) > 100:
        return []

    # Decide offsets based on inventory direction
    if pos > HP_SKEW_TRIGGER:
        bid_off = HP_BASE_OFFSET + HP_SKEW_OFFSET   # 3
        ask_off = HP_BASE_OFFSET                    # 1
    elif pos < -HP_SKEW_TRIGGER:
        bid_off = HP_BASE_OFFSET                    # 1
        ask_off = HP_BASE_OFFSET + HP_SKEW_OFFSET   # 3
    else:
        bid_off = HP_BASE_OFFSET                    # 1
        ask_off = HP_BASE_OFFSET                    # 1

    # Compute quote prices, anchored to integer mid
    import math
    bid_px = int(math.floor(mid)) - bid_off
    ask_px = int(math.ceil(mid)) + ask_off

    # Don't cross our own quotes; don't quote at or past the touch.
    # We want to be PASSIVE makers, not takers.
    if bid_px >= best_ask:
        bid_px = best_ask - 1
    if ask_px <= best_bid:
        ask_px = best_bid + 1
    if bid_px >= ask_px:
        return []

    # Sizing: respect both soft and hard limits
    # On the BID side (buying), we'd grow pos -> check upper limits
    # On the ASK side (selling), we'd shrink pos -> check lower limits
    bid_room = max(0, HP_HARD_LIMIT - pos)
    ask_room = max(0, HP_HARD_LIMIT + pos)

    # Soft limit: stop building past +/- SOFT_LIMIT
    if pos >= HP_SOFT_LIMIT:
        bid_size = 0
    else:
        bid_size = min(HP_BASE_SIZE, bid_room, HP_SOFT_LIMIT - pos)

    if pos <= -HP_SOFT_LIMIT:
        ask_size = 0
    else:
        ask_size = min(HP_BASE_SIZE, ask_room, HP_SOFT_LIMIT + pos)

    # Imbalance veto: if book strongly favors a side, don't quote into it.
    # imb > 0 means buyers winning at top of book -> aggressive buying ->
    #   our ask is likely to get lifted by adverse takers. Skip ask.
    # imb < 0 means sellers winning -> our bid is likely to be hit by adverse takers.
    imb = _l1_imbalance(depth)
    if imb > IMB_VETO_THRESH:
        ask_size = 0
    if imb < -IMB_VETO_THRESH:
        bid_size = 0

    orders = []
    if bid_size > 0:
        orders.append(Order(sym, bid_px, int(bid_size)))
    if ask_size > 0:
        orders.append(Order(sym, ask_px, -int(ask_size)))
    return orders


# ============================================================================
# Per-product z-take (UNCHANGED from v4 — used for non-HP only)
# ============================================================================

def _z_take_orders(state, cfg):
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
        orders: dict[str, list[Order]] = {}

        # HP: passive MM with bounded position
        hp_ors = _hp_mm_orders(state)
        if hp_ors:
            orders["HYDROGEL_PACK"] = hp_ors

        # Everything else: unchanged v4 z-take
        for cfg in CFGS:
            ors = _z_take_orders(state, cfg)
            if ors:
                orders[cfg["symbol"]] = ors

        return orders, 0, ""
"""
Round 3 v14 — v12 base + simplified HP + VEX bullish bias on tight-spread signal.

v12 baseline: +25,739 (HP +76, VEX+VEV +25,663)

v14 changes:
1. HP: penny inside best (414624.py pattern), Kalman fair as guardrail.
   Goal: capture more spread per tick instead of quoting at fair±3.

2. VEX: when both VEV_5200 and VEV_5300 spreads <= 2, shift fair_static up by
   2 ticks (5275 -> 5277). EDA showed +0.53 mean forward 20-step return when
   this signal fires. Small shift; doesn't dominate existing alpha.

3. VEV options: COMPLETELY UNCHANGED. They make ~+10K each across the chain.
"""

import json
import math

from datamodel import Order, TradingState

TAKE_WIDTH = 1
ANCHOR_WARMUP = 100
DIVERGE_TAKE_SIZE = 30

# v14: VEX bullish bias signal params
TIGHT_SPREAD_TH = 2          # VEV_5200/5300 spread <= this triggers signal
VEX_BULLISH_SHIFT = 2        # add this to VEX fair_static when signal fires


def search_sells(depth):
    for p in sorted(depth.sell_orders):
        yield p, -depth.sell_orders[p]


def search_buys(depth):
    for p in sorted(depth.buy_orders, reverse=True):
        yield p, depth.buy_orders[p]


def full_depth_mid(depth):
    bids, asks = list(search_buys(depth)), list(search_sells(depth))
    bv, av = sum(v for _, v in bids), sum(v for _, v in asks)
    if bv <= 0 or av <= 0:
        return (max(depth.buy_orders) + min(depth.sell_orders)) / 2
    return (sum(p * v for p, v in bids) / bv + sum(p * v for p, v in asks) / av) / 2


# =========================================================================
# Zscore pipeline (VEV_*) — UNCHANGED
# =========================================================================


def divergence_take_orders(cfg, depth, scratch, position, anchor, mid):
    threshold = cfg.get("diverge_threshold", 0)
    if threshold <= 0 or scratch.get("anchor_n", 0) < ANCHOR_WARMUP:
        return [], 0, 0
    diverge = mid - anchor
    if abs(diverge) < threshold:
        return [], 0, 0

    product, limit = cfg["product"], cfg["position_limit"]
    max_pos = cfg.get("max_diverge_position", 60)
    out, bought, sold = [], 0, 0
    if diverge > 0 and position > -max_pos:
        room = position + max_pos
        for price, qty in search_buys(depth):
            cap = min(limit + position - sold, DIVERGE_TAKE_SIZE - sold, room - sold)
            if cap <= 0:
                break
            take = min(qty, cap)
            out.append(Order(product, price, -take))
            sold += take
    elif diverge < 0 and position < max_pos:
        room = max_pos - position
        for price, qty in search_sells(depth):
            cap = min(limit - position - bought, DIVERGE_TAKE_SIZE - bought, room - bought)
            if cap <= 0:
                break
            take = min(qty, cap)
            out.append(Order(product, price, take))
            bought += take
    return out, bought, sold


def take_orders(cfg, depth, fair, position):
    product, limit = cfg["product"], cfg["position_limit"]
    out, bought, sold = [], 0, 0
    for price, qty in search_sells(depth):
        if price >= fair - TAKE_WIDTH:
            break
        cap = limit - position - bought
        if cap <= 0:
            break
        take = min(qty, cap)
        out.append(Order(product, price, take))
        bought += take
    for price, qty in search_buys(depth):
        if price <= fair + TAKE_WIDTH:
            break
        cap = limit + position - sold
        if cap <= 0:
            break
        take = min(qty, cap)
        out.append(Order(product, price, -take))
        sold += take
    return out, bought, sold


def make_quote(cfg, fair, best_bid, best_ask, position, bought, sold):
    product, limit = cfg["product"], cfg["position_limit"]
    qsize = cfg.get("quote_size", 20)
    bid_px = min(math.floor((fair + best_bid) / 2), best_ask - 1)
    ask_px = max(math.ceil((fair + best_ask) / 2), best_bid + 1)
    buy = max(0, min(qsize, limit - position - bought))
    sell = max(0, min(qsize, limit + position - sold))
    out = []
    if buy > 0 and bid_px < ask_px:
        out.append(Order(product, bid_px, buy))
    if sell > 0 and ask_px > bid_px:
        out.append(Order(product, ask_px, -sell))
    return out


def zscore_orders(cfg, state, scratch):
    depth = state.order_depths.get(cfg["product"])
    if not depth or not depth.buy_orders or not depth.sell_orders:
        return []

    best_bid = max(depth.buy_orders)
    best_ask = min(depth.sell_orders)
    mid = (best_bid + best_ask) / 2
    fair = full_depth_mid(depth)

    n = scratch.get("anchor_n", 0) + 1
    s = scratch.get("anchor_sum", 0.0) + mid
    scratch["anchor_n"], scratch["anchor_sum"] = n, s
    anchor = s / n
    position = state.position.get(cfg["product"], 0)

    diverge, d_bought, d_sold = divergence_take_orders(
        cfg, depth, scratch, position, anchor, mid
    )
    pos_eff = position + d_bought - d_sold
    takes, bought, sold = take_orders(cfg, depth, fair, pos_eff)
    bought += d_bought
    sold += d_sold
    quotes = make_quote(cfg, fair, best_bid, best_ask, position, bought, sold)
    return diverge + takes + quotes


# =========================================================================
# v14: simple HP — penny inside best, Kalman fair as guardrail
# =========================================================================


def hp_simple_orders(state, store):
    """
    Simple HP: penny inside best bid/ask. Kalman fair as guardrail
    so we never quote on the wrong side of fair when book is unbalanced.
    """
    depth = state.order_depths.get("HYDROGEL_PACK")
    if not depth or not depth.buy_orders or not depth.sell_orders:
        return []

    best_bid = max(depth.buy_orders)
    best_ask = min(depth.sell_orders)
    bv = depth.buy_orders[best_bid]
    av = -depth.sell_orders[best_ask]
    tot = bv + av
    micro = (best_bid * av + best_ask * bv) / tot if tot > 0 else (best_bid + best_ask) / 2.0

    # Kalman track (slow, just for guardrail)
    fair = store.get("_f", micro)
    k_ss = 0.05    # faster than v12 (was 0.02), tracks better
    innov = micro - fair
    err_ema = store.get("_err", abs(innov))
    err_ema += k_ss * (abs(innov) - err_ema)
    fair += (k_ss / (1.0 + err_ema)) * innov
    store["_f"], store["_err"] = fair, err_ema

    position = state.position.get("HYDROGEL_PACK", 0)
    limit = 200

    # --- Penny inside best ---
    my_bid = best_bid + 1
    my_ask = best_ask - 1
    if my_bid >= my_ask:
        my_bid = my_ask - 1

    # --- Guardrail: don't quote bid above fair+1 or ask below fair-1 ---
    if my_bid > fair + 1:
        my_bid = int(math.floor(fair + 1))
    if my_ask < fair - 1:
        my_ask = int(math.ceil(fair - 1))

    # --- Inventory-based asymmetric sizing ---
    # When long, smaller bid / larger ask (push toward flat)
    # When short, larger bid / smaller ask
    base_size = 30
    skew_th = 50
    if position > skew_th:
        bid_size = max(0, base_size // 3)
        ask_size = base_size + 10
        # Also nudge quotes
        my_bid -= 1
    elif position < -skew_th:
        bid_size = base_size + 10
        ask_size = max(0, base_size // 3)
        my_ask += 1
    else:
        bid_size = base_size
        ask_size = base_size

    # Hard inventory cap at 150 (still 50 buffer below 200 limit)
    if position >= 150:
        bid_size = 0
    elif position <= -150:
        ask_size = 0

    # Respect actual exchange limits
    bid_size = min(bid_size, limit - position)
    ask_size = min(ask_size, limit + position)

    orders = []
    if bid_size > 0 and my_bid < my_ask:
        orders.append(Order("HYDROGEL_PACK", int(my_bid), int(bid_size)))
    if ask_size > 0 and my_ask > my_bid:
        orders.append(Order("HYDROGEL_PACK", int(my_ask), -int(ask_size)))

    return orders


# =========================================================================
# Kalman-MR pipeline (VEX) — UNCHANGED except for tight-spread bias
# =========================================================================


def kalman_mr_orders(cfg, depth, position, scratch, fair_static_override=None):
    if not depth or not depth.buy_orders or not depth.sell_orders:
        return []
    product = cfg["product"]
    limit = cfg["position_limit"]
    bb = max(depth.buy_orders)
    ba = min(depth.sell_orders)
    bv_tob = depth.buy_orders[bb]
    av_tob = -depth.sell_orders[ba]
    tot = bv_tob + av_tob
    micro = (bb * av_tob + ba * bv_tob) / tot if tot > 0 else (bb + ba) / 2.0
    mid = (bb + ba) / 2.0

    k_ss = cfg["k_ss"]
    fair = scratch.get("_f", micro)
    innov = micro - fair
    err_ema = scratch.get("_err", abs(innov))
    err_ema += k_ss * (abs(innov) - err_ema)
    fair += (k_ss / (1.0 + err_ema)) * innov
    scratch["_f"], scratch["_err"] = fair, err_ema

    n = scratch.get("_n", 0) + 1
    s2 = scratch.get("_s2", 0.0) + (mid - fair) ** 2
    scratch["_n"], scratch["_s2"] = n, s2
    sigma = max(1.0, (s2 / n) ** 0.5) if n > 50 else cfg["sigma_init"]

    anchor = fair_static_override if fair_static_override is not None else cfg["fair_static"]
    target = max(-limit, min(limit, round(cfg["mr_gain"] * (anchor - mid) / sigma)))

    take_max_pay = cfg["take_max_pay"]
    quote_edge = cfg["quote_edge"]
    quote_size = cfg["quote_size"]

    orders = []
    bv = sv = 0
    delta = target - position

    if delta > 0:
        for a in sorted(depth.sell_orders):
            if a > fair + take_max_pay:
                break
            room = min(-depth.sell_orders[a], delta - bv, limit - position - bv)
            if room <= 0:
                break
            orders.append(Order(product, a, room))
            bv += room
    elif delta < 0:
        need = -delta
        for b in sorted(depth.buy_orders, reverse=True):
            if b < fair - take_max_pay:
                break
            room = min(depth.buy_orders[b], need - sv, limit + position - sv)
            if room <= 0:
                break
            orders.append(Order(product, b, -room))
            sv += room

    baaf = min((p for p in depth.sell_orders if p >= fair + quote_edge), default=None)
    bbbf = max((p for p in depth.buy_orders if p <= fair - quote_edge), default=None)
    if bbbf is not None:
        buy_q = min(quote_size, limit - position - bv)
        if buy_q > 0:
            orders.append(Order(product, bbbf + 1, buy_q))
    if baaf is not None:
        sell_q = min(quote_size, limit + position - sv)
        if sell_q > 0:
            orders.append(Order(product, baaf - 1, -sell_q))

    return orders


# =========================================================================
# Tight-spread VEX bias signal
# =========================================================================


def check_vex_bullish_signal(state):
    """Return True when both VEV_5200 and VEV_5300 spreads <= TIGHT_SPREAD_TH."""
    for sym in ("VEV_5200", "VEV_5300"):
        d = state.order_depths.get(sym)
        if not d or not d.buy_orders or not d.sell_orders:
            return False
        spread = min(d.sell_orders) - max(d.buy_orders)
        if spread > TIGHT_SPREAD_TH:
            return False
    return True


# =========================================================================
# Per-product configuration
# =========================================================================

VEX_CFG = {
    "product": "VELVETFRUIT_EXTRACT",
    "position_limit": 200,
    "k_ss": 0.02,
    "fair_static": 5275,
    "mr_gain": 2000,
    "sigma_init": 15.0,
    "take_max_pay": -2,
    "quote_edge": 1,
    "quote_size": 30,
}

ZSCORE_PRODUCTS = [
    {"product": "VEV_4000", "position_limit": 300, "quote_size": 30, "diverge_threshold": 20, "max_diverge_position": 295},
    {"product": "VEV_4500", "position_limit": 300, "quote_size": 30, "diverge_threshold": 20, "max_diverge_position": 295},
    {"product": "VEV_5000", "position_limit": 300, "quote_size": 30, "diverge_threshold": 18, "max_diverge_position": 295},
    {"product": "VEV_5100", "position_limit": 300, "quote_size": 30, "diverge_threshold": 14, "max_diverge_position": 295},
    {"product": "VEV_5200", "position_limit": 300, "quote_size": 30, "diverge_threshold": 11, "max_diverge_position": 295},
    {"product": "VEV_5300", "position_limit": 300, "quote_size": 30, "diverge_threshold": 8, "max_diverge_position": 295},
    {"product": "VEV_5400", "position_limit": 300, "quote_size": 30, "diverge_threshold": 4, "max_diverge_position": 295},
    {"product": "VEV_5500", "position_limit": 300, "quote_size": 30, "diverge_threshold": 2, "max_diverge_position": 295},
]


class Trader:
    def bid(self):
        return 0

    def run(self, state: TradingState):
        try:
            store = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            store = {}

        orders: dict[str, list[Order]] = {}

        # 1) HP — simple penny inside best with Kalman guardrail
        hp_store = store.setdefault("HYDROGEL_PACK", {})
        hp_orders = hp_simple_orders(state, hp_store)
        if hp_orders:
            orders["HYDROGEL_PACK"] = hp_orders

        # 2) VEX — Kalman MR with tight-spread bullish bias
        vex_depth = state.order_depths.get(VEX_CFG["product"])
        bullish = check_vex_bullish_signal(state)
        anchor_override = (VEX_CFG["fair_static"] + VEX_BULLISH_SHIFT) if bullish else None
        vex_orders = kalman_mr_orders(
            VEX_CFG, vex_depth,
            state.position.get(VEX_CFG["product"], 0),
            store.setdefault(VEX_CFG["product"], {}),
            fair_static_override=anchor_override,
        )
        if vex_orders:
            orders[VEX_CFG["product"]] = vex_orders

        # 3) VEV options — completely unchanged
        for cfg in ZSCORE_PRODUCTS:
            ors = zscore_orders(cfg, state, store.setdefault(cfg["product"], {}))
            if ors:
                orders[cfg["product"]] = ors

        return orders, 0, json.dumps(store)
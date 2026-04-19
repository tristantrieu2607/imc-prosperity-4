# -*- coding: utf-8 -*-
"""
attempt16 - invSkewPennyJump + floorHolding MarketT&M
Format: attempt12 structure
Logic:  attempt15 improvements, bugs fixed, resources optimized
"""

from datamodel import OrderDepth, TradingState, Order
from typing import List, Tuple, Optional
import json


class Trader:

    LIMITS = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }

    # ---------- OSMIUM constants ----------
    OSMIUM_FAIR   = 10_000
    OSMIUM_SKEW_T = 40        # inventory threshold before active flattening

    # ---------- PEPPER constants ----------
    # Asset has ~10% upward drift over the session — we want to CAPTURE that drift,
    # not churn against it. Strategy: hold near the limit, earn MM spread on top,
    # and only sell when someone pays a real premium above current fair.
    PEPPER_EMA_ALPHA     = 0.05   # slower EMA so fair tracks trend, not noise
    PEPPER_FLOOR         = 70     # aggressively long — near the 80 limit
    PEPPER_SELL_PREMIUM  = 3      # only sell if bid >= fair + 3 (earn the drift)
    PEPPER_PASSIVE_EDGE  = 2      # passive ask sits fair + 2 above fair

    # ------------------------------------------------------------------ #
    #  Entry point                                                         #
    # ------------------------------------------------------------------ #
    def run(self, state: TradingState):
        result = {}
        trader_data: dict = json.loads(state.traderData) if state.traderData else {}

        for product, order_depth in state.order_depths.items():
            position = state.position.get(product, 0)

            if product == "ASH_COATED_OSMIUM":
                orders, trader_data = self.trade_osmium(
                    product, order_depth, position, trader_data
                )
            elif product == "INTARIAN_PEPPER_ROOT":
                orders, trader_data = self.trade_pepper(
                    product, order_depth, position, trader_data
                )
            else:
                orders = []

            result[product] = orders

        return result, 0, json.dumps(trader_data)

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _best(order_depth):  # type: (OrderDepth) -> Tuple[Optional[int], Optional[int]]
        """Return (best_bid, best_ask) or None if side is empty."""
        bid = max(order_depth.buy_orders)  if order_depth.buy_orders  else None
        ask = min(order_depth.sell_orders) if order_depth.sell_orders else None
        return bid, ask

    # ------------------------------------------------------------------ #
    #  OSMIUM — stationary asset, pure market-making + pennying           #
    # ------------------------------------------------------------------ #
    def trade_osmium(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
        trader_data: dict,
    ) -> Tuple[List[Order], dict]:

        orders: List[Order] = []
        limit      = self.LIMITS[product]
        fair_value = self.OSMIUM_FAIR

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders, trader_data

        buy_vol = sell_vol = 0

        # --- Step 1: Take obvious mispricings ---
        for ask, qty in sorted(order_depth.sell_orders.items()):
            if ask >= fair_value:
                break
            can_buy = limit - (position + buy_vol)
            if can_buy <= 0:
                break
            fill = min(abs(qty), can_buy)
            orders.append(Order(product, ask, fill))
            buy_vol += fill

        for bid, qty in sorted(order_depth.buy_orders.items(), reverse=True):
            if bid <= fair_value:
                break
            can_sell = limit + (position - sell_vol)
            if can_sell <= 0:
                break
            fill = min(qty, can_sell)
            orders.append(Order(product, bid, -fill))
            sell_vol += fill

        pos_after_take = position + buy_vol - sell_vol

        # --- Step 2: Inventory flatten (soft skew towards flat) ---
        if pos_after_take > self.OSMIUM_SKEW_T:
            excess   = pos_after_take - self.OSMIUM_SKEW_T
            can_sell = limit + (position - sell_vol)
            fill     = min(excess, can_sell)
            if fill > 0:
                orders.append(Order(product, fair_value, -fill))
                sell_vol += fill

        elif pos_after_take < -self.OSMIUM_SKEW_T:
            excess  = abs(pos_after_take) - self.OSMIUM_SKEW_T
            can_buy = limit - (position + buy_vol)
            fill    = min(excess, can_buy)
            if fill > 0:
                orders.append(Order(product, fair_value, fill))
                buy_vol += fill

        # --- Step 3: Passive penny quotes ---
        # Default to ±1 around fair; improve by pennying the best resting order
        # that is not a singleton (size > 1) and is not adjacent to fair.
        my_bid = fair_value - 1
        my_ask = fair_value + 1

        for bp, bv in sorted(order_depth.buy_orders.items(), reverse=True):
            if bv > 1 and bp < fair_value - 1:
                my_bid = bp + 1
                break

        for sp, sv in sorted(order_depth.sell_orders.items()):
            if abs(sv) > 1 and sp > fair_value + 1:
                my_ask = sp - 1
                break

        # Safety: never cross our own passive quotes
        if my_bid >= my_ask:
            my_bid, my_ask = fair_value - 1, fair_value + 1

        can_buy  = limit - (position + buy_vol)
        can_sell = limit + (position - sell_vol)

        if can_buy  > 0:
            orders.append(Order(product, my_bid,  can_buy))
        if can_sell > 0:
            orders.append(Order(product, my_ask, -can_sell))

        return orders, trader_data

    # ------------------------------------------------------------------ #
    #  PEPPER — persistently upward-drifting asset                        #
    #  Strategy: capture the drift (hold high) + earn MM spread on top.   #
    # ------------------------------------------------------------------ #
    def trade_pepper(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
        trader_data: dict,
    ) -> Tuple[List[Order], dict]:

        orders: List[Order] = []
        limit         = self.LIMITS[product]
        floor         = self.PEPPER_FLOOR
        sell_premium  = self.PEPPER_SELL_PREMIUM
        passive_edge  = self.PEPPER_PASSIVE_EDGE

        best_bid, best_ask = self._best(order_depth)
        if best_bid is None or best_ask is None:
            return orders, trader_data

        # --- Fair value: slow EMA of mid, tracks the drift ---
        mid     = (best_bid + best_ask) / 2
        ema_key = f"{product}_ema"
        ema     = trader_data.get(ema_key, mid)
        ema     = self.PEPPER_EMA_ALPHA * mid + (1 - self.PEPPER_EMA_ALPHA) * ema
        trader_data[ema_key] = ema
        fair_value = int(round(ema))

        buy_vol = sell_vol = 0

        # --- Step 1a: AGGRESSIVE ACCUMULATION below floor ---
        # When under floor, buy anything at or below fair to get loaded up fast.
        # When at/above floor, buy only genuine discounts (strictly below fair).
        for ask, qty in sorted(order_depth.sell_orders.items()):
            current = position + buy_vol
            if current < floor:
                # Still building: accept anything up to fair
                if ask > fair_value:
                    break
            else:
                # Already loaded: only take real discounts
                if ask >= fair_value:
                    break
            can_buy = limit - current
            if can_buy <= 0:
                break
            fill = min(abs(qty), can_buy)
            if fill > 0:
                orders.append(Order(product, ask, fill))
                buy_vol += fill

        # --- Step 1b: Only sell into bids that pay the drift premium ---
        # This is the key change: don't sell at fair+1, demand fair+PREMIUM.
        # Since price drifts up, a bid slightly above fair is still a LOSING sale.
        for bid, qty in sorted(order_depth.buy_orders.items(), reverse=True):
            if bid < fair_value + sell_premium:
                break
            # Never sell below the floor
            current = position + buy_vol - sell_vol
            if current <= floor:
                break
            # How much can we sell before hitting floor?
            room_to_floor = current - floor
            can_sell      = min(limit + (position - sell_vol), room_to_floor)
            if can_sell <= 0:
                break
            fill = min(qty, can_sell)
            if fill > 0:
                orders.append(Order(product, bid, -fill))
                sell_vol += fill

        # --- Step 2: Emergency short cover (should rarely trigger) ---
        pos_after_take = position + buy_vol - sell_vol
        if pos_after_take < 0:
            can_buy = limit - (position + buy_vol)
            fill    = min(abs(pos_after_take), can_buy)
            if fill > 0:
                # Pay up to cover — use best ask or fair, whichever higher
                cover_price = max(best_ask, fair_value)
                orders.append(Order(product, cover_price, fill))
                buy_vol += fill

        # --- Step 3: Passive market making ---
        # Buy side: quote a tight bid to accumulate on dips.
        # Sell side: quote WIDE — only fill if someone overpays meaningfully.
        current_pos = position + buy_vol - sell_vol

        # Passive bid: join or penny the best bid, but never above fair
        passive_bid = min(best_bid + 1, fair_value - 1)

        # Passive ask: stay well above fair to earn the drift premium
        passive_ask = max(best_ask, fair_value + passive_edge)

        # Safety: don't cross
        if passive_bid >= passive_ask:
            passive_bid = fair_value - 1
            passive_ask = fair_value + passive_edge

        # Passive BUY: always (we want more)
        can_buy_mm = limit - (position + buy_vol)
        if can_buy_mm > 0:
            orders.append(Order(product, passive_bid, can_buy_mm))

        # Passive SELL: only above floor, and only the excess above floor
        # Size is capped so we never passively fill below the floor
        if current_pos > floor:
            sellable = min(limit + (position - sell_vol), current_pos - floor)
            if sellable > 0:
                orders.append(Order(product, passive_ask, -sellable))

        return orders, trader_data
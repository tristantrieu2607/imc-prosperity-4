# -*- coding: utf-8 -*-
"""
attempt17 - fixes attempt16:
  - Removed Python 3.10+ union type hint syntax (int | None) -> use Optional
  - Fixed PEPPER take loop: break only when price is definitively too high,
    not on the first ask that doesn't meet a secondary condition
"""

from datamodel import OrderDepth, TradingState, Order
from typing import List, Tuple, Optional
import json


class Trader:

    LIMITS = {
        "OSMIUM": 80,
        "PEPPER": 80,
    }

    # ---------- OSMIUM constants ----------
    OSMIUM_FAIR   = 10_000
    OSMIUM_SKEW_T = 40

    # ---------- PEPPER constants ----------
    PEPPER_EMA_ALPHA  = 0.2
    PEPPER_FLOOR      = 30
    PEPPER_SKEW_RANGE = 3

    # ------------------------------------------------------------------ #
    #  Entry point                                                         #
    # ------------------------------------------------------------------ #
    def run(self, state: TradingState):
        result = {}
        trader_data = json.loads(state.traderData) if state.traderData else {}

        for product, order_depth in state.order_depths.items():
            position = state.position.get(product, 0)

            if product == "OSMIUM":
                orders, trader_data = self.trade_osmium(
                    product, order_depth, position, trader_data
                )
            elif product == "PEPPER":
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
    def _best(order_depth):
        # type: (OrderDepth) -> Tuple[Optional[int], Optional[int]]
        bid = max(order_depth.buy_orders)  if order_depth.buy_orders  else None
        ask = min(order_depth.sell_orders) if order_depth.sell_orders else None
        return bid, ask

    # ------------------------------------------------------------------ #
    #  OSMIUM                                                              #
    # ------------------------------------------------------------------ #
    def trade_osmium(self, product, order_depth, position, trader_data):
        orders = []
        limit      = self.LIMITS[product]
        fair_value = self.OSMIUM_FAIR

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders, trader_data

        buy_vol = 0
        sell_vol = 0

        # Step 1: Take mispricings
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

        # Step 2: Flatten if beyond soft threshold
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

        # Step 3: Passive penny quotes
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

        if my_bid >= my_ask:
            my_bid = fair_value - 1
            my_ask = fair_value + 1

        can_buy  = limit - (position + buy_vol)
        can_sell = limit + (position - sell_vol)

        if can_buy  > 0:
            orders.append(Order(product, my_bid,  can_buy))
        if can_sell > 0:
            orders.append(Order(product, my_ask, -can_sell))

        return orders, trader_data

    # ------------------------------------------------------------------ #
    #  PEPPER                                                              #
    # ------------------------------------------------------------------ #
    def trade_pepper(self, product, order_depth, position, trader_data):
        orders = []
        limit = self.LIMITS[product]
        floor = self.PEPPER_FLOOR

        best_bid, best_ask = self._best(order_depth)
        if best_bid is None or best_ask is None:
            return orders, trader_data

        # EMA fair value
        mid     = (best_bid + best_ask) / 2.0
        ema_key = product + "_ema"
        ema     = trader_data.get(ema_key, mid)
        ema     = self.PEPPER_EMA_ALPHA * mid + (1.0 - self.PEPPER_EMA_ALPHA) * ema
        trader_data[ema_key] = ema
        fair_value = int(round(ema))

        buy_vol  = 0
        sell_vol = 0

        # Step 1: Aggressive taking
        # BUG FIX: do NOT break on the first ask that doesn't meet needs_floor.
        # Iterate all asks; only skip ones that are too expensive.
        for ask, qty in sorted(order_depth.sell_orders.items()):
            below_fair  = ask < fair_value
            needs_floor = (position + buy_vol) < floor and ask <= fair_value
            if not (below_fair or needs_floor):
                continue                          # <-- was 'break', now 'continue'
            can_buy = limit - (position + buy_vol)
            if can_buy <= 0:
                break
            fill = min(abs(qty), can_buy)
            orders.append(Order(product, ask, fill))
            buy_vol += fill

        # Sell only meaningfully above fair (protect floor bias)
        for bid, qty in sorted(order_depth.buy_orders.items(), reverse=True):
            if bid <= fair_value + 1:
                break
            can_sell = limit + (position - sell_vol)
            if can_sell <= 0:
                break
            fill = min(qty, can_sell)
            orders.append(Order(product, bid, -fill))
            sell_vol += fill

        pos_after_take = position + buy_vol - sell_vol

        # Step 2: Clear only when genuinely offside
        CLEAR_WIDTH = 2
        if pos_after_take > limit - 5:
            can_sell = limit + (position - sell_vol)
            fill     = min(pos_after_take - (limit - 5), can_sell)
            if fill > 0:
                orders.append(Order(product, fair_value + CLEAR_WIDTH, -fill))
                sell_vol += fill

        elif pos_after_take < 0:
            can_buy = limit - (position + buy_vol)
            fill    = min(abs(pos_after_take), can_buy)
            if fill > 0:
                orders.append(Order(product, fair_value - CLEAR_WIDTH, fill))
                buy_vol += fill

        # Step 3: Passive quotes with inventory skew
        current_pos = position + buy_vol - sell_vol
        max_excur   = max(limit - floor, 1)
        skew        = int(((current_pos - floor) / max_excur) * self.PEPPER_SKEW_RANGE)

        passive_bid = min(best_bid + 1, fair_value - 1) - skew
        passive_ask = max(best_ask - 1, fair_value + 1) - skew

        if passive_bid >= passive_ask:
            passive_bid = fair_value - 1
            passive_ask = fair_value + 1

        can_buy_mm  = limit - (position + buy_vol)
        can_sell_mm = limit + (position - sell_vol)

        if can_buy_mm > 0:
            orders.append(Order(product, passive_bid, can_buy_mm))

        if current_pos > floor and can_sell_mm > 0:
            orders.append(Order(product, passive_ask, -can_sell_mm))

        return orders, trader_data
from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import json

class Trader:

    LIMITS = {
        "EMERALDS": 80,
        "TOMATOES": 80
    }

    def run(self, state: TradingState):
        result = {}

        if state.traderData and state.traderData != "":
            trader_data = json.loads(state.traderData)
        else:
            trader_data = {}

        for product in state.order_depths:
            order_depth = state.order_depths[product]
            position = state.position.get(product, 0)

            if product == "EMERALDS":
                orders, trader_data = self.trade_alpha(product, order_depth, position, trader_data)
            elif product == "TOMATOES":
                orders, trader_data = self.trade_alpha(product, order_depth, position, trader_data)

            result[product] = orders

        return result, 0, json.dumps(trader_data)

    def trade_alpha(self, product, order_depth: OrderDepth, position: int, trader_data: dict):

        orders: List[Order] = []
        limit = self.LIMITS[product]

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders, trader_data

        # ===== BASIC BOOK INFO =====
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())

        bid_vol = sum(order_depth.buy_orders.values())
        ask_vol = -sum(order_depth.sell_orders.values())

        # ===== MICROPRICE =====
        microprice = (best_bid * ask_vol + best_ask * bid_vol) / (bid_vol + ask_vol)

        # ===== IMBALANCE =====
        imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol)

        # ===== MOMENTUM =====
        key_last = f"{product}_last_mid"
        mid = (best_bid + best_ask) / 2

        if key_last in trader_data:
            momentum = mid - trader_data[key_last]
        else:
            momentum = 0

        trader_data[key_last] = mid

        # ===== FAIR VALUE =====
        fair_value = microprice + imbalance * 2 + momentum * 0.5
        fair_value = round(fair_value)

        # ===== ADAPTIVE SPREAD =====
        key_prev_mid = f"{product}_prev_mid"
        prev_mid = trader_data.get(key_prev_mid, mid)
        volatility = abs(mid - prev_mid)

        spread = max(2, min(6, int(volatility * 2)))
        trader_data[key_prev_mid] = mid

        # ===== INVENTORY SKEW =====
        skew = int(position * 0.1)

        buy_price = fair_value - spread - skew
        sell_price = fair_value + spread - skew

        # ===== POSITION CONTROL =====
        buy_volume = 0
        sell_volume = 0

        # ===== TAKE (WITH SIGNAL CONFIRMATION) =====
        for ask_price, ask_volume in sorted(order_depth.sell_orders.items()):
            if ask_price < fair_value:
                if imbalance > -0.2:  # avoid catching falling knife
                    can_buy = limit - (position + buy_volume)
                    qty = min(-ask_volume, can_buy)
                    if qty > 0:
                        orders.append(Order(product, ask_price, qty))
                        buy_volume += qty

        for bid_price, bid_volume in sorted(order_depth.buy_orders.items(), reverse=True):
            if bid_price > fair_value:
                if imbalance < 0.2:
                    can_sell = limit + (position - sell_volume)
                    qty = min(bid_volume, can_sell)
                    if qty > 0:
                        orders.append(Order(product, bid_price, -qty))
                        sell_volume += qty

        # ===== SMART CLEARING =====
        position_after = position + buy_volume - sell_volume

        if abs(position_after) > limit * 0.6:
            if position_after > 0:
                qty = min(position_after, limit)
                orders.append(Order(product, fair_value, -qty))
            else:
                qty = min(-position_after, limit)
                orders.append(Order(product, fair_value, qty))

        # ===== PASSIVE MAKING =====
        inv_ratio = abs(position) / limit
        size_mult = max(0.3, 1 - inv_ratio)

        # Buy order
        can_buy = limit - (position + buy_volume)
        buy_qty = int(can_buy * size_mult)
        if buy_qty > 0:
            orders.append(Order(product, buy_price, buy_qty))

        # Sell order
        can_sell = limit + (position - sell_volume)
        sell_qty = int(can_sell * size_mult)
        if sell_qty > 0:
            orders.append(Order(product, sell_price, -sell_qty))

        return orders, trader_data
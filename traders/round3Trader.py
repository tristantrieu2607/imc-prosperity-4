from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List, Dict
import math
import numpy as np
import jsonpickle


def trade_hydrogel(state: TradingState, trader_data: dict) -> tuple[list[Order], dict]:
    orders = []
    product = "HYDROGEL_PACK"

    ob = state.order_depths.get(product)
    if not ob:
        return orders, trader_data

    bid_wall = min(ob.buy_orders.keys()) if ob.buy_orders else None
    ask_wall = max(ob.sell_orders.keys()) if ob.sell_orders else None

    if not (bid_wall and ask_wall):
        return orders, trader_data

    wall_mid = (bid_wall + ask_wall) / 2

    # 1. Update slow EMA
    window = 1500
    alpha = 2.0 / (window + 1)
    prev_ema = trader_data.get("hp_ema", wall_mid)
    ema = alpha * wall_mid + (1 - alpha) * prev_ema
    trader_data["hp_ema"] = ema

    # 2. Inventory Skew
    pos = state.position.get(product, 0)
    pos_limit = 200
    skew = -(pos / pos_limit) * 2.5
    fair = ema + skew

    my_bid = int(round(fair - 1.5))
    my_ask = int(round(fair + 1.5))

    # 3. Market Making Orders
    buy_capacity = pos_limit - pos
    sell_capacity = pos_limit + pos

    if buy_capacity > 0:
        orders.append(Order(product, my_bid, buy_capacity))
    if sell_capacity > 0:
        orders.append(Order(product, my_ask, -sell_capacity))

    return orders, trader_data


def trade_vev_mm_refined(state: TradingState, trader_data: dict) -> tuple[dict[str, list[Order]], dict]:
    orders = {}
    limit = 300
    active_strikes = ["VEV_5300", "VEV_5400", "VEV_5500"]
    underlying = "VELVETFRUIT_EXTRACT"

    spot_ob = state.order_depths.get(underlying)
    if not spot_ob or not spot_ob.buy_orders or not spot_ob.sell_orders:
        return {}, trader_data
    spot = (max(spot_ob.buy_orders.keys()) + min(spot_ob.sell_orders.keys())) / 2

    for product in active_strikes:
        orders[product] = []
        ob = state.order_depths.get(product)
        if not ob or not ob.buy_orders or not ob.sell_orders:
            continue

        # 1. Fair Value (EMA of Mid)
        mid = (max(ob.buy_orders.keys()) + min(ob.sell_orders.keys())) / 2
        ema_key = f"ema_{product}"
        fair = trader_data.get(ema_key, mid)
        fair = 0.2 * mid + 0.8 * fair
        trader_data[ema_key] = fair

        # 2. Structural Bias
        if product == "VEV_5400":
            fair -= 0.75
        else:
            fair += 0.5

        # 3. Inventory Skew
        pos = state.position.get(product, 0)
        inventory_skew = -(pos / limit) * 2.5
        adjusted_fair = fair + inventory_skew

        # 4. Quoting
        bid_price = int(np.floor(adjusted_fair - 1))
        ask_price = int(np.ceil(adjusted_fair + 1))

        orders[product].append(Order(product, bid_price, limit - pos))
        orders[product].append(Order(product, ask_price, -(limit + pos)))

    return orders, trader_data


class Trader:

    def run(self, state: TradingState):
        # Load persistent state
        if state.traderData:
            try:
                trader_data = jsonpickle.decode(state.traderData)
            except Exception:
                trader_data = {}
        else:
            trader_data = {}

        result = {}

        # Hydrogel
        hg_orders, trader_data = trade_hydrogel(state, trader_data)
        if hg_orders:
            result["HYDROGEL_PACK"] = hg_orders

        # VEV options
        vev_orders, trader_data = trade_vev_mm_refined(state, trader_data)
        for product, prod_orders in vev_orders.items():
            if prod_orders:
                result[product] = prod_orders

        traderData = jsonpickle.encode(trader_data)
        conversions = 0
        return result, conversions, traderData
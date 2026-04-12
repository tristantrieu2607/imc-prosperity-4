"""
Parameter optimizer for IMC Prosperity 4
Runs backtester across different parameter combinations and reports results.

Usage:
    python optimize.py
    
Modify the parameter ranges at the bottom of this file.
"""

import subprocess
import itertools
import os
import re

TRADER_TEMPLATE = '''from prosperity4bt.datamodel import OrderDepth, UserId, TradingState, Order
from typing import List, Dict
import json

class Trader:

    LIMITS = {{
        "EMERALDS": 80,
        "TOMATOES": 80
    }}

    def run(self, state: TradingState):
        result = {{}}

        if state.traderData and state.traderData != "":
            trader_data = json.loads(state.traderData)
        else:
            trader_data = {{}}

        for product in state.order_depths:
            order_depth = state.order_depths[product]
            orders: List[Order] = []
            position = state.position.get(product, 0)

            if product == "EMERALDS":
                orders = self.trade_emeralds(order_depth, position)
            elif product == "TOMATOES":
                orders, trader_data = self.trade_tomatoes(order_depth, position, trader_data)

            result[product] = orders
        trader_data_string = json.dumps(trader_data)
        conversions = 0
        return result, conversions, trader_data_string

    def trade_emeralds(self, order_depth: OrderDepth, position: int) -> List[Order]:
        orders: List[Order] = []
        fair_value = 10000
        limit = self.LIMITS["EMERALDS"]

        buy_volume = 0
        sell_volume = 0

        if len(order_depth.sell_orders) > 0:
            for ask_price, ask_volume in sorted(order_depth.sell_orders.items()):
                if ask_price < fair_value:
                    can_buy = limit - (position + buy_volume)
                    qty = min(-ask_volume, can_buy)
                    if qty > 0:
                        orders.append(Order("EMERALDS", ask_price, qty))
                        buy_volume += qty

        if len(order_depth.buy_orders) > 0:
            for bid_price, bid_volume in sorted(order_depth.buy_orders.items(), reverse=True):
                if bid_price > fair_value:
                    can_sell = limit + (position - sell_volume)
                    qty = min(bid_volume, can_sell)
                    if qty > 0:
                        orders.append(Order("EMERALDS", bid_price, -qty))
                        sell_volume += qty

        position_after_take = position + buy_volume - sell_volume

        if position_after_take > 0:
            can_sell = limit + (position - sell_volume)
            qty = min(position_after_take, can_sell)
            if qty > 0:
                orders.append(Order("EMERALDS", fair_value, -qty))
                sell_volume += qty

        elif position_after_take < 0:
            can_buy = limit - (position + buy_volume)
            qty = min(-position_after_take, can_buy)
            if qty > 0:
                orders.append(Order("EMERALDS", fair_value, qty))
                buy_volume += qty

        spread = {emerald_spread}

        buy_price = fair_value - spread
        can_buy = limit - (position + buy_volume)
        if can_buy > 0:
            orders.append(Order("EMERALDS", buy_price, can_buy))

        sell_price = fair_value + spread
        can_sell = limit + (position - sell_volume)
        if can_sell > 0:
            orders.append(Order("EMERALDS", sell_price, -can_sell))

        return orders

    def trade_tomatoes(self, order_depth: OrderDepth, position: int, trader_data: dict):
        orders: List[Order] = []
        limit = self.LIMITS["TOMATOES"]

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        mid_price = (best_bid + best_ask) / 2

        ema_span = {ema_span}
        alpha = 2 / (ema_span + 1)

        if "tomatoes_ema" in trader_data:
            ema = trader_data["tomatoes_ema"]
            ema = alpha * mid_price + (1 - alpha) * ema
        else:
            ema = mid_price

        trader_data["tomatoes_ema"] = ema
        fair_value = round(ema)

        buy_volume = 0
        sell_volume = 0

        if len(order_depth.sell_orders) > 0:
            for ask_price, ask_volume in sorted(order_depth.sell_orders.items()):
                if ask_price < fair_value:
                    can_buy = limit - (position + buy_volume)
                    qty = min(-ask_volume, can_buy)
                    if qty > 0:
                        orders.append(Order("TOMATOES", ask_price, qty))
                        buy_volume += qty

        if len(order_depth.buy_orders) > 0:
            for bid_price, bid_volume in sorted(order_depth.buy_orders.items(), reverse=True):
                if bid_price > fair_value:
                    can_sell = limit + (position - sell_volume)
                    qty = min(bid_volume, can_sell)
                    if qty > 0:
                        orders.append(Order("TOMATOES", bid_price, -qty))
                        sell_volume += qty

        position_after_take = position + buy_volume - sell_volume

        if position_after_take > 0:
            can_sell = limit + (position - sell_volume)
            qty = min(position_after_take, can_sell)
            if qty > 0:
                orders.append(Order("TOMATOES", fair_value, -qty))
                sell_volume += qty

        elif position_after_take < 0:
            can_buy = limit - (position + buy_volume)
            qty = min(-position_after_take, can_buy)
            if qty > 0:
                orders.append(Order("TOMATOES", fair_value, qty))
                buy_volume += qty

        spread = {tomato_spread}

        buy_price = fair_value - spread
        can_buy = limit - (position + buy_volume)
        if can_buy > 0:
            orders.append(Order("TOMATOES", buy_price, can_buy))

        sell_price = fair_value + spread
        can_sell = limit + (position - sell_volume)
        if can_sell > 0:
            orders.append(Order("TOMATOES", sell_price, -can_sell))

        return orders, trader_data
'''


def run_backtest(emerald_spread, ema_span, tomato_spread):
    """Generate a trader file with given params, run backtester, parse profit."""
    
    code = TRADER_TEMPLATE.format(
        emerald_spread=emerald_spread,
        ema_span=ema_span,
        tomato_spread=tomato_spread
    )
    
    temp_file = "_temp_trader.py"
    with open(temp_file, "w") as f:
        f.write(code)
    
    try:
        result = subprocess.run(
            ["prosperity4btx", temp_file, "0", "--no-out", "--no-progress"],
            capture_output=True,
            text=True,
            timeout=120
        )
        output = result.stdout + result.stderr
        
        # Parse total profit from output
        match = re.search(r"Total profit:\s*([\-\d,\.]+)", output)
        if match:
            profit = float(match.group(1).replace(",", ""))
            return profit
        else:
            return None
    except Exception as e:
        print(f"  Error: {e}")
        return None
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)


if __name__ == "__main__":
    # === MODIFY THESE RANGES ===
    emerald_spreads = [1, 2, 3, 4, 5, 6, 7, 8]
    ema_spans = [1,2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30]
    tomato_spreads = [2]
    
    print("=" * 60)
    print("IMC Prosperity 4 — Parameter Optimization")
    print("=" * 60)
    
    results = []
    total_combos = len(emerald_spreads) * len(ema_spans) * len(tomato_spreads)
    
    for i, (es, ema, ts) in enumerate(itertools.product(emerald_spreads, ema_spans, tomato_spreads)):
        print(f"[{i+1}/{total_combos}] emerald_spread={es}, ema_span={ema}, tomato_spread={ts}", end=" ... ")
        
        profit = run_backtest(es, ema, ts)
        
        if profit is not None:
            print(f"Profit: {profit:,.0f}")
            results.append((profit, es, ema, ts))
        else:
            print("FAILED")
    
    # Sort by profit descending
    results.sort(reverse=True)
    
    print("\n" + "=" * 60)
    print("TOP 10 PARAMETER COMBINATIONS")
    print("=" * 60)
    print(f"{'Rank':<6}{'Profit':<12}{'E_Spread':<10}{'EMA_Span':<10}{'T_Spread':<10}")
    print("-" * 48)
    
    for rank, (profit, es, ema, ts) in enumerate(results[:10], 1):
        print(f"{rank:<6}{profit:<12,.0f}{es:<10}{ema:<10}{ts:<10}")
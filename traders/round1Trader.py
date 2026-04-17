from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List, Dict
import json

class Trader:

    LIMITS = {
        "OSMIUM": 80,
        "PEPPER": 80
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

            if product == "OSMIUM":
                orders, trader_data = self.trade_osmium(order_depth, position, trader_data)
            elif product == "PEPPER":
                orders, trader_data = self.trade_pepper(order_depth, position, trader_data)
            
            result[product] = orders
            
        trader_data_string = json.dumps(trader_data)
        return result, 0, trader_data_string 
    
    def trade_osmium(self, order_depth: OrderDepth, position: int, trader_data: dict):
        orders: List[Order] = []
        limit = self.LIMITS.get("OSMIUM", 80)

        # 1. Hardcoded Fair Value (Based on EDA: Perfectly Stationary)
        fair_value = 10000

        buy_volume = 0
        sell_volume = 0

        # === STEP 1: TAKE FAVORABLE ===
        if len(order_depth.sell_orders) > 0:
            for ask_price, ask_volume in sorted(order_depth.sell_orders.items()):
                if ask_price < fair_value:
                    can_buy = limit - (position + buy_volume)
                    qty = min(abs(ask_volume), can_buy)
                    if qty > 0:
                        orders.append(Order("OSMIUM", int(ask_price), int(qty)))
                        buy_volume += qty

        if len(order_depth.buy_orders) > 0:
            for bid_price, bid_volume in sorted(order_depth.buy_orders.items(), reverse=True):
                if bid_price > fair_value:
                    can_sell = limit + (position - sell_volume)
                    qty = min(bid_volume, can_sell)
                    if qty > 0:
                        orders.append(Order("OSMIUM", int(bid_price), -int(qty)))
                        sell_volume += qty

        position_after_take = position + buy_volume - sell_volume

        # === STEP 2: SCRATCH CHOKE-RELEASE ===
        scratch_threshold = 40
        if position_after_take > scratch_threshold:
            excess = position_after_take - scratch_threshold
            can_sell = limit + (position - sell_volume)
            qty = min(excess, can_sell)
            if qty > 0:
                orders.append(Order("OSMIUM", int(fair_value), -int(qty)))
                sell_volume += qty
        elif position_after_take < -scratch_threshold:
            excess = abs(position_after_take) - scratch_threshold
            can_buy = limit - (position + buy_volume)
            qty = min(excess, can_buy)
            if qty > 0:
                orders.append(Order("OSMIUM", int(fair_value), int(qty)))
                buy_volume += qty

        # === STEP 3: THE DEEP OSMIUM STATIC LADDER ===
        buy_levels = [fair_value - 6, fair_value - 10, fair_value - 15]   
        sell_levels = [fair_value + 6, fair_value + 10, fair_value + 15]  
        vol_weights = [0.50, 0.30, 0.20] 

        # --- Place Buy Ladder ---
        can_buy = limit - (position + buy_volume)
        base_can_buy = can_buy 
        if can_buy > 0:
            for i in range(len(buy_levels)):
                vol = can_buy if i == len(buy_levels) - 1 else int(base_can_buy * vol_weights[i])
                if vol > 0:
                    orders.append(Order("OSMIUM", int(buy_levels[i]), int(vol)))
                    can_buy -= vol

        # --- Place Sell Ladder ---
        can_sell = limit + (position - sell_volume)
        base_can_sell = can_sell
        if can_sell > 0:
            for i in range(len(sell_levels)):
                vol = can_sell if i == len(sell_levels) - 1 else int(base_can_sell * vol_weights[i])
                if vol > 0:
                    orders.append(Order("OSMIUM", int(sell_levels[i]), -int(vol)))
                    can_sell -= vol

        return orders, trader_data

    def trade_pepper(self, order_depth: OrderDepth, position: int, trader_data: dict):
        orders: List[Order] = []
        limit = self.LIMITS.get("PEPPER", 80)

        # --- Fair Value Calculation (EMA for Drifting) ---
        best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else 10000
        best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else 10000
        mid_price = (best_bid + best_ask) / 2
        
        alpha = 0.2 # Standard trend alpha
        ema = trader_data.get("pepper_ema", mid_price)
        ema = alpha * mid_price + (1 - alpha) * ema
        trader_data["pepper_ema"] = ema
        fair_value = int(round(ema))

        buy_volume = 0
        sell_volume = 0

        # === STEP 1: TAKE (Aggressive) ===
        if len(order_depth.sell_orders) > 0:
            for ask_price, ask_qty in sorted(order_depth.sell_orders.items()):
                if ask_price < fair_value:
                    qty = min(abs(ask_qty), limit - (position + buy_volume))
                    if qty > 0:
                        orders.append(Order("PEPPER", int(ask_price), int(qty)))
                        buy_volume += qty

        if len(order_depth.buy_orders) > 0:
            for bid_price, bid_qty in sorted(order_depth.buy_orders.items(), reverse=True):
                if bid_price > fair_value:
                    qty = min(bid_qty, limit + (position - sell_volume))
                    if qty > 0:
                        orders.append(Order("PEPPER", int(bid_price), -int(qty)))
                        sell_volume += qty

        # === STEP 2: CLEAR ===
        pos_after_take = position + buy_volume - sell_volume
        if pos_after_take > 0: 
            qty = min(abs(pos_after_take), limit + (position - sell_volume))
            orders.append(Order("PEPPER", fair_value, -int(qty)))
            sell_volume += qty
        elif pos_after_take < 0:
            qty = min(abs(pos_after_take), limit - (position + buy_volume))
            orders.append(Order("PEPPER", fair_value, int(qty)))
            buy_volume += qty

        # === STEP 3: MAKE (Passive with Inventory Skew) ===
        # Recalculate position for accurate skew
        current_pos = position + buy_volume - sell_volume
        inventory_skew = int((current_pos / limit) * 3) 
        
        buy_price = int(min(best_bid + 1, fair_value - 1) - inventory_skew)
        sell_price = int(max(best_ask - 1, fair_value + 1) - inventory_skew)

        can_buy_rem = limit - (position + buy_volume)
        if can_buy_rem > 0:
            orders.append(Order("PEPPER", buy_price, int(can_buy_rem)))

        can_sell_rem = limit + (position - sell_volume)
        if can_sell_rem > 0:
            orders.append(Order("PEPPER", sell_price, -int(can_sell_rem)))

        return orders, trader_data
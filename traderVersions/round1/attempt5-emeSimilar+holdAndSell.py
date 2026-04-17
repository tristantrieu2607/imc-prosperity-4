from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List, Dict
import traceback
import json

class Trader:

    LIMITS = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80
    }

    def run(self, state: TradingState): 
        result = {}
        
        # 1. Safely load trader data
        trader_data_string = state.traderData if state.traderData else ""
        try:
            if trader_data_string:
                trader_data = json.loads(trader_data_string)
            else:
                trader_data = {}
        except json.JSONDecodeError:
            trader_data = {}

        # 2. Main Logic Loop wrapped in a try-except to prevent silent crashes
        try:
            for product in state.order_depths: 
                order_depth = state.order_depths[product]
                position = state.position.get(product, 0)

                # We pass the 'product' string explicitly for safer Order creation
                if product == "ASH_COATED_OSMIUM":
                    orders, trader_data = self.trade_ASH_COATED_OSMIUM(product, order_depth, position, trader_data)
                    result[product] = orders
                elif product == "INTARIAN_PEPPER_ROOT":
                    orders, trader_data = self.trade_INTARIAN_PEPPER_ROOT(product, order_depth, position, trader_data)
                    result[product] = orders

        except Exception as e:
            # If an error happens, this prints it to your logs but keeps the bot alive!
            print(f"Error encountered: {traceback.format_exc()}")
            
        trader_data_string = json.dumps(trader_data)
        return result, 0, trader_data_string 
    
    def trade_ASH_COATED_OSMIUM(self, product: str, order_depth: OrderDepth, position: int, trader_data: dict):
        orders: List[Order] = []
        limit = self.LIMITS.get(product, 80)

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
                        orders.append(Order(product, int(ask_price), int(qty)))
                        buy_volume += qty

        if len(order_depth.buy_orders) > 0:
            for bid_price, bid_volume in sorted(order_depth.buy_orders.items(), reverse=True):
                if bid_price > fair_value:
                    can_sell = limit + (position - sell_volume)
                    qty = min(bid_volume, can_sell)
                    if qty > 0:
                        orders.append(Order(product, int(bid_price), -int(qty)))
                        sell_volume += qty

        # === STEP 2: SCRATCH CHOKE-RELEASE ===
        position_after_take = position + buy_volume - sell_volume
        scratch_threshold = 40
        
        if position_after_take > scratch_threshold:
            excess = position_after_take - scratch_threshold
            can_sell = limit + (position - sell_volume)
            qty = min(excess, can_sell)
            if qty > 0:
                orders.append(Order(product, int(fair_value), -int(qty)))
                sell_volume += qty
                
        elif position_after_take < -scratch_threshold:
            excess = abs(position_after_take) - scratch_threshold
            can_buy = limit - (position + buy_volume)
            qty = min(excess, can_buy)
            if qty > 0:
                orders.append(Order(product, int(fair_value), int(qty)))
                buy_volume += qty

        # === STEP 3: THE DEEP ASH_COATED_OSMIUM STATIC LADDER ===
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
                    orders.append(Order(product, int(buy_levels[i]), int(vol)))
                    can_buy -= vol

        # --- Place Sell Ladder ---
        can_sell = limit + (position - sell_volume)
        base_can_sell = can_sell
        if can_sell > 0:
            for i in range(len(sell_levels)):
                vol = can_sell if i == len(sell_levels) - 1 else int(base_can_sell * vol_weights[i])
                if vol > 0:
                    orders.append(Order(product, int(sell_levels[i]), -int(vol)))
                    can_sell -= vol

        return orders, trader_data

    def trade_INTARIAN_PEPPER_ROOT(self, product: str, order_depth: OrderDepth, position: int, trader_data: dict):
        orders: List[Order] = []
        limit = self.LIMITS.get(product, 80)

        buy_orders = order_depth.buy_orders
        sell_orders = order_depth.sell_orders

        # --- SAFE Fair Value Calculation (Handles Empty Order Books) ---
        if len(buy_orders) > 0 and len(sell_orders) > 0:
            best_bid = max(buy_orders.keys())
            best_ask = min(sell_orders.keys())
            mid_price = (best_bid + best_ask) / 2
        elif "INTARIAN_PEPPER_ROOT_ema" in trader_data:
            # Fallback to EMA if order book is empty to prevent crashing
            mid_price = trader_data["INTARIAN_PEPPER_ROOT_ema"]
            best_bid = int(mid_price) - 1
            best_ask = int(mid_price) + 1
        else:
            mid_price = 10000
            best_bid = 9999
            best_ask = 10001
        
        alpha = 0.2 
        ema = trader_data.get("INTARIAN_PEPPER_ROOT_ema", mid_price)
        ema = alpha * mid_price + (1 - alpha) * ema
        trader_data["INTARIAN_PEPPER_ROOT_ema"] = ema
        fair_value = int(round(ema))

        buy_volume = 0
        sell_volume = 0

        # === STEP 1: TAKE (Aggressive) ===
        if len(sell_orders) > 0:
            for ask_price, ask_qty in sorted(sell_orders.items()):
                if ask_price < fair_value:
                    can_buy = limit - (position + buy_volume)
                    qty = min(abs(ask_qty), can_buy)
                    if qty > 0:
                        orders.append(Order(product, int(ask_price), int(qty)))
                        buy_volume += qty

        if len(buy_orders) > 0:
            for bid_price, bid_qty in sorted(buy_orders.items(), reverse=True):
                if bid_price > fair_value:
                    can_sell = limit + (position - sell_volume)
                    qty = min(bid_qty, can_sell)
                    if qty > 0:
                        orders.append(Order(product, int(bid_price), -int(qty)))
                        sell_volume += qty

        # === STEP 2: CLEAR (Manage Drift) ===
        pos_after_take = position + buy_volume - sell_volume
        
        if pos_after_take > 0: 
            can_sell = limit + (position - sell_volume)
            qty = min(abs(pos_after_take), can_sell)
            if qty > 0:
                orders.append(Order(product, fair_value, -int(qty)))
                sell_volume += qty
                
        elif pos_after_take < 0:
            can_buy = limit - (position + buy_volume)
            qty = min(abs(pos_after_take), can_buy)
            if qty > 0:
                orders.append(Order(product, fair_value, int(qty)))
                buy_volume += qty

        # === STEP 3: MAKE (Passive with Inventory Skew) ===
        current_pos = position + buy_volume - sell_volume
        inventory_skew = int((current_pos / limit) * 3) 
        
        buy_price = int(min(best_bid + 1, fair_value - 1) - inventory_skew)
        sell_price = int(max(best_ask - 1, fair_value + 1) - inventory_skew)

        # Edge-case safety: ensure our passive prices don't cross and self-trade
        if buy_price >= sell_price:
            buy_price = sell_price - 1

        can_buy_rem = limit - (position + buy_volume)
        if can_buy_rem > 0:
            orders.append(Order(product, buy_price, int(can_buy_rem)))

        can_sell_rem = limit + (position - sell_volume)
        if can_sell_rem > 0:
            orders.append(Order(product, sell_price, -int(can_sell_rem)))

        return orders, trader_data
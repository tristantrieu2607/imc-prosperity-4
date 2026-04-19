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
                # Adjusted to pass product name to match the method signature
                orders, trader_data = self.trade_osmium(product, order_depth, position, trader_data)
            elif product == "PEPPER":
                # Updated to pass product name and use the new MT/MM logic
                orders, trader_data = self.trade_pepper(product, order_depth, position, trader_data)
            
            result[product] = orders
            
        trader_data_string = json.dumps(trader_data)
        return result, 0, trader_data_string 
    
    def trade_osmium(self, product: str, order_depth: OrderDepth, position: int, trader_data: dict):
        orders: List[Order] = []
        limit = self.LIMITS.get(product, 80)
        fair_value = 10000

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders, trader_data

        buy_volume = 0
        sell_volume = 0

        # === STEP 1: IMMEDIATELY TAKE FAVORABLE ===
        for ask_price, ask_volume in sorted(order_depth.sell_orders.items()):
            if ask_price < fair_value:
                can_buy = limit - (position + buy_volume)
                qty = min(abs(ask_volume), can_buy)
                if qty > 0:
                    orders.append(Order(product, int(ask_price), int(qty)))
                    buy_volume += qty

        for bid_price, bid_volume in sorted(order_depth.buy_orders.items(), reverse=True):
            if bid_price > fair_value:
                can_sell = limit + (position - sell_volume)
                qty = min(bid_volume, can_sell)
                if qty > 0:
                    orders.append(Order(product, int(bid_price), -int(qty)))
                    sell_volume += qty

        position_after_take = position + buy_volume - sell_volume

        # === STEP 2: FLATTEN INVENTORY SKEW ===
        skew_threshold = 40
        if position_after_take > skew_threshold:
            excess = position_after_take - skew_threshold
            can_sell = limit + (position - sell_volume)
            qty = min(excess, can_sell)
            if qty > 0:
                orders.append(Order(product, int(fair_value), -int(qty)))
                sell_volume += qty
                
        elif position_after_take < -skew_threshold:
            excess = abs(position_after_take) - skew_threshold
            can_buy = limit - (position + buy_volume)
            qty = min(excess, can_buy)
            if qty > 0:
                orders.append(Order(product, int(fair_value), int(qty)))
                buy_volume += qty

        # === STEP 3: PASSIVE QUOTES (PENNYING) ===
        my_buy_price = fair_value - 1
        my_sell_price = fair_value + 1

        for bp, bv in sorted(order_depth.buy_orders.items(), reverse=True):
            if bv > 1 and bp < fair_value - 1: 
                my_buy_price = bp + 1
                break
                
        for sp, sv in sorted(order_depth.sell_orders.items()):
            if abs(sv) > 1 and sp > fair_value + 1:
                my_sell_price = sp - 1
                break

        if my_buy_price >= my_sell_price:
            my_buy_price = fair_value - 1
            my_sell_price = fair_value + 1

        can_buy = limit - (position + buy_volume)
        if can_buy > 0:
            orders.append(Order(product, int(my_buy_price), int(can_buy)))

        can_sell = limit + (position - sell_volume)
        if can_sell > 0:
            orders.append(Order(product, int(my_sell_price), -int(can_sell)))

        return orders, trader_data

    def trade_pepper(self, product: str, order_depth: OrderDepth, position: int, trader_data: dict):
        orders: List[Order] = []
        limit = self.LIMITS.get(product, 80)
        target_floor = 30 # Maintain at least 30 units because the asset is trending up

        # --- 1. Fair Value Calculation (EMA) ---
        best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
        best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None
        
        if best_bid is None or best_ask is None:
            return orders, trader_data

        mid_price = (best_bid + best_ask) / 2
        alpha = 0.2 
        ema_key = f"{product}_ema"
        ema = trader_data.get(ema_key, mid_price)
        ema = alpha * mid_price + (1 - alpha) * ema
        trader_data[ema_key] = ema
        fair_value = ema

        buy_volume = 0
        sell_volume = 0

        # --- 2. Market Taking (MT) - Aggressive Execution ---
        # Logic: Buy if price < fair_value, 
        # OR buy if we are below our floor (even if price is at fair_value)
        for ask_price, ask_qty in sorted(order_depth.sell_orders.items()):
            if ask_price < fair_value or (position + buy_volume < target_floor and ask_price <= fair_value):
                max_buy = limit - (position + buy_volume)
                qty = min(abs(ask_qty), max_buy)
                if qty > 0:
                    orders.append(Order(product, int(ask_price), int(qty)))
                    buy_volume += qty

        # Sell aggressively only if price is significantly above fair_value
        # We are more conservative with selling to protect our floor
        for bid_price, bid_qty in sorted(order_depth.buy_orders.items(), reverse=True):
            if bid_price > fair_value + 1:
                max_sell = limit + (position - sell_volume)
                qty = min(bid_qty, max_sell)
                if qty > 0:
                    orders.append(Order(product, int(bid_price), -int(qty)))
                    sell_volume += qty

        # --- 3. Market Making (MM) - Passive Quoting with Floor Bias ---
        current_pos = position + buy_volume - sell_volume
        
        # Adjust skew relative to the floor (neutral point is now 30, not 0)
        # This makes the bot bid higher when below 30 and ask higher when near 80
        skew_factor = (current_pos - target_floor) / (limit - target_floor) 
        
        bid_price = int(round(fair_value - 1 - (skew_factor * 2)))
        ask_price = int(round(fair_value + 1 - (skew_factor * 2)))

        # Safety: Don't accidentally cross the spread with passive orders
        bid_price = min(bid_price, best_ask - 1)
        ask_price = max(ask_price, best_bid + 1)

        # Passive Buy
        can_buy_mm = limit - (position + buy_volume)
        if can_buy_mm > 0:
            orders.append(Order(product, bid_price, int(can_buy_mm)))

        # Passive Sell (Only quote sells if we have met our floor requirement)
        if current_pos > target_floor:
            can_sell_mm = limit + (position - sell_volume)
            if can_sell_mm > 0:
                orders.append(Order(product, ask_price, -int(can_sell_mm)))

        return orders, trader_data
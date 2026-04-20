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
            trader_data = json.loads(trader_data_string) if trader_data_string else {}
        except json.JSONDecodeError:
            trader_data = {}

        # 2. Main Logic Loop
        try:
            for product in state.order_depths: 
                order_depth = state.order_depths[product]
                position = state.position.get(product, 0)

                if product == "ASH_COATED_OSMIUM":
                    # FIXED: Pass 4 arguments to match call
                    orders, trader_data = self.trade_osmium(product, order_depth, position, trader_data)
                    result[product] = orders
                elif product == "INTARIAN_PEPPER_ROOT":
                    orders, trader_data = self.trade_pepper(product, order_depth, position, trader_data)
                    result[product] = orders

        except Exception as e:
            print(f"Error encountered: {traceback.format_exc()}")
            
        return result, 0, json.dumps(trader_data)
    
    # FIXED: Added 'product' to the signature
    def trade_osmium(self, product: str, order_depth: OrderDepth, position: int, trader_data: dict):
        orders: List[Order] = []
        limit = self.LIMITS.get(product, 80)
        fair_value = 10000

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders, trader_data

        buy_volume = 0
        sell_volume = 0
        skew_threshold = 80
        margin = 1

        # === STEP 1: IMMEDIATELY TAKE FAVORABLE ===
        for ask_price, ask_volume in sorted(order_depth.sell_orders.items()):
            if ask_price < fair_value:
                can_buy = limit - (position + buy_volume)
                qty = min(abs(ask_volume), can_buy)
                if qty > 0:
                    orders.append(Order("ASH_COATED_OSMIUM", int(ask_price), int(qty)))
                    buy_volume += qty

        for bid_price, bid_volume in sorted(order_depth.buy_orders.items(), reverse=True):
            if bid_price > fair_value:
                can_sell = limit + (position - sell_volume)
                qty = min(bid_volume, can_sell)
                if qty > 0:
                    orders.append(Order("ASH_COATED_OSMIUM", int(bid_price), -int(qty)))
                    sell_volume += qty

        position_after_take = position + buy_volume - sell_volume

        # === STEP 2: FLATTEN INVENTORY SKEW ===
        if position_after_take > skew_threshold:
            excess = position_after_take - skew_threshold
            can_sell = limit + (position - sell_volume)
            qty = min(excess, can_sell)
            if qty > 0:
                orders.append(Order("ASH_COATED_OSMIUM", int(fair_value), -int(qty)))
                sell_volume += qty
                
        elif position_after_take < -skew_threshold:
            excess = abs(position_after_take) - skew_threshold
            can_buy = limit - (position + buy_volume)
            qty = min(excess, can_buy)
            if qty > 0:
                orders.append(Order("ASH_COATED_OSMIUM", int(fair_value), int(qty)))
                buy_volume += qty

        # === STEP 3: PASSIVE QUOTES (FRANKFURT PENNYING) ===

        my_buy_price = fair_value - margin
        my_sell_price = fair_value + margin

        for bp, bv in sorted(order_depth.buy_orders.items(), reverse=True):
            # Only apply margin to the price checks, leave bv > 1 alone
            if bv > 1 and bp < fair_value - margin: 
                my_buy_price = bp + margin
                break
                
        for sp, sv in sorted(order_depth.sell_orders.items()):
            # Only apply margin to the price checks, leave abs(sv) > 1 alone
            if abs(sv) > 1 and sp > fair_value + margin:
                my_sell_price = sp - margin
                break

        # Safety Fallback
        if my_buy_price >= my_sell_price:
            my_buy_price = fair_value - margin
            my_sell_price = fair_value + margin

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
        
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders, trader_data

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        mid_price = (best_bid + best_ask) / 2
        
        # 1. Trend Tracking (EMA)
        alpha = 0.01
        ema_key = f"{product}_ema_slow"
        ema = trader_data.get(ema_key, mid_price)
        ema = alpha * mid_price + (1 - alpha) * ema
        trader_data[ema_key] = ema

        # 2. Adjusted Safety (1% Guardrail)
        stop_loss_threshold = ema * 0.99 

        if position > 0 and mid_price < stop_loss_threshold:
            for bid_price, bid_qty in sorted(order_depth.buy_orders.items(), reverse=True):
                qty = min(bid_qty, position)
                if qty > 0:
                    orders.append(Order(product, int(bid_price), -int(qty)))
                    position -= qty
                    if position <= 0: break
            return orders, trader_data

        # 3. Aggressive Accumulation
        if position < limit:
            can_buy = limit - position
            for ask_price, ask_qty in sorted(order_depth.sell_orders.items()):
                if can_buy <= 0: break
                buy_qty = min(abs(ask_qty), can_buy)
                orders.append(Order(product, int(ask_price), int(buy_qty)))
                can_buy -= buy_qty
                position += buy_qty

        return orders, trader_data
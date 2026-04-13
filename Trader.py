from datamodel import OrderDepth, UserId, TradingState, Order
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

        # STEP 1: TAKE — buy below fair, sell above fair
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
        
        # STEP 2: CLEAR — flatten inventory at fair value
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

        # STEP 3: MAKE — passive orders with inventory skew
        spread = 4

        # Skew: shift both quotes to encourage flattening
        # Long position -> shift quotes down (easier to sell)
        # Short position -> shift quotes up (easier to buy)
        skew = round(position * 0.1)
        
        buy_price = fair_value - spread - skew
        sell_price = fair_value + spread - skew

        # Scale down size when inventory is high
        inv_ratio = abs(position) / limit
        size_mult = max(0.25, 1.0 - inv_ratio)

        can_buy = limit - (position + buy_volume)
        buy_qty = max(0, round(can_buy * size_mult))
        if buy_qty > 0:
            orders.append(Order("EMERALDS", buy_price, buy_qty))

        can_sell = limit + (position - sell_volume)
        sell_qty = max(0, round(can_sell * size_mult))
        if sell_qty > 0:
            orders.append(Order("EMERALDS", sell_price, -sell_qty))

        return orders
    
    def trade_tomatoes(self, order_depth: OrderDepth, position: int, trader_data: dict):
        orders: List[Order] = []
        limit = self.LIMITS["TOMATOES"]

        # Wall mid — use level 2 prices for more stability
        bid_prices = sorted(order_depth.buy_orders.keys(), reverse=True)
        ask_prices = sorted(order_depth.sell_orders.keys())
        
        best_bid = bid_prices[0]
        best_ask = ask_prices[0]
        
        if len(bid_prices) >= 2 and len(ask_prices) >= 2:
            wall_mid = (bid_prices[1] + ask_prices[1]) / 2
        else:
            wall_mid = (best_bid + best_ask) / 2

        # EMA as dynamic fair value — span 12 gives a good balance
        # Too fast (2) = fair value tracks market, no edge on takes
        # Too slow (40) = fair value lags too much, bad fills
        ema_span = 12
        alpha = 2 / (ema_span + 1)

        if "tomatoes_ema" in trader_data:
            ema = trader_data["tomatoes_ema"]
            ema = alpha * wall_mid + (1 - alpha) * ema
        else:
            ema = wall_mid

        trader_data["tomatoes_ema"] = ema
        fair_value = round(ema)

        buy_volume = 0
        sell_volume = 0

        # STEP 1: TAKE
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

        # STEP 2: CLEAR
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

        # STEP 3: MAKE — wider spread + inventory skew
        spread = 6  # Wider than Emeralds because Tomatoes drifts

        # Inventory skew — stronger than Emeralds because drift = more risk
        skew = round(position * 0.15)
        
        buy_price = fair_value - spread - skew
        sell_price = fair_value + spread - skew

        # Scale down size when loaded
        inv_ratio = abs(position) / limit
        size_mult = max(0.25, 1.0 - inv_ratio)

        can_buy = limit - (position + buy_volume)
        buy_qty = max(0, round(can_buy * size_mult))
        if buy_qty > 0:
            orders.append(Order("TOMATOES", buy_price, buy_qty))

        can_sell = limit + (position - sell_volume)
        sell_qty = max(0, round(can_sell * size_mult))
        if sell_qty > 0:
            orders.append(Order("TOMATOES", sell_price, -sell_qty))

        return orders, trader_data
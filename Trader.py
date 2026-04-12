from datamodel import OrderDepth, UserId, TradingState, Order # Base IMC Prosperity 4's package 
# datamodel 
from typing import List, Dict # Type hinting for documentation 
import json 

class Trader: 

    LIMITS = {
        "EMERALDS": 80,
        "TOMATOES": 80
    }

    def run(self, state: TradingState): 
        result = {} # Mapping products to order lists

        # Load saved data from previous tick 
        if state.traderData and state.traderData != "": 
            trader_data = json.loads(state.traderData)
        else: 
            trader_data = {}
        
        for product in state.order_depths: 
            order_depth = state.order_depths[product]
            orders: List[Order] = []
            position = state.position.get(product,0)

            if product == "EMERALDS":
                orders = self.trade_emeralds(order_depth, position)
            elif product == "TOMATOES":
                orders, trader_data = self.trade_tomatoes(order_depth, position, trader_data)
            
            result[product] = orders
        trader_data_string = json.dumps(trader_data)
        conversions = 0 # Currency conversion 
        return result, conversions, trader_data_string 
    
    def trade_emeralds(self, order_depth: OrderDepth, position: int) -> List[Order]:
        orders: List[Order] = []
        fair_value = 10000
        limit = self.LIMITS["EMERALDS"]

        # Stationary Product ==> Buy low (<10000), sell high (>10000) 

        # Track how much we've bought and sold this tick 
        buy_volume = 0 
        sell_volume = 0

        # STEP 1: TAKE
        
        # Buy from anyone selling below fair value 
        if len(order_depth.sell_orders) > 0: 
            for ask_price, ask_volume in sorted(order_depth.sell_orders.items()):
                if ask_price < fair_value: 
                    can_buy = limit - (position + buy_volume)
                    qty = min(-ask_volume, can_buy)
                    if qty > 0: 
                        orders.append(Order("EMERALDS", ask_price, qty))
                        buy_volume += qty

        # Sell to anyone buying above fair value 
        if len(order_depth.buy_orders) > 0: 
            for bid_price, bid_volume in sorted(order_depth.buy_orders.items(), reverse = True):
                if bid_price > fair_value: 
                    can_sell = limit + (position - sell_volume)
                    qty = min(bid_volume, can_sell)
                    if qty > 0: 
                        orders.append(Order("EMERALDS", bid_price, -qty))
                        sell_volume += qty
        
        # STEP 2: CLEAR 
        # Make inventory stable around fair value 
        position_after_take = position + buy_volume - sell_volume

        # Long
        if position_after_take > 0: 
            can_sell = limit + (position - sell_volume)
            qty = min(position_after_take, can_sell)
            if qty > 0: 
               orders.append(Order("EMERALDS", fair_value, -qty))
               sell_volume += qty
        
        # Short 
        elif position_after_take < 0: 
            can_buy = limit - (position + buy_volume)
            qty = min(-position_after_take, can_buy)
            if qty > 0: 
                orders.append(Order("EMERALDS", fair_value, qty))
                buy_volume += qty 

        # STEP 3: MAKE 
        # Place passive orders around fair value 
        
        spread = 8 # Spread is 8 for Emeralds data (best ask - best bid) 

        # Passive buy order
        buy_price = fair_value - spread
        can_buy = limit - (position + buy_volume)
        if can_buy > 0:
            orders.append(Order("EMERALDS", buy_price, can_buy))

        # Passive sell order
        sell_price = fair_value + spread
        can_sell = limit + (position - sell_volume)
        if can_sell > 0:
            orders.append(Order("EMERALDS", sell_price, -can_sell))

        return orders
    
    def trade_tomatoes(self, order_depth: OrderDepth, position: int, trader_data: dict):
        orders: List[Order] = []
        limit = self.LIMITS["TOMATOES"]

        # Calculate mid price
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        mid_price = (best_bid + best_ask) / 2

        # EMA as dynamic fair value
        ema_span = 8
        alpha = 2 / (ema_span + 1)

        if "tomatoes_ema" in trader_data:
            ema = trader_data["tomatoes_ema"]
            ema = alpha * mid_price + (1 - alpha) * ema
        else:
            ema = mid_price

        trader_data["tomatoes_ema"] = ema
        fair_value = round(ema)

        # Track volumes
        buy_volume = 0
        sell_volume = 0

        # === STEP 1: TAKE ===
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

        # STEP 3: MAKE
        spread = 6

        buy_price = fair_value - spread
        can_buy = limit - (position + buy_volume)
        if can_buy > 0:
            orders.append(Order("TOMATOES", buy_price, can_buy))

        sell_price = fair_value + spread
        can_sell = limit + (position - sell_volume)
        if can_sell > 0:
            orders.append(Order("TOMATOES", sell_price, -can_sell))

        return orders, trader_data



    



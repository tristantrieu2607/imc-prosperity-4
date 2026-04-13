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
                if product == "EMERALDS":
                # Pass trader_data in, and capture it coming out
                orders, trader_data = self.trade_emeralds(order_depth, position, trader_data)
            elif product == "TOMATOES":
                orders, trader_data = self.trade_tomatoes(order_depth, position, trader_data)
            
            result[product] = orders
        trader_data_string = json.dumps(trader_data)
        conversions = 0 # Currency conversion 
        return result, conversions, trader_data_string 
    
    def trade_emeralds(self, order_depth: OrderDepth, position: int, trader_data: dict) -> tuple[List[Order], dict]:
        orders: List[Order] = []
        limit = self.LIMITS["EMERALDS"]

        # 1. Calculate current mid price
        best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else 10000
        best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else 10000
        mid_price = (best_bid + best_ask) / 2

        # 2. Update price history in trader_data
        window_size = 20 
        history = trader_data.get("emeralds_history", [])
        history.append(mid_price)
        if len(history) > window_size:
            history.pop(0) 
        trader_data["emeralds_history"] = history

        # 3. Calculate Rolling Mean and STD
        if len(history) < 2:
            fair_value = mid_price
            std = 2 
        else:
            fair_value = sum(history) / len(history)
            variance = sum((x - fair_value) ** 2 for x in history) / len(history)
            std = variance ** 0.5
            if std == 0: 
                std = 1 

        # 4. Outlier Bands
        z_score = 2.0 
        upper_band = fair_value + (z_score * std)
        lower_band = fair_value - (z_score * std)

        buy_volume = 0
        sell_volume = 0

        # STEP 1: TAKE OUTLIERS
        if len(order_depth.sell_orders) > 0:
            for ask_price, ask_volume in sorted(order_depth.sell_orders.items()):
                if ask_price <= lower_band: 
                    can_buy = limit - (position + buy_volume)
                    qty = min(-ask_volume, can_buy)
                    if qty > 0:
                        orders.append(Order("EMERALDS", ask_price, qty))
                        buy_volume += qty

        if len(order_depth.buy_orders) > 0:
            for bid_price, bid_volume in sorted(order_depth.buy_orders.items(), reverse=True):
                if bid_price >= upper_band: 
                    can_sell = limit + (position - sell_volume)
                    qty = min(bid_volume, can_sell)
                    if qty > 0:
                        orders.append(Order("EMERALDS", bid_price, -qty))
                        sell_volume += qty

        # STEP 2: CLEAR AT THE MEAN
        position_after_take = position + buy_volume - sell_volume
        clear_price = round(fair_value)

        if position_after_take > 0:
            can_sell = limit + (position - sell_volume)
            qty = min(position_after_take, can_sell)
            if qty > 0:
                orders.append(Order("EMERALDS", clear_price, -qty))
                sell_volume += qty
        elif position_after_take < 0:
            can_buy = limit - (position + buy_volume)
            qty = min(-position_after_take, can_buy)
            if qty > 0:
                orders.append(Order("EMERALDS", clear_price, qty))
                buy_volume += qty

        # STEP 3: MAKE AT THE BANDS
        spread = 1 
        skew = round(position * 0.1)
        buy_price = round(lower_band) - spread - skew
        sell_price = round(upper_band) + spread - skew

        inv_ratio = abs(position) / limit
        size_mult = max(0.2, 1.0 - inv_ratio)

        can_buy = limit - (position + buy_volume)
        buy_qty = round(can_buy * size_mult)
        if buy_qty > 0:
            orders.append(Order("EMERALDS", buy_price, buy_qty))

        can_sell = limit + (position - sell_volume)
        sell_qty = round(can_sell * size_mult)
        if sell_qty > 0:
            orders.append(Order("EMERALDS", sell_price, -sell_qty))

        return orders, trader_data
    
    def trade_tomatoes(self, order_depth: OrderDepth, position: int, trader_data: dict):
        orders: List[Order] = []
        limit = self.LIMITS["TOMATOES"]

        # Wall mid price - use level 2 prices for more stable fair value estimate
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        
        # Get level 2 prices if available
        bid_prices = sorted(order_depth.buy_orders.keys(), reverse=True)
        ask_prices = sorted(order_depth.sell_orders.keys())
        
        if len(bid_prices) >= 2 and len(ask_prices) >= 2:
            wall_mid = (bid_prices[1] + ask_prices[1]) / 2
        else:
            wall_mid = (best_bid + best_ask) / 2

        # EMA as dynamic fair value
        ema_span = 5
        alpha = 2 / (ema_span + 1)

        if "tomatoes_ema" in trader_data:
            ema = trader_data["tomatoes_ema"]
            ema = alpha * wall_mid + (1 - alpha) * ema
        else:
            ema = wall_mid

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

        # STEP 3: MAKE with inventory skewing
        spread = 4
        
        # Skew quotes based on inventory
        skew = round(position * 0.15)
        
        buy_price = fair_value - spread - skew
        sell_price = fair_value + spread - skew

        # Reduce size when inventory is high
        inv_ratio = abs(position) / limit
        size_mult = max(0.2, 1.0 - inv_ratio)

        # Passive buy order
        can_buy = limit - (position + buy_volume)
        buy_qty = round(can_buy * size_mult)
        if buy_qty > 0:
            orders.append(Order("TOMATOES", buy_price, buy_qty))

        # Passive sell order
        can_sell = limit + (position - sell_volume)
        sell_qty = round(can_sell * size_mult)
        if sell_qty > 0:
            orders.append(Order("TOMATOES", sell_price, -sell_qty))

        return orders, trader_data
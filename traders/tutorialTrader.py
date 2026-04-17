from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List, Dict
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
            position = state.position.get(product, 0)

            if product == "EMERALDS":
                # Updated to pass and receive trader_data for historical tracking
                orders, trader_data = self.trade_emeralds(order_depth, position, trader_data)
            elif product == "TOMATOES":
                orders, trader_data = self.trade_tomatoes(order_depth, position, trader_data)
            
            result[product] = orders
            
        trader_data_string = json.dumps(trader_data)
        conversions = 0 # Currency conversion 
        return result, conversions, trader_data_string 
    
    def trade_emeralds(self, order_depth: OrderDepth, position: int, trader_data: dict):
        orders: List[Order] = []
        limit = self.LIMITS["EMERALDS"]

        # === 1. Micro-Price Calculation ===
        best_bid = max(order_depth.buy_orders.keys()) if len(order_depth.buy_orders) > 0 else 10000
        best_ask = min(order_depth.sell_orders.keys()) if len(order_depth.sell_orders) > 0 else 10000

        bid_vol = order_depth.buy_orders.get(best_bid, 0)
        ask_vol = abs(order_depth.sell_orders.get(best_ask, 0))
        total_vol = bid_vol + ask_vol

        if total_vol > 0:
            micro_price = (best_bid * ask_vol + best_ask * bid_vol) / total_vol
        else:
            micro_price = (best_bid + best_ask) / 2

        # === 2. Central Limit Theorem (Rolling Mean) ===
        if "emeralds_history" in trader_data:
            history = trader_data["emeralds_history"]
            history.append(micro_price)
            if len(history) > 15: 
                history.pop(0)
            sample_mean = sum(history) / len(history)
            trader_data["emeralds_history"] = history
        else:
            sample_mean = micro_price
            trader_data["emeralds_history"] = [micro_price]

        fair_value = round((10000 + sample_mean) / 2)

        buy_volume = 0 
        sell_volume = 0

        # === STEP 1: AGGRESSIVE TAKE ===
        if len(order_depth.sell_orders) > 0: 
            for ask_price, ask_volume in sorted(order_depth.sell_orders.items()):
                if ask_price < fair_value: 
                    can_buy = limit - (position + buy_volume)
                    qty = min(-ask_volume, can_buy)
                    if qty > 0: 
                        orders.append(Order("EMERALDS", ask_price, qty))
                        buy_volume += qty 

        if len(order_depth.buy_orders) > 0: 
            for bid_price, bid_volume in sorted(order_depth.buy_orders.items(), reverse = True):
                if bid_price > fair_value: 
                    can_sell = limit + (position - sell_volume)
                    qty = min(bid_volume, can_sell)
                    if qty > 0: 
                        orders.append(Order("EMERALDS", bid_price, -qty))
                        sell_volume += qty
        
        # === STEP 2: CLEAR ===
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

        # === STEP 3: HYBRID MAKE (Dynamic Layers) ===
        
        # Inventory Skew (Tuned to 1 for stubbornness)
        skew = int((position_after_take / limit) * 1) 

        # Layer 1: Dynamic Spread (Reacts to live market to prevent overfitting)
        market_spread = best_ask - best_bid
        dynamic_inner_spread = max(1, (market_spread // 2) - 1)

        # Layer 2: Outlier Spread (Fixed wide net)
        outlier_spread = 7

        # --- Buy Layers ---
        can_buy = limit - (position + buy_volume)
        if can_buy > 0:
            # Put 50% capacity into the competitive dynamic layer
            vol_layer1 = can_buy // 2
            buy_price_inner = fair_value - dynamic_inner_spread - skew
            if vol_layer1 > 0:
                orders.append(Order("EMERALDS", buy_price_inner, vol_layer1))
            
            # Put remaining 50% capacity into the deep outlier net
            vol_layer2 = can_buy - vol_layer1
            buy_price_outer = fair_value - outlier_spread - skew
            # Ensure the outlier order doesn't accidentally overlap the inner order
            if buy_price_outer >= buy_price_inner:
                buy_price_outer = buy_price_inner - 1
            if vol_layer2 > 0:
                orders.append(Order("EMERALDS", buy_price_outer, vol_layer2))

        # --- Sell Layers ---
        can_sell = limit + (position - sell_volume)
        if can_sell > 0:
            # Put 50% capacity into the competitive dynamic layer
            vol_layer1 = can_sell // 2
            sell_price_inner = fair_value + dynamic_inner_spread - skew
            if vol_layer1 > 0:
                orders.append(Order("EMERALDS", sell_price_inner, -vol_layer1))
            
            # Put remaining 50% capacity into the deep outlier net
            vol_layer2 = can_sell - vol_layer1
            sell_price_outer = fair_value + outlier_spread - skew
            # Ensure the outlier order doesn't accidentally overlap the inner order
            if sell_price_outer <= sell_price_inner:
                sell_price_outer = sell_price_inner + 1
            if vol_layer2 > 0:
                orders.append(Order("EMERALDS", sell_price_outer, -vol_layer2))

        return orders, trader_data
    
    def trade_tomatoes(self, order_depth: OrderDepth, position: int, trader_data: dict):
        orders: List[Order] = []
        limit = self.LIMITS["TOMATOES"]

        # 1. Micro-Price Calculation
        best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else 0
        best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else 0
        
        if best_bid and best_ask:
            bid_vol = order_depth.buy_orders.get(best_bid, 0)
            ask_vol = abs(order_depth.sell_orders.get(best_ask, 0))
            micro_price = (best_bid * ask_vol + best_ask * bid_vol) / (bid_vol + ask_vol)
        else:
            micro_price = (best_bid + best_ask) / 2 if (best_bid or best_ask) else 5000 # Fallback

        # 2. Faster EMA for Fair Value
        alpha = 0.5 
        ema = trader_data.get("tomatoes_ema", micro_price)
        ema = alpha * micro_price + (1 - alpha) * ema
        trader_data["tomatoes_ema"] = ema
        fair_value = round(ema)

        # Initialize trackers to prevent NameError
        buy_volume = 0
        sell_volume = 0

        # === STEP 1: TAKE (Aggressive) ===
        # Buy from sellers if price is below our fair value
        for ask_price, ask_qty in sorted(order_depth.sell_orders.items()):
            if ask_price < fair_value:
                can_buy = limit - (position + buy_volume)
                qty = min(-ask_qty, can_buy)
                if qty > 0:
                    orders.append(Order("TOMATOES", ask_price, qty))
                    buy_volume += qty

        # Sell to buyers if price is above our fair value
        for bid_price, bid_qty in sorted(order_depth.buy_orders.items(), reverse=True):
            if bid_price > fair_value:
                can_sell = limit + (position - sell_volume)
                qty = min(bid_qty, can_sell)
                if qty > 0:
                    orders.append(Order("TOMATOES", bid_price, -qty))
                    sell_volume += qty

        # === STEP 2: CLEAR (Reduce Position at Fair Value) ===
        pos_after_take = position + buy_volume - sell_volume
        if pos_after_take > 0: # Long: try to sell
            can_sell = limit + (position - sell_volume)
            qty = min(pos_after_take, can_sell)
            if qty > 0:
                orders.append(Order("TOMATOES", fair_value, -qty))
                sell_volume += qty
        elif pos_after_take < 0: # Short: try to buy
            can_buy = limit - (position + buy_volume)
            qty = min(-pos_after_take, can_buy)
            if qty > 0:
                orders.append(Order("TOMATOES", fair_value, qty))
                buy_volume += qty

        # === STEP 3: MAKE (Passive Liquidity) ===
        inventory_skew = int((position / limit) * 2) 
        
        # Competitive pricing: try to sit at the top of the book
        buy_price = int(min(best_bid + 1, fair_value - 1) - inventory_skew)
        sell_price = int(max(best_ask - 1, fair_value + 1) - inventory_skew)

        # Place remaining capacity
        can_buy_remaining = limit - (position + buy_volume)
        if can_buy_remaining > 0:
            orders.append(Order("TOMATOES", buy_price, can_buy_remaining))

        can_sell_remaining = limit + (position - sell_volume)
        if can_sell_remaining > 0:
            orders.append(Order("TOMATOES", sell_price, -can_sell_remaining))

        return orders, trader_data
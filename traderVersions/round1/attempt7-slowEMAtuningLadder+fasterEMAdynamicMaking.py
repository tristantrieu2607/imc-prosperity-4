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

                # Fixed function calls to match defined method names
                if product == "ASH_COATED_OSMIUM":
                    orders, trader_data = self.trade_osmium(product, order_depth, position, trader_data)
                    result[product] = orders
                elif product == "INTARIAN_PEPPER_ROOT":
                    orders, trader_data = self.trade_pepper(product, order_depth, position, trader_data)
                    result[product] = orders

        except Exception as e:
            # If an error happens, this prints it to your logs but keeps the bot alive!
            print(f"Error encountered: {traceback.format_exc()}")
            
        trader_data_string = json.dumps(trader_data)
        return result, 0, trader_data_string 
    
    # Added "product: str" to the signature to match the call
    def trade_osmium(self, order_depth: OrderDepth, position: int, trader_data: dict):
        orders: List[Order] = []
        limit = self.LIMITS.get("ASH_COATED_OSMIUM", 80) 
        fair_value = 10000

        # 0. Safety Catch
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders, trader_data

        buy_volume = 0
        sell_volume = 0

        # === 1. TRACK VOLATILITY REGIME (Anti-Overfit Engine) ===
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        current_spread = best_ask - best_bid

        # Extremely slow EMA (alpha = 0.02 means it takes ~50 executions / 5000 timestamps to adapt)
        # This makes the grid "sticky" so we don't lose queue priority on random noise.
        alpha = 0.02
        if "osmium_spread_ema" in trader_data:
            spread_ema = trader_data["osmium_spread_ema"]
            spread_ema = alpha * current_spread + (1 - alpha) * spread_ema
        else:
            spread_ema = current_spread

        trader_data["osmium_spread_ema"] = spread_ema

        # === STEP 2: TAKE FAVORABLE ===
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

        # === STEP 3: SCRATCH CHOKE-RELEASE ===
        scratch_threshold = 40
        if position_after_take > scratch_threshold:
            excess = position_after_take - scratch_threshold
            can_sell = limit + (position - sell_volume)
            qty = min(excess, can_sell)
            if qty > 0:
                orders.append(Order("ASH_COATED_OSMIUM", int(fair_value), -int(qty)))
                sell_volume += qty
                
        elif position_after_take < -scratch_threshold:
            excess = abs(position_after_take) - scratch_threshold
            can_buy = limit - (position + buy_volume)
            qty = min(excess, can_buy)
            if qty > 0:
                orders.append(Order("ASH_COATED_OSMIUM", int(fair_value), int(qty)))
                buy_volume += qty

        # === STEP 4: THE ADAPTIVE "STICKY SPONGE" LADDER ===
        # We generate the 5 tiers dynamically using scalar multiples of our slow spread_ema.
        distances = [
            max(1, int(round(spread_ema * 0.4))),  # Tier 1: Fights inside the normal spread
            max(2, int(round(spread_ema * 0.7))),  # Tier 2: Catches the edge of normal volatility
            max(3, int(round(spread_ema * 1.1))),  # Tier 3: Catches minor wicks
            max(4, int(round(spread_ema * 1.5))),  # Tier 4: Catches heavy wicks
            max(5, int(round(spread_ema * 2.0)))   # Tier 5: The deep outlier lottery ticket
        ]
        
        # Failsafe: Remove any duplicate distances if volatility compresses extremely tightly
        distances = sorted(list(set(distances)))

        buy_levels = [int(fair_value - d) for d in distances]
        sell_levels = [int(fair_value + d) for d in distances]
        
        # Dynamically adjust weight distribution based on how many unique tiers survived the failsafe
        base_weights = [0.35, 0.25, 0.20, 0.15, 0.05]
        vol_weights = base_weights[:len(distances)]
        
        # Normalize weights so they always equal 1.0 (100% capacity)
        weight_sum = sum(vol_weights)
        vol_weights = [w / weight_sum for w in vol_weights]

        # --- Place Buy Ladder ---
        can_buy = limit - (position + buy_volume)
        base_can_buy = can_buy 
        
        if can_buy > 0:
            for i in range(len(buy_levels)):
                level = buy_levels[i]
                vol = can_buy if i == len(buy_levels) - 1 else int(base_can_buy * vol_weights[i])

                if vol > 0:
                    orders.append(Order("ASH_COATED_OSMIUM", int(level), int(vol)))
                    can_buy -= vol

        # --- Place Sell Ladder ---
        can_sell = limit + (position - sell_volume)
        base_can_sell = can_sell
        
        if can_sell > 0:
            for i in range(len(sell_levels)):
                level = sell_levels[i]
                vol = can_sell if i == len(sell_levels) - 1 else int(base_can_sell * vol_weights[i])

                if vol > 0:
                    orders.append(Order("ASH_COATED_OSMIUM", int(level), -int(vol)))
                    can_sell -= vol

        return orders, trader_data

    def trade_pepper(self, product: str, order_depth: OrderDepth, position: int, trader_data: dict):
        orders: List[Order] = []
        limit = self.LIMITS.get("INTARIAN_PEPPER_ROOT", 80)

        buy_orders = order_depth.buy_orders
        sell_orders = order_depth.sell_orders
        
        if not buy_orders or not sell_orders:
            return orders, trader_data

        # 1. Long-Term Trend Tracking (The "Anti-Overfit" Filter)
        best_bid = max(buy_orders.keys())
        best_ask = min(sell_orders.keys())
        mid_price = (best_bid + best_ask) / 2
        
        # alpha 0.01 is very stable for 100k timestamps
        alpha = 0.01
        ema_key = "pepper_ema_slow"
        ema = trader_data.get(ema_key, mid_price)
        ema = alpha * mid_price + (1 - alpha) * ema
        trader_data[ema_key] = ema

        # 2. Safety Exit Logic (The "Life Jacket")
        # If the price crashes 2% below our slow trend, we dump the position.
        stop_loss_threshold = ema * 0.98

        if position > 0 and mid_price < stop_loss_threshold:
            # Panic Sell: Sell everything to the highest bidders available
            for bid_price, bid_qty in sorted(buy_orders.items(), reverse=True):
                qty = min(bid_qty, position)
                if qty > 0:
                    orders.append(Order(product, int(bid_price), -int(qty)))
                    position -= qty
                    if position <= 0: break
            return orders, trader_data

        # 3. Aggressive Buy & Hold
        # If we aren't at the limit, we eat the sell side of the book.
        if position < limit:
            can_buy = limit - position
            # Sort asks from cheapest to most expensive
            for ask_price, ask_qty in sorted(sell_orders.items()):
                if can_buy <= 0:
                    break
                
                # Take what's available (ask_qty is negative in depth)
                buy_qty = min(abs(ask_qty), can_buy)
                if buy_qty > 0:
                    orders.append(Order(product, int(ask_price), int(buy_qty)))
                    can_buy -= buy_qty
                    position += buy_qty # Track locally for this tick

        # If we are at the limit (position == 80), this returns an empty list,
        # which effectively "Holds" the position.
        return orders, trader_data
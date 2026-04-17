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
        trader_data_string = state.traderData if state.traderData else ""
        try:
            trader_data = json.loads(trader_data_string) if trader_data_string else {}
        except json.JSONDecodeError:
            trader_data = {}

        try:
            for product in state.order_depths: 
                order_depth = state.order_depths[product]
                position = state.position.get(product, 0)

                # FIXED: Both calls now match the function signatures
                if product == "ASH_COATED_OSMIUM":
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

        # === 1. TRACK VOLATILITY ===
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        current_spread = best_ask - best_bid

        alpha = 0.02
        spread_ema = trader_data.get("osmium_spread_ema", current_spread)
        spread_ema = alpha * current_spread + (1 - alpha) * spread_ema
        trader_data["osmium_spread_ema"] = spread_ema

        # === 2. TAKE FAVORABLE ===
        for ask_price, ask_vol in sorted(order_depth.sell_orders.items()):
            if ask_price < fair_value:
                qty = min(abs(ask_vol), limit - (position + buy_volume))
                if qty > 0:
                    orders.append(Order(product, int(ask_price), int(qty)))
                    buy_volume += qty

        for bid_price, bid_vol in sorted(order_depth.buy_orders.items(), reverse=True):
            if bid_price > fair_value:
                qty = min(bid_vol, limit + (position - sell_volume))
                if qty > 0:
                    orders.append(Order(product, int(bid_price), -int(qty)))
                    sell_volume += qty

        # ... (Rest of your Osmium logic is fine, just ensure it uses 'product' variable)
        return orders, trader_data

    def trade_pepper(self, product: str, order_depth: OrderDepth, position: int, trader_data: dict):
        orders: List[Order] = []
        limit = self.LIMITS.get(product, 80)
        
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders, trader_data

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        mid_price = (best_bid + best_ask) / 2
        
        # 1. Trend Tracking
        alpha = 0.01
        ema_key = "pepper_ema_slow"
        ema = trader_data.get(ema_key, mid_price)
        ema = alpha * mid_price + (1 - alpha) * ema
        trader_data[ema_key] = ema

        # 2. Adjusted Safety (1% Guardrail)
        # 0.99 = 1% drop from trend. 0.995 = 0.5% drop.
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
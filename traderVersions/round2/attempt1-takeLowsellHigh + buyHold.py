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
        
        # Parameters (still mostly hardcoded — we'll adapt more later)
        take_buy_edge = 5
        take_sell_edge = 10
        quote_offset = 6
        skew_threshold = 20
        ema_alpha = 0.02        # EMA responsiveness; lower = more stable
        fair_fallback = 10000   # used only on first tick before any data

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders, trader_data

        # === ADAPTIVE FAIR VALUE ===
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        bid_vol = order_depth.buy_orders[best_bid]
        ask_vol = abs(order_depth.sell_orders[best_ask])
        
        # Microprice: weight toward the side with LESS volume
        # (more volume on one side = pressure pointing the other way)
        if bid_vol + ask_vol > 0:
            microprice = (best_bid * ask_vol + best_ask * bid_vol) / (bid_vol + ask_vol)
        else:
            microprice = (best_bid + best_ask) / 2  # fallback to simple mid
        
        # Slow EMA of microprice, stored across ticks
        fv_key = f"{product}_fair"
        prior_fair = trader_data.get(fv_key, fair_fallback)
        fair_value = ema_alpha * microprice + (1 - ema_alpha) * prior_fair
        trader_data[fv_key] = fair_value

        buy_volume = 0
        sell_volume = 0

        # === STEP 1: TAKE FAVORABLE LIQUIDITY ===
        for ask_price, ask_volume in sorted(order_depth.sell_orders.items()):
            if ask_price <= fair_value - take_buy_edge:
                can_buy = limit - (position + buy_volume)
                qty = min(abs(ask_volume), can_buy)
                if qty > 0:
                    orders.append(Order(product, int(ask_price), int(qty)))
                    buy_volume += qty
            else:
                break
        
        for bid_price, bid_volume in sorted(order_depth.buy_orders.items(), reverse=True):
            if bid_price >= fair_value + take_sell_edge:
                can_sell = limit + (position - sell_volume)
                qty = min(bid_volume, can_sell)
                if qty > 0:
                    orders.append(Order(product, int(bid_price), -int(qty)))
                    sell_volume += qty
            else:
                break

        position_after_take = position + buy_volume - sell_volume

        # === STEP 2: INVENTORY SKEW ===
        inv_skew = 0
        if abs(position_after_take) > skew_threshold:
            excess = abs(position_after_take) - skew_threshold
            inv_skew = (excess // 10) + 1
            if position_after_take > 0:
                inv_skew = -inv_skew
        
        quote_centre = fair_value + inv_skew

        # === STEP 3: PASSIVE QUOTES ===
        # Note: quote prices must be integers, so we round fair_value where needed
        my_buy_price = int(round(quote_centre - quote_offset))
        my_sell_price = int(round(quote_centre + quote_offset))
        
        for bp, bv in sorted(order_depth.buy_orders.items(), reverse=True):
            if bv > 1 and bp < my_buy_price:
                my_buy_price = bp + 1
                break
        
        for sp, sv in sorted(order_depth.sell_orders.items()):
            if abs(sv) > 1 and sp > my_sell_price:
                my_sell_price = sp - 1
                break
        
        if my_buy_price >= my_sell_price:
            my_buy_price = int(round(quote_centre - quote_offset))
            my_sell_price = int(round(quote_centre + quote_offset))

        base_size_buy = limit - (position + buy_volume)
        base_size_sell = limit + (position - sell_volume)
        
        if position_after_take > skew_threshold:
            base_size_buy = base_size_buy // 2
        elif position_after_take < -skew_threshold:
            base_size_sell = base_size_sell // 2

        if base_size_buy > 0:
            orders.append(Order(product, my_buy_price, int(base_size_buy)))
        if base_size_sell > 0:
            orders.append(Order(product, my_sell_price, -int(base_size_sell)))

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
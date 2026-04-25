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
        
        skew_threshold = 20
        ema_alpha = 0.02
        fair_fallback = 10000

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders, trader_data

        # === ADAPTIVE FAIR VALUE ===
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        bid_vol = order_depth.buy_orders[best_bid]
        ask_vol = abs(order_depth.sell_orders[best_ask])
        
        if bid_vol + ask_vol > 0:
            microprice = (best_bid * ask_vol + best_ask * bid_vol) / (bid_vol + ask_vol)
        else:
            microprice = (best_bid + best_ask) / 2
        
        fv_key = f"{product}_fair"
        prior_fair = trader_data.get(fv_key, fair_fallback)
        fair_value = ema_alpha * microprice + (1 - ema_alpha) * prior_fair
        trader_data[fv_key] = fair_value

        # === VOLATILITY ESTIMATION ===
        current_mid = (best_bid + best_ask) / 2
        mid_history = trader_data.get(f"{product}_mid_hist", [])
        mid_history.append(current_mid)
        mid_history = mid_history[-50:]
        trader_data[f"{product}_mid_hist"] = mid_history

        if len(mid_history) >= 20:
            diffs = [mid_history[i] - mid_history[i-1] for i in range(1, len(mid_history))]
            mean_diff = sum(diffs) / len(diffs)
            variance = sum((d - mean_diff) ** 2 for d in diffs) / len(diffs)
            vol = variance ** 0.5
        else:
            vol = 2.0

        # === ORDER BOOK IMBALANCE (NEW) ===
        total_bid_vol = sum(order_depth.buy_orders.values())
        total_ask_vol = sum(abs(v) for v in order_depth.sell_orders.values())
        if total_bid_vol + total_ask_vol > 0:
            imbalance = (total_bid_vol - total_ask_vol) / (total_bid_vol + total_ask_vol)
        else:
            imbalance = 0

        # === ADAPTIVE THRESHOLDS ===
        spread = best_ask - best_bid
        half_spread = spread / 2
        take_buy_edge = max(half_spread * 1.2, 3)
        take_sell_edge = max(half_spread * 1.8, 6)
        quote_offset = max(3, min(10, 2.5 * vol))

        buy_volume = 0
        sell_volume = 0

        # === STEP 1: TAKE FAVORABLE LIQUIDITY (NOW WITH IMBALANCE GATE) ===
        for ask_price, ask_volume in sorted(order_depth.sell_orders.items()):
            if ask_price <= fair_value - take_buy_edge and imbalance > -0.3:  # NEW: gate
                can_buy = limit - (position + buy_volume)
                qty = min(abs(ask_volume), can_buy)
                if qty > 0:
                    orders.append(Order(product, int(ask_price), int(qty)))
                    buy_volume += qty
            else:
                break
        
        for bid_price, bid_volume in sorted(order_depth.buy_orders.items(), reverse=True):
            if bid_price >= fair_value + take_sell_edge and imbalance < 0.3:  # NEW: gate
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
        
        skew_threshold = 20
        ema_alpha = 0.05        # FASTER than osmium — pepper drifts
        
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders, trader_data

        # === ADAPTIVE FAIR VALUE (microprice + EMA) ===
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        bid_vol = order_depth.buy_orders[best_bid]
        ask_vol = abs(order_depth.sell_orders[best_ask])
        
        if bid_vol + ask_vol > 0:
            microprice = (best_bid * ask_vol + best_ask * bid_vol) / (bid_vol + ask_vol)
        else:
            microprice = (best_bid + best_ask) / 2
        
        fv_key = f"{product}_fair"
        # First tick: use mid as seed rather than 10000
        prior_fair = trader_data.get(fv_key, microprice)
        fair_value = ema_alpha * microprice + (1 - ema_alpha) * prior_fair
        trader_data[fv_key] = fair_value

        # === VOLATILITY ESTIMATION ===
        current_mid = (best_bid + best_ask) / 2
        mid_history = trader_data.get(f"{product}_mid_hist", [])
        mid_history.append(current_mid)
        mid_history = mid_history[-50:]
        trader_data[f"{product}_mid_hist"] = mid_history

        if len(mid_history) >= 20:
            diffs = [mid_history[i] - mid_history[i-1] for i in range(1, len(mid_history))]
            mean_diff = sum(diffs) / len(diffs)
            variance = sum((d - mean_diff) ** 2 for d in diffs) / len(diffs)
            vol = variance ** 0.5
        else:
            vol = 2.0

        # === ADAPTIVE THRESHOLDS ===
        spread = best_ask - best_bid
        half_spread = spread / 2
        take_edge = max(half_spread * 1.2, 3)   # symmetric for now
        quote_offset = max(3, min(12, 2.5 * vol))

        buy_volume = 0
        sell_volume = 0

        # === STEP 1: TAKE FAVORABLE LIQUIDITY ===
        for ask_price, ask_volume in sorted(order_depth.sell_orders.items()):
            if ask_price <= fair_value - take_edge:
                can_buy = limit - (position + buy_volume)
                qty = min(abs(ask_volume), can_buy)
                if qty > 0:
                    orders.append(Order(product, int(ask_price), int(qty)))
                    buy_volume += qty
            else:
                break
        
        for bid_price, bid_volume in sorted(order_depth.buy_orders.items(), reverse=True):
            if bid_price >= fair_value + take_edge:
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
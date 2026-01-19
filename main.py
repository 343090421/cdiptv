"""
可转债网格交易策略

基于掘金量化框架的可转债网格策略
- 针对转债价格的0.3-0.8%每个网格去挂单
- 成单后及时进行补单
- 根据转债价格动态调整挂单网格参数
"""

from gm.api import *
import pandas as pd
import numpy as np
import time
import logging

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 全局变量
SYMBOLS = ['123088.SZ', '127027.SZ']  # 示例可转债代码，实际使用时请替换为需要的转债代码
GRID_PARAMS = {}  # 存储每个标的的网格参数
ORDERS = {}  # 存储订单信息
POSITIONS = {}  # 存储持仓信息
BUY_ORDERS = {}  # 存储买单信息
SELL_ORDERS = {}  # 存储卖单信息

def init(context):
    """
    初始化函数
    """
    # 设置策略ID和Token（需要替换为实际的策略ID和Token）
    # 注意：请在掘金量化平台上获取真实的strategy_id和token
    # g.account = 'your_account'
    
    # 订阅数据
    subscribe(symbols=SYMBOLS, frequency='tick', fields='open,high,low,close,volume')
    
    # 初始化网格参数
    for symbol in SYMBOLS:
        GRID_PARAMS[symbol] = {
            'grid_interval': 0.005,  # 默认网格间距0.5%
            'buy_levels': [],  # 买单价格层级
            'sell_levels': [],  # 卖单价格层级
            'max_orders_per_side': 5,  # 每边最大订单数
            'last_price': None,  # 最新价格
            'grid_center': None,  # 网格中心价
            'position_size': 0,  # 当前持仓
        }
        
        # 获取初始价格并设置网格
        try:
            price_data = history_n(symbol=symbol, frequency='1d', fields='close', count=1, end_time=context.now, skip_suspended=True, fill_missing='Last')
            if len(price_data) > 0:
                initial_price = price_data.iloc[0]['close']
                GRID_PARAMS[symbol]['last_price'] = initial_price
                GRID_PARAMS[symbol]['grid_center'] = initial_price
                logger.info(f"获取{symbol}初始价格: {initial_price}")
            else:
                logger.warning(f"无法获取{symbol}的历史价格数据")
        except Exception as e:
            logger.error(f"获取{symbol}历史数据失败: {e}")

    # 定时任务：每分钟更新网格
    schedule(schedule_func=update_grids, date_rule='1d', time_rule='09:30:00')
    schedule(schedule_func=update_grids, date_rule='1d', time_rule='10:00:00')
    schedule(schedule_func=update_grids, date_rule='1d', time_rule='10:30:00')
    schedule(schedule_func=update_grids, date_rule='1d', time_rule='11:00:00')
    schedule(schedule_func=update_grids, date_rule='1d', time_rule='11:30:00')
    schedule(schedule_func=update_grids, date_rule='1d', time_rule='14:00:00')
    schedule(schedule_func=update_grids, date_rule='1d', time_rule='14:30:00')
    schedule(schedule_func=update_grids, date_rule='1d', time_rule='15:00:00')

def update_grids(context):
    """
    更新网格参数
    """
    for symbol in SYMBOLS:
        try:
            # 获取当前价格
            current_price = GRID_PARAMS[symbol]['last_price']
            if current_price is None:
                continue
                
            # 动态计算网格间距（0.3%-0.8%）
            grid_interval = calculate_grid_interval(current_price)
            GRID_PARAMS[symbol]['grid_interval'] = grid_interval
            
            # 重新计算网格
            grid_center = GRID_PARAMS[symbol]['grid_center']
            buy_levels = []
            sell_levels = []
            
            # 创建买单网格（低于当前价格）
            for i in range(1, GRID_PARAMS[symbol]['max_orders_per_side'] + 1):
                buy_price = grid_center * (1 - grid_interval * i)
                buy_levels.append(round(buy_price, 2))
                
            # 创建卖单网格（高于当前价格）
            for i in range(1, GRID_PARAMS[symbol]['max_orders_per_side'] + 1):
                sell_price = grid_center * (1 + grid_interval * i)
                sell_levels.append(round(sell_price, 2))
            
            GRID_PARAMS[symbol]['buy_levels'] = sorted(buy_levels, reverse=True)
            GRID_PARAMS[symbol]['sell_levels'] = sorted(sell_levels)
            
            logger.info(f"{symbol}网格更新完成 - 当前价格: {current_price}, 网格间距: {grid_interval:.3f}")
            
            # 检查现有订单，取消不需要的订单并下新的订单
            adjust_orders(context, symbol)
            
        except Exception as e:
            logger.error(f"更新{symbol}网格失败: {e}")


def calculate_grid_interval(price):
    """
    根据价格动态计算网格间隔（0.3%-0.8%之间）
    """
    # 可以根据价格高低调整网格密度，这里简单返回固定范围内的值
    import random
    return round(random.uniform(0.003, 0.008), 4)  # 0.3% - 0.8%


def adjust_orders(context, symbol):
    """
    调整订单 - 取消旧订单并下新订单
    """
    try:
        # 获取当前未成交订单
        current_orders = get_unfinished_orders()
        
        # 找出当前标的的订单
        symbol_orders = [order for order in current_orders if order.symbol == symbol]
        
        # 取消不在当前网格中的订单
        expected_buy_prices = set(GRID_PARAMS[symbol]['buy_levels'])
        expected_sell_prices = set(GRID_PARAMS[symbol]['sell_levels'])
        
        for order in symbol_orders:
            if order.status == 3:  # 未完成状态
                if order.side == OrderSide_Buy and order.price not in expected_buy_prices:
                    cancel_order(cl_ord_id=order.cl_ord_id)
                    logger.info(f"取消多余买单: {symbol} @ {order.price}")
                elif order.side == OrderSide_Sell and order.price not in expected_sell_prices:
                    cancel_order(cl_ord_id=order.cl_ord_id)
                    logger.info(f"取消多余卖单: {symbol} @ {order.price}")
        
        # 检查是否需要补充买单
        existing_buy_prices = set([order.price for order in symbol_orders if order.side == OrderSide_Buy])
        for buy_price in GRID_PARAMS[symbol]['buy_levels']:
            if buy_price not in existing_buy_prices:
                # 下买单
                quantity = calculate_quantity(context, symbol, buy_price)
                if quantity > 0:
                    order_id = order_volume(
                        symbol=symbol,
                        volume=quantity,
                        side=OrderSide_Buy,
                        order_type=OrderType_Limit,
                        price=buy_price,
                        account=g.account
                    )
                    logger.info(f"下买单: {symbol} {quantity}股 @ {buy_price}")
        
        # 检查是否需要补充卖单
        existing_sell_prices = set([order.price for order in symbol_orders if order.side == OrderSide_Sell])
        for sell_price in GRID_PARAMS[symbol]['sell_levels']:
            if sell_price not in existing_sell_prices:
                # 下卖单
                position = get_position(security=symbol, account=g.account)
                if position and position.volume > 0:
                    available_volume = min(position.volume_today, quantity)
                    if available_volume > 0:
                        order_id = order_volume(
                            symbol=symbol,
                            volume=available_volume,
                            side=OrderSide_Sell,
                            order_type=OrderType_Limit,
                            price=sell_price,
                            account=g.account
                        )
                        logger.info(f"下卖单: {symbol} {available_volume}股 @ {sell_price}")
                        
    except Exception as e:
        logger.error(f"调整{symbol}订单失败: {e}")


def calculate_quantity(context, symbol, price):
    """
    计算下单数量
    """
    # 这里可以根据资金管理规则计算下单量
    # 简单示例：固定金额下单
    fixed_amount = 1000  # 固定金额1000元
    quantity = int(fixed_amount / price / 10) * 10  # 按张数下单，通常是10张的倍数
    
    # 确保数量不小于最小单位
    if quantity < 10:
        quantity = 10
        
    return quantity


def on_tick(context, tick):
    """
    行情推送回调函数
    """
    symbol = tick['symbol']
    
    # 更新最新价格
    GRID_PARAMS[symbol]['last_price'] = tick['close']
    
    # 如果网格中心为空，用当前价格作为中心
    if GRID_PARAMS[symbol]['grid_center'] is None:
        GRID_PARAMS[symbol]['grid_center'] = tick['close']
    
    # 检查是否有订单成交
    check_filled_orders(context, symbol)


def check_filled_orders(context, symbol):
    """
    检查订单成交情况，及时补单
    """
    try:
        # 获取已成交的订单
        finished_orders = get_finished_orders(start_date=context.now.strftime('%Y-%m-%d'), 
                                            end_date=context.now.strftime('%Y-%m-%d'))
        
        for order in finished_orders:
            if order.symbol == symbol and order.status == 2:  # 已成交
                logger.info(f"订单已成交: {symbol} {order.side} {order.volume} @ {order.price}")
                
                # 根据成交方向补充相应订单
                if order.side == OrderSide_Buy:
                    # 买单成交后，可能需要补充更高价位的卖单或更低的买单
                    supplement_sell_order(context, symbol, order.price)
                elif order.side == OrderSide_Sell:
                    # 卖单成交后，可能需要补充更低价位的买单或更高的卖单
                    supplement_buy_order(context, symbol, order.price)
                    
    except Exception as e:
        logger.error(f"检查{symbol}成交订单失败: {e}")


def supplement_buy_order(context, symbol, filled_price):
    """
    补充买单
    """
    try:
        # 找到下一个应该下的买单价格
        buy_levels = GRID_PARAMS[symbol]['buy_levels']
        next_buy_price = None
        
        for price in sorted(buy_levels, reverse=True):
            if price < filled_price:
                next_buy_price = price
                break
        
        if next_buy_price:
            # 检查该价格是否已有买单
            current_orders = get_unfinished_orders()
            existing_orders = [o for o in current_orders if o.symbol == symbol and 
                              o.side == OrderSide_Buy and abs(o.price - next_buy_price) < 0.01]
            
            if not existing_orders:
                quantity = calculate_quantity(context, symbol, next_buy_price)
                if quantity > 0:
                    order_id = order_volume(
                        symbol=symbol,
                        volume=quantity,
                        side=OrderSide_Buy,
                        order_type=OrderType_Limit,
                        price=next_buy_price,
                        account=g.account
                    )
                    logger.info(f"补充买单: {symbol} {quantity}股 @ {next_buy_price}")
    except Exception as e:
        logger.error(f"补充{symbol}买单失败: {e}")


def supplement_sell_order(context, symbol, filled_price):
    """
    补充卖单
    """
    try:
        # 找到下一个应该下的卖单价格
        sell_levels = GRID_PARAMS[symbol]['sell_levels']
        next_sell_price = None
        
        for price in sorted(sell_levels):
            if price > filled_price:
                next_sell_price = price
                break
        
        if next_sell_price:
            # 检查该价格是否已有卖单
            current_orders = get_unfinished_orders()
            existing_orders = [o for o in current_orders if o.symbol == symbol and 
                              o.side == OrderSide_Sell and abs(o.price - next_sell_price) < 0.01]
            
            if not existing_orders:
                position = get_position(security=symbol, account=g.account)
                if position and position.volume > 0:
                    quantity = min(calculate_quantity(context, symbol, next_sell_price), position.volume_today)
                    if quantity > 0:
                        order_id = order_volume(
                            symbol=symbol,
                            volume=quantity,
                            side=OrderSide_Sell,
                            order_type=OrderType_Limit,
                            price=next_sell_price,
                            account=g.account
                        )
                        logger.info(f"补充卖单: {symbol} {quantity}股 @ {next_sell_price}")
    except Exception as e:
        logger.error(f"补充{symbol}卖单失败: {e}")


def on_bar(context, bars):
    """
    K线数据推送回调函数
    """
    pass


def on_order_status(context, status):
    """
    订单状态变化回调函数
    """
    symbol = status.symbol
    logger.info(f"订单状态更新: {symbol} {status.status} {status.volume_orign-volume_left} / {status.volume_orign}")
    
    # 当订单完全成交时，补充相应的订单
    if status.status == 2:  # 完全成交
        if status.side == OrderSide_Buy:
            supplement_sell_order(context, symbol, status.price)
        elif status.side == OrderSide_Sell:
            supplement_buy_order(context, symbol, status.price)


def on_execution_report(context, report):
    """
    成交通知回调函数
    """
    symbol = report.symbol
    logger.info(f"成交报告: {symbol} {report.side} {report.volume} @ {report.price}")
    
    # 根据成交情况调整网格中心
    if GRID_PARAMS.get(symbol):
        GRID_PARAMS[symbol]['grid_center'] = report.price


def on_backtest_finished(context, indicator):
    """
    回测结束回调函数
    """
    logger.info("回测结束")
    logger.info(f"收益指标: {indicator}")


def run():
    """
    运行策略主函数
    """
    # 注意：在实际掘金量化平台上运行时，以下参数会被平台自动处理
    # 这里仅用于本地测试目的
    
    # 设置策略ID和Token（需要替换为真实值）
    # set_token('YOUR_TOKEN_HERE')  # 替换为真实的Token
    
    # 运行策略
    run_strategy(
        # strategy_id='YOUR_STRATEGY_ID',  # 替换为真实的策略ID
        filename='main.py',
        mode=4,  # 实盘模式
        token='YOUR_TOKEN_HERE',  # 替换为真实的Token
        backtest_start_time='2023-01-01 09:00:00',
        backtest_end_time='2023-12-31 15:00:00',
        backtest_initial_cash=1000000,
        backtest_transaction_cost=0.0002,
        backtest_commission_rate=0.0001
    )


if __name__ == '__main__':
    run()
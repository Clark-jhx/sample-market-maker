import sys
from time import sleep
from market_maker.settings import settings
from market_maker.market_maker import OrderManager, XBt_to_XBT, logger
from market_maker.market_maker import MulOrderManager
from market_maker.utils import math


class MineOrderManager(OrderManager):

    def print_status(self):
        """Print the current MM status."""
        margin = self.exchange.get_margin()
        position = self.exchange.get_position()
        self.running_qty = self.exchange.get_delta()
        tickLog = self.exchange.get_instrument()['tickLog']  # 合约价值(1usd)
        self.start_XBt = margin["marginBalance"]

        self.logger.info("当前余额: %.6f" % XBt_to_XBT(self.start_XBt))  # 当前余额(小数点有6位)
        self.logger.info("目前仓位数量: %d" % self.running_qty)  # 目前仓位数量
        if settings.CHECK_POSITION_LIMITS:  # 仓位数量限制
            self.logger.info("仓位数量限制: %d/%d" % (settings.MIN_POSITION, settings.MAX_POSITION))
        # 仓位情况
        if position['currentQty'] != 0:
            self.logger.info("开仓价格: %.*f" % (tickLog, float(position['avgCostPrice'])))
            self.logger.info("开仓价格: %.*f" % (tickLog, float(position['avgEntryPrice'])))
        self.logger.info("Contracts Traded This Run: %d" % (self.running_qty - self.starting_qty))
        self.logger.info("Total Contract Delta: %.4f XBT" % self.exchange.calc_delta()['spot'])

    # 覆写父类方法
    def place_orders(self):
        # 每个账户下单的地方

        # 设置杠杆
        #self.exchange.isolate_margin(leverage=0) # 先设置成0
        self.exchange.isolate_margin(leverage=settings.LEVERAGE)

        buy_orders = []
        sell_orders = []
        if self.tag == settings.API_SECRETS[0]['tag']:
            # 账户1下单
            buy_orders.append({'ordType': 'Market', 'orderQty': settings.ORDER__SIZE, 'side': "Buy"})
            self.exchange.create_bulk_orders(buy_orders)
            pass
        if self.tag == settings.API_SECRETS[1]['tag']:
            # 账户2下单
            sell_orders.append({'ordType': 'Market', 'orderQty': settings.ORDER__SIZE, 'side': "Sell"})
            self.exchange.create_bulk_orders(sell_orders)
            pass
        pass

    # 放置止损止盈单
    def place_loss_win(self):
        # 还未成交的挂单
        existing_orders = self.exchange.get_orders()
        if len(existing_orders) > 0:
            # 存在未成交的订单，直接返回
            return

        buy_orders = []
        sell_orders = []
        # 当前持仓情况
        position = self.exchange.get_position()
        # 目前仓位数量 有正负
        self.running_qty = position['currentQty']
        # 开仓价格
        avgEntryPrice = position['avgEntryPrice']
        # 强平价格
        marginCallPrice = position['marginCallPrice']
        # 开仓价格 与 止盈价格 差距
        if (avgEntryPrice is None) or (marginCallPrice is None):
            return
        diff = abs(avgEntryPrice - marginCallPrice)

        if self.running_qty == 0:
            # 仓位为0直接返回
            return

        if self.running_qty > 0:
            # 多头止盈
            # tickSize 最小变动价格0.5，toNearest 取最靠近0.5的值(比如100.6，最靠近100.5)
            price = math.toNearest((avgEntryPrice + diff * 2), self.instrument['tickSize'])
            sell_orders.append({'price': price, 'orderQty': settings.ORDER__SIZE, 'side': "Sell"})
            self.exchange.create_bulk_orders(sell_orders)
            pass
        if self.running_qty < 0:
            # 空头止盈
            # tickSize 最小变动价格0.5，toNearest 取最靠近0.5的值(比如100.6，最靠近100.5)
            price = math.toNearest((avgEntryPrice - diff * 2), self.instrument['tickSize'])
            buy_orders.append({'price': price, 'orderQty': settings.ORDER__SIZE, 'side': "Buy"})
            self.exchange.create_bulk_orders(buy_orders)
            pass

class MultiCustomOrderManager(MulOrderManager):
    """A sample order manager for implementing your own custom strategy"""

    def __init__(self, key_secrets=None):
        # 先调用父类构造器，创建orderManager, 并传入秘钥
        super(MultiCustomOrderManager, self).__init__(key_secrets=key_secrets)
        # 账户1
        self.order_manager_1 = self.order_managers[settings.API_SECRETS[0]['tag']]
        # 账户2
        self.order_manager_2 = self.order_managers[settings.API_SECRETS[1]['tag']]

    def create_order_manager(self, tag=None, apiKey=None, apiSecret=None):
        return MineOrderManager(tag=tag, apiKey=apiKey, apiSecret=apiSecret)

    # 覆写父类方法
    def strategy(self):
        # 仓位数量
        currentQty_1 = self.order_manager_1.exchange.get_delta()
        currentQty_2 = self.order_manager_2.exchange.get_delta()
        if currentQty_1 == 0 and currentQty_2 == 0:
            self.order_manager_1.place_orders()
            self.order_manager_2.place_orders()
        else:
            # 放置止损止盈单
            self.order_manager_1.place_loss_win()
            self.order_manager_2.place_loss_win()
            pass


def run() -> None:
    # 读取密钥配置，list类型
    key_secrets = settings.API_SECRETS
    order_manager = MultiCustomOrderManager(key_secrets=key_secrets)
    # Try/except just keeps ctrl-c from printing an ugly stacktrace
    try:
        # 在开始主循环之前sleep一段时间，以便多个websocket建立连接
        sleep(settings.BEFORE_MAIN_LOOP)
        order_manager.run_loop()
    except (KeyboardInterrupt, SystemExit):
        sys.exit()

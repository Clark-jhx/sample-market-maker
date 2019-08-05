import sys
from time import sleep
from market_maker.settings import settings
from market_maker.market_maker import OrderManager, XBt_to_XBT, logger
from market_maker.market_maker import MulOrderManager


class MineOrderManager(OrderManager):

    def print_status(self):
        """Print the current MM status."""
        margin = self.exchange.get_margin()
        position = self.exchange.get_position()
        self.running_qty = self.exchange.get_delta()
        tickLog = self.exchange.get_instrument()['tickLog']  # 合约价值(1usd)
        self.start_XBt = margin["marginBalance"]

        logger.info("当前余额: %.6f" % XBt_to_XBT(self.start_XBt))  # 当前余额(小数点有6位)
        logger.info("目前仓位数量: %d" % self.running_qty)  # 目前仓位数量
        if settings.CHECK_POSITION_LIMITS:  # 仓位数量限制
            logger.info("仓位数量限制: %d/%d" % (settings.MIN_POSITION, settings.MAX_POSITION))
        # 仓位情况
        if position['currentQty'] != 0:
            logger.info("开仓价格: %.*f" % (tickLog, float(position['avgCostPrice'])))
            logger.info("开仓价格: %.*f" % (tickLog, float(position['avgEntryPrice'])))
        logger.info("Contracts Traded This Run: %d" % (self.running_qty - self.starting_qty))
        logger.info("Total Contract Delta: %.4f XBT" % self.exchange.calc_delta()['spot'])

    # 覆写父类方法
    def place_orders(self):
        # 每个账户下单的地方

        # 设置杠杆
        #self.exchange.isolate_margin(leverage=0) # 先设置成0
        self.exchange.isolate_margin(leverage=settings.LEVERAGE)

        buy_orders = []
        sell_orders = []
        if self.tag == '1':
            # 账户1下单
            buy_orders.append({'ordType': 'Market', 'orderQty': 1, 'side': "Buy"})
            self.exchange.create_bulk_orders(buy_orders)
            pass
        if self.tag == '2':
            # 账户2下单
            sell_orders.append({'ordType': 'Market', 'orderQty': 1, 'side': "Sell"})
            self.exchange.create_bulk_orders(sell_orders)
            pass
        pass

class MultiCustomOrderManager(MulOrderManager):
    """A sample order manager for implementing your own custom strategy"""

    def __init__(self, key_secrets=None):
        # 先调用父类构造器，创建orderManager, 并传入秘钥
        super(MultiCustomOrderManager, self).__init__(key_secrets=key_secrets)
        # 账户1
        self.order_manager_1 = self.order_managers['1']
        # 账户2
        self.order_manager_2 = self.order_managers['2']

    def create_order_manager(self, tag=None, apiKey=None, apiSecret=None):
        return MineOrderManager(tag=tag, apiKey=apiKey, apiSecret=apiSecret)

    # 覆写父类方法
    def strategy(self):
        # 仓位数量
        print('xx strategy')
        currentQty_1 = self.order_manager_1.exchange.get_delta()
        currentQty_2 = self.order_manager_2.exchange.get_delta()
        print(currentQty_1, currentQty_2)
        if currentQty_1 == 0 and currentQty_2 == 0:
            self.order_manager_1.place_orders()
            self.order_manager_2.place_orders()
        else:
            # todo 挂止盈单
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

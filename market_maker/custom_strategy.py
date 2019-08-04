import sys
from time import sleep
import threading
from market_maker.utils import math, constants
from market_maker.settings import settings
from market_maker.market_maker import OrderManager, logger


class ClarkOrderManager(OrderManager):

    def __init__(self):
        # 添加定时器
        self.timer = None
        # 是否打印status
        self.while_count = 0
        # 标记是否是第一次启动
        self.first_flag = True
        # 机器人开始前，保证金余额
        self.start_margin_balance = 0
        # 调用父类构造器
        OrderManager.__init__(self)

    def prepare_order(self, index):
        """Create an order object."""
        '''确定每一个订单(价格、数量)'''

        # 确定一个订单合约数
        # 固定值
        quantity = settings.ORDER_START_SIZE

        # 确定下单价格
        price = self.get_price_offset(index)

        # index负的为买，正的为卖
        buy_sell = 'Buy' if index < 0 else 'Sell'  # 注意大小写

        return {'price': price, 'orderQty': quantity, 'side': buy_sell}

    def get_price_offset(self, index):
        '''确定每一单下单价格'''

        # INTERVAL 订单间距，tickSize 最小变动价格0.5，toNearest 四舍五入
        # 这里直接使用start_position_mid(市场中间价格)
        return math.toNearest(self.start_position_mid + settings.INTERVAL * index, self.instrument['tickSize'])

    def place_orders(self):
        """Create order items for use in convergence."""

        buy_orders = []  # 列表
        sell_orders = []  # 列表
        # Create orders from the outside in. This is intentional - let's say the inner order gets taken;
        # then we match orders from the outside in, ensuring the fewest number of orders are amended and only
        # a new order is created in the inside. If we did it inside-out, all orders would be amended
        # down and a new order would be created at the outside.
        for i in reversed(range(1, settings.ORDER_PAIRS + 1)):  # 反转一个序列对象，将其元素从后向前颠倒构建成一个新的迭代器
            # 6 5 4 3 2 1
            if not self.long_position_limit_exceeded():
                buy_orders.append(self.prepare_order(-i))  # 买单 -6 -5 -4 -3 -2 -1
            if not self.short_position_limit_exceeded():
                sell_orders.append(self.prepare_order(i))  # 卖单 6 5 4 3 2 1

        return self.converge_orders(buy_orders, sell_orders)

    def converge_orders(self, buy_orders, sell_orders):
        """Converge the orders we currently have in the book with what we want to be in the book.
           This involves amending any open orders and creating new ones if any have filled completely.
           We start from the closest orders outward."""
        '''将已存在订单与将要放置的订单合并'''

        tickLog = self.exchange.get_instrument()['tickLog']  # 合约价值 1usd
        to_create = []

        buys_matched = 0
        sells_matched = 0

        while buys_matched < len(buy_orders):
            to_create.append(buy_orders[buys_matched])
            buys_matched += 1

        while sells_matched < len(sell_orders):
            to_create.append(sell_orders[sells_matched])
            sells_matched += 1

        if len(to_create) > 0:
            logger.info("Creating %d orders:" % (len(to_create)))
            for order in reversed(to_create):
                logger.info("%4s %d @ %.*f" % (order['side'], order['orderQty'], tickLog, order['price']))
            # 创建订单，发送请求
            self.exchange.create_bulk_orders(to_create)

    # 将 不停地放单操作 去掉
    def run_loop(self):
        while True:
            sys.stdout.write("-----\n")
            sys.stdout.flush()

            self.while_count += 1
            # 检查文件改变，重启
            self.check_file_change()
            sleep(settings.LOOP_INTERVAL)

            # This will restart on very short downtime, but if it's longer,
            # the MM will crash entirely as it is unable to connect to the WS on boot.
            # 如果ws断开连接，重连
            if not self.check_connection():
                logger.error("Realtime data connection unexpectedly closed, restarting.")
                self.restart()

            # 心跳
            self.sanity_check()  # Ensures health of mm - several cut-out points here
            # 状态，每隔一分钟打印一次
            if self.while_count >= settings.LOG_INTERVAL:
                self.print_status()  # Print skew, delta, etc
                self.while_count = 0
            # self.place_orders()  # Creates desired orders and converges to existing orders

    # 进行放单的地方
    def reset(self):
        if self.first_flag:
            # 第一次时，获取保证金余额，用于计算收益
            self.start_margin_balance = XBt_to_mXBT(self.exchange.get_margin()['marginBalance'])
        self.exchange.cancel_all_orders()  # 取消所有订单
        self.sanity_check()  # 心跳
        self.print_status()  # 打印状态
        self.start_timer()  # 启动定时器

        # Create orders and converge.
        self.place_orders()

    def start_timer(self):
        '''启动定时器'''
        self.timer = threading.Timer(settings.TIMER_INTERVAL, self.handle_timer)
        self.timer.start()

    def cancel_timer(self):
        '''取消定时器'''
        if self.timer is not None:
            self.timer.cancel()

    def handle_timer(self):
        '''定时器到时'''
        logger.info('place order again')
        self.reset()

    def print_status(self):
        """Print the current MM status."""

        # 保证金
        margin = self.exchange.get_margin()
        # 仓位信息
        position = self.exchange.get_position(settings.SYMBOL)
        # 对手合约仓位信息
        position_x = self.exchange.get_position(settings.SYMBOL_x)
        # 目前仓位数量
        self.running_qty = self.exchange.get_delta(settings.SYMBOL)
        # 对手合约目前仓位数量
        self.running_qty_x = self.exchange.get_delta(settings.SYMBOL_x)

        # 合约价值(1usd)
        tickLog = self.exchange.get_instrument()['tickLog']

        logger.info("  ")
        ### 保证金信息 ###
        # 当前余额(小数点有6位)，单位毫比特
        #logger.info("保证金余额:%.3f(mXBT) = 钱包余额:%.3f + 未实现盈亏:%.3f" % (XBt_to_mXBT(margin['marginBalance']), XBt_to_mXBT(margin['walletBalance']), XBt_to_mXBT(margin['unrealisedPnl'])))
        logger.info("保证金余额 = 钱包余额 + 未实现盈亏  单位(mXBT)")
        logger.info("%.3f     %.3f     %.3f" % (XBt_to_mXBT(margin['marginBalance']), XBt_to_mXBT(margin['walletBalance']), XBt_to_mXBT(margin['unrealisedPnl'])))
        logger.info("  ")
        #logger.info("可用余额:%.3f(mXBT) = 仓位保证金:%.3f + 委托保证金:%.3f" % (XBt_to_mXBT(margin['availableMargin']), XBt_to_mXBT(margin['maintMargin']), XBt_to_mXBT(margin['unrealisedPnl'])))
        logger.info("可用余额 = 仓位保证金 + 委托保证金  单位(mXBT)")
        logger.info("%.3f     %.3f     %.3f" % (XBt_to_mXBT(margin['availableMargin']), XBt_to_mXBT(margin['maintMargin']), XBt_to_mXBT(margin['unrealisedPnl'])))
        logger.info("  ")
        logger.info("百分之%.2f保证金已被使用 %.2f倍杠杆" % (margin['marginUsedPcnt'] * 100, margin['marginLeverage']))
        ### 仓位信息 ###
        #logger.info("合约  目前仓位数量  价值  开仓价格  标记价格  强平价格  保证金  未实现盈亏  已实现盈亏")
        logger.info("  ")
        logger.info('目前仓位数量: %d 美元' % position['currentQty'])
        logger.info('价值:         %.3f(mXBT)' % XBt_to_mXBT(position['markValue']))
        logger.info('开仓价格:     %s' % str(position['avgCostPrice']))
        logger.info('标记价格:     %s' % str(position['markPrice']))
        logger.info('强平价格:     %s' % str(position['marginCallPrice']))
        logger.info('保证金:       %s' % str(position['maintMargin']))
        logger.info('未实现盈亏:   %.3f (mXBT)' % XBt_to_mXBT(position['unrealisedGrossPnl']))
        logger.info('已实现盈亏:   %.3f' % position['realisedPnl'])

        ### 收益信息 ###
        logger.info("  ")
        logger.info("机器人运行以来已经买入多少(美元): %d" % (self.running_qty - self.starting_qty))  # 机器人运行以来已经买入多少(美元)
        #logger.info("Total Contract Delta: %.4f XBT" % self.exchange.calc_delta()['spot'])    # 总合约增量
        logger.info('实现盈亏:%.3f(mXBT)' % (self.start_margin_balance - XBt_to_mXBT(margin['marginBalance'])))  # 用账户保证金余额计算
        logger.info("  ")

    def get_ticker(self):
        '''最高买价，最低卖价，中间价'''
        ticker = self.exchange.get_ticker()  # 最新的市场买卖价格，从intrument中获得
        tickLog = self.exchange.get_instrument()['tickLog']  # 合约价值(1usd)

        # Midpoint, used for simpler order placement.
        self.start_position_mid = ticker["mid"]

        # log信息
        logger.info("%s Ticker: Buy: %.*f, Sell: %.*f, Mid: %.f" %
                    (self.instrument['symbol'], tickLog, ticker["buy"], tickLog, ticker["sell"], ticker["mid"]))
        return ticker


if __name__ == "__main__":
    logger.info('BitMEX Market Maker Version: %s\n' % constants.VERSION)  # 信息：软件版本

    om = ClarkOrderManager()
    # Try/except just keeps ctrl-c from printing an ugly stacktrace
    try:
        om.run_loop()
    except (KeyboardInterrupt, SystemExit):
        sys.exit()


# 程序入口
def run():
    logger.info('BitMEX Market Maker Version: %s\n' % constants.VERSION)  # 信息：软件版本

    om = ClarkOrderManager()
    # Try/except just keeps ctrl-c from printing an ugly stacktrace
    try:
        om.run_loop()
    except (KeyboardInterrupt, SystemExit):
        sys.exit()



# helper

# 聪 to 比特币
def XBt_to_XBT(XBt):
    return float(XBt) / constants.XBt_TO_XBT

# 聪 to 豪比特
def XBt_to_mXBT(XBt):
    return float(XBt) / constants.XBt_TO_mXBT
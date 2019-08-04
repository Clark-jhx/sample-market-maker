from os.path import join
import logging

# 合约类型
SYMBOL = "XBTUSD"
# 对手合约
SYMBOL_x = "XBTZ19"

# 指定你持有的合同，这些将在投资组合计算中使用。
CONTRACTS = [SYMBOL, SYMBOL_x]

# 每个机器人，这个标记要不行同，不然会互相影响订单
ORDERID_PREFIX = "mm_a_"

# 订单成交的百分比，阈值
limit = 0.1  # 10%

# 每一单数量(美元)
ORDER_START_SIZE = 20

# 订单对
ORDER_PAIRS = 5

# 连续订单之间的间隔(美元)
INTERVAL = 5

# 修改订单时使用，INTERVAL * 2
# RELIST_INTERVAL = INTERVAL * 2


# 网址
BASE_URL = "https://testnet.bitmex.com/api/v1/"  # 测试地址
# BASE_URL = "https://www.bitmex.com/api/v1/" # Once you're ready, uncomment this.

# 测试
API_KEY = "8niYvr0Xcxq-HqfFEiGBsISd"
API_SECRET = "3oJVgWKHVSJhmgWb4PHk7Fqgt_CoyievVsRmv1I0tugzXUgN"

# 实盘
# API_KEY = ""
# API_SECRET = ""

# 定时器间隔 单位秒
# 间隔多长时间重新下单
TIMER_INTERVAL = 60 * 5

# 主循环时间间隔，单位秒
LOOP_INTERVAL = 5

# log信息打印时间，单位秒，1分钟
LOG_INTERVAL = 12  # LOOP_INTERVAL * 12



########################################################################################################################
# Connection/Auth
# 连接/授权
########################################################################################################################

# api地址
# API URL.
# BASE_URL = "https://testnet.bitmex.com/api/v1/"  # 测试地址
# BASE_URL = "https://www.bitmex.com/api/v1/" # Once you're ready, uncomment this.

# 永久api key
# The BitMEX API requires permanent API keys. Go to https://testnet.bitmex.com/api/apiKeys to fill these out.
# API_KEY = ""
# API_SECRET = ""

########################################################################################################################
# Target
# 做市目标
########################################################################################################################

# Instrument to market make on BitMEX.
# SYMBOL = "XBTUSD"

########################################################################################################################
# Order Size & Spread
# 订单 大小&差价
########################################################################################################################

# How many pairs of buy/sell orders to keep open
# 挂所多少对 买/卖 单
# 6个买，6个卖
# ORDER_PAIRS = 6

# ORDER_START_SIZE will be the number of contracts submitted on level 1
# Number of contracts from level 1 to ORDER_PAIRS - 1 will follow the function
# [ORDER_START_SIZE + ORDER_STEP_SIZE (Level -1)]
# ORDER_START_SIZE = 100
ORDER_STEP_SIZE = 100

# Distance between successive orders, as a percentage (example: 0.005 for 0.5%)
# 连续订单之间的间距，百分比
# 订单之间的差价
# INTERVAL = 0.005

# Minimum spread to maintain, in percent, between asks & bids
# 最小差价
MIN_SPREAD = 0.01

# If True, market-maker will place orders just inside the existing spread and work the interval % outwards,
# rather than starting in the middle and killing potentially profitable spreads.
# 市场买价与卖价有较大价差时使用
MAINTAIN_SPREADS = True

# This number defines far much the price of an existing order can be from a desired order before it is amended.
# This is useful for avoiding unnecessary calls and maintaining your ratelimits.
#
# Further information:
# Each order is designed to be (INTERVAL*n)% away from the spread.
# If the spread changes and the order has moved outside its bound defined as
# abs((desired_order['price'] / order['price']) - 1) > settings.RELIST_INTERVAL)
# it will be resubmitted.
#
# 修改订单时会用到
# 0.01 == 1%
# RELIST_INTERVAL = 0.01


########################################################################################################################
# Trading Behavior
# 交易行为
########################################################################################################################

# Position limits - set to True to activate. Values are in contracts.
# If you exceed a position limit, the bot will log and stop quoting that side.
# 如果超过限制，机器人会停止那边的报价
CHECK_POSITION_LIMITS = False
MIN_POSITION = -10000
MAX_POSITION = 10000

# If True, will only send orders that rest in the book (ExecInst: ParticipateDoNotInitiate).
# Use to guarantee a maker rebate.用户保障制造商的回扣
# However -- orders that would have matched immediately will instead cancel, and you may end up with
# unexpected delta. Be careful. 但是立即匹配的订单被取消，可能发生意向不到的事
POST_ONLY = False

########################################################################################################################
# Misc Behavior, Technicals
# 杂项
########################################################################################################################

# If true, don't set up any orders, just say what we would do
# 如果为true，不设置任何订单，只是指明将在干啥
# DRY_RUN = True
DRY_RUN = False

# How often to re-check and replace orders. 经常检查和替换订单
# Generally, it's safe to make this short because we're fetching from websockets. But if too many
# order amend/replaces are done, you may hit a ratelimit. If so, email BitMEX if you feel you need a higher limit.
# 如果太多订单要修改/替换，可能会激活速率限制，向bitmex发邮件
# 主循环时间间隔，单位秒
# LOOP_INTERVAL = 5

# Wait times between orders / errors
# 出现错误等待时间
API_REST_INTERVAL = 1
API_ERROR_INTERVAL = 10
TIMEOUT = 7

# If we're doing a dry run, use these numbers for BTC balances
# 可能是账户没有钱，用这个吧
DRY_BTC = 50

# Available levels: logging.(DEBUG|INFO|WARN|ERROR)
# log 等级
LOG_LEVEL = logging.INFO

# To uniquely identify orders placed by this bot, the bot sends a ClOrdID (Client order ID) that is attached
# to each order so its source can be identified. This keeps the market maker from cancelling orders that are
# manually placed, or orders placed by another bot.
# 为了唯一标识机器人放置的订单，机器人会发送一个 订单id 标识每个订单，所以来源可以被识别。这样使得这个做市商不能取消手工放置的订单，或者订单被另一个机器人替换
#
# If you are running multiple bots on the same symbol, give them unique ORDERID_PREFIXes - otherwise they will
# cancel each others' orders.
# 如果运行多个机器人，并且这个标记相同，那个机器人之间或相互影响订单
# Max length is 13 characters.
# ORDERID_PREFIX = "mm_bitmex_"

# If any of these files (and this file) changes, reload the bot.
# 如下文件(和此文件)发生改变，会reload机器人
WATCHED_FILES = [join('market_maker', 'market_maker.py'), join('market_maker', 'bitmex.py'), 'settings.py']

########################################################################################################################
# BitMEX Portfolio
########################################################################################################################

# Specify the contracts that you hold. These will be used in portfolio calculations.
# 指定你持有的合同，这些将在投资组合计算中使用。
# CONTRACTS = ['XBTUSD']

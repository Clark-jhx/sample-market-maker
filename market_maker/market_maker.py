from __future__ import absolute_import
from time import sleep
import sys
from datetime import datetime
from os.path import getmtime
import random
import requests
import atexit
import signal
import logging

from market_maker import bitmex
from market_maker.settings import settings
from market_maker.utils import log, constants, errors, math

# Used for reloading the bot - saves modified times of key files
import os

watched_files_mtimes = [(f, getmtime(f)) for f in settings.WATCHED_FILES]

#
# Helpers
#
logger = log.setup_custom_logger('root')


# 交易接口
class ExchangeInterface:
    def __init__(self, dry_run=False, apiKey=None, apiSecret=None):
        self.dry_run = dry_run
        # 命令行中读取合约类型，没有的话，使用默认的
        if len(sys.argv) > 1:
            self.symbol = sys.argv[1]
        else:
            self.symbol = settings.SYMBOL
        self.logger = log.setup_custom_logger('exchange', logging.INFO)
        # api接口
        self.bitmex = bitmex.BitMEX(base_url=settings.BASE_URL, symbol=self.symbol,
                                    apiKey=apiKey, apiSecret=apiSecret,
                                    orderIDPrefix=settings.ORDERID_PREFIX, postOnly=settings.POST_ONLY,
                                    timeout=settings.TIMEOUT)

    # 取消指定订单
    def cancel_order(self, order):
        tickLog = self.get_instrument()['tickLog']
        self.logger.info("Canceling: %s %d @ %.*f" % (order['side'], order['orderQty'], tickLog, order['price']))
        while True:
            try:
                self.bitmex.cancel(order['orderID'])
                sleep(settings.API_REST_INTERVAL)
            except ValueError as e:
                self.logger.info(e)
                sleep(settings.API_ERROR_INTERVAL)
            else:
                break

    # 取消所有订单
    def cancel_all_orders(self):
        if self.dry_run:
            return

        self.logger.info("Resetting current position. Canceling all existing orders.")
        tickLog = self.get_instrument()['tickLog']

        # In certain cases, a WS update might not make it through before we call this.
        # For that reason, we grab via HTTP to ensure we grab them all.
        # http方式获得所有已存在订单
        orders = self.bitmex.http_open_orders()

        for order in orders:
            self.logger.info("Canceling: %s %d @ %.*f" % (order['side'], order['orderQty'], tickLog, order['price']))

        if len(orders):
            # 取消指定id的订单
            self.bitmex.cancel([order['orderID'] for order in orders])

        sleep(settings.API_REST_INTERVAL)

    # todo
    def get_portfolio(self):
        contracts = settings.CONTRACTS
        portfolio = {}
        for symbol in contracts:
            position = self.bitmex.position(symbol=symbol)
            instrument = self.bitmex.instrument(symbol=symbol)

            if instrument['isQuanto']:  # isQuanto:是否双币价
                future_type = "Quanto"
            elif instrument['isInverse']:  # isInverse:是否反向
                future_type = "Inverse"
            elif not instrument['isQuanto'] and not instrument['isInverse']:
                future_type = "Linear"
            else:
                raise NotImplementedError("Unknown future type; not quanto or inverse: %s" % instrument['symbol'])

            if instrument[
                'underlyingToSettleMultiplier'] is None:  # underlyingToSettleMultiplier:标的价值至结算价值的乘数(-100000000)
                multiplier = float(instrument['multiplier']) / float(
                    instrument['quoteToSettleMultiplier'])  # quoteToSettleMultiplier:计价价值至结算价值的乘数
            else:
                multiplier = float(instrument['multiplier']) / float(instrument['underlyingToSettleMultiplier'])

            portfolio[symbol] = {
                "currentQty": float(position['currentQty']),
                "futureType": future_type,
                "multiplier": multiplier,
                "markPrice": float(instrument['markPrice']),  # markPrice:标记价格
                "spot": float(instrument['indicativeSettlePrice'])
            }

        return portfolio

    def calc_delta(self):
        """Calculate currency delta for portfolio"""
        portfolio = self.get_portfolio()
        spot_delta = 0
        mark_delta = 0
        for symbol in portfolio:
            item = portfolio[symbol]
            if item['futureType'] == "Quanto":
                spot_delta += item['currentQty'] * item['multiplier'] * item['spot']
                mark_delta += item['currentQty'] * item['multiplier'] * item['markPrice']
            elif item['futureType'] == "Inverse":
                spot_delta += (item['multiplier'] / item['spot']) * item['currentQty']
                mark_delta += (item['multiplier'] / item['markPrice']) * item['currentQty']
            elif item['futureType'] == "Linear":
                spot_delta += item['multiplier'] * item['currentQty']
                mark_delta += item['multiplier'] * item['currentQty']
        basis_delta = mark_delta - spot_delta
        delta = {
            "spot": spot_delta,
            "mark_price": mark_delta,
            "basis": basis_delta
        }
        return delta

    # symbol合约类型，目前仓位数量(有正负之分)
    def get_delta(self, symbol=None):
        if symbol is None:
            symbol = self.symbol
        return self.get_position(symbol)['currentQty']

    # 根据网站insruments排序
    # "symbol": "XBTUSD", // 合约
    # "markPrice": 7256.78, // 标记价格
    # "lastPrice": 7262, // 最新成交价
    # "bidPrice": 7262, // 买价
    # "askPrice": 7264, // 卖价
    # "openValue": 1816825822500 // 未平仓合约价值，单位聪
    # "tickLog": 1, // 合约价值，1usd
    # "expiry": null, // 到期日期
    # "rootSymbol": "XBT", // 根符号
    # "state": "Open", // 状态
    # "typ": "FFWCSX", // 类型
    # "listing": "2016-05-04T12:00:00.000Z", // 挂牌，2016年5月4日下午8: 00:00
    # "front": "2016-05-04T12:00:00.000Z", // 即月，2016年5月4日下午8: 00:00
    # "expiry": null, // 到期日期
    # "settle": null, // 结算
    # "relistInterval": null, // 重新挂牌时间间隔
    # "inverseLeg": "", // 转换符号
    # "sellLeg": "", // 跨期的卖符号
    # "buyLeg": "", // 跨期的买符号
    # "optionStrikePcnt": null, // 无中文翻译
    # "optionStrikeRound": null, // 无中文翻译
    # "optionStrikePrice": null, // 行使价格
    # "positionCurrency": "USD", // 仓位货币
    # "underlying": "XBT", // 标的资产
    # "quoteCurrency": "USD", // 计价货币
    # "underlyingSymbol": "XBT=", // 标的符号
    # "reference": "BMEX", // 参考
    # "referenceSymbol": ".BXBT", // 参考代码
    # "calcInterval": null, // 计算价格
    # "publishInterval": null, // 发布间隔
    # "publishTime": null, // 发布时间
    # "maxOrderQty": 10000000, // 最大委托数量
    # "maxPrice": 1000000, // 最大委托价格
    # "lotSize": 1, // 最小合约数量
    # "tickSize": 0.5, // 最小价格变动
    # "multiplier": -100000000, // 乘数
    # "settlCurrency": "XBt", // 交割货币
    # "underlyingToPositionMultiplier": null, // 标的价值至仓位价值的乘数
    # "underlyingToSettleMultiplier": -100000000, // 标的价值至结算价值的乘数
    # "quoteToSettleMultiplier": null, // 计价价值至结算价值的乘数
    # "isQuanto": false, // 是否双币价
    # "isInverse": true, // 是否反向
    # "initMargin": 0.01, // 起始保证金，1.00 %
    # "maintMargin": 0.005, // 维持保证金，0.50 %
    # "riskLimit": 20000000000, // 风险限额，单位聪
    # "riskStep": 10000000000, // 风险限额递增值，单位聪
    # "limit": null, // 限价
    # xx(systemLossRecoveryEnabled) // 没有该字段，启用DPE
    # "deleverage": true, // 自动减仓
    # "makerFee": -0.00025, // 提取流动性费，-0.025 %
    # "takerFee": 0.00075, // 提取流动性佣金，0.075 %
    # "settlementFee": 0, // 计算费，0 %
    # "insuranceFee": 0, // 保险费0 %
    # "fundingBaseSymbol": ".XBTBON8H", // 又名InterestBaseSymbol, 基础货币利率符号
    # "fundingQuoteSymbol": ".USDBON8H", // 又名InterestQuoteSymbol, 计价货币利率符号
    # "fundingPremiumSymbol": ".XBTUSDPI8H", // 资金利率溢价符号
    # xx(nextFunding) // 下一个资金费率
    # "fundingInterval": "2000-01-01T08:00:00.000Z", // 资金费率收取间隔
    # "fundingRate": -0.002171, // 资金费率，-0.2171
    # "indicativeFundingRate": -0.000578, // 又名predicted Rate预测费率，-0.057 %
    # "rebalanceTimestamp": null, // 系统平衡时间
    # "rebalanceInterval": null, // 系统平衡时间间隔
    # "openingTimestamp": "2018-05-28T12:00:00.000Z", // 开盘时间，2018年5月28日下午10: 00:00
    # "closingTimestamp": "2018-05-28T14:00:00.000Z", // 收盘时间，2018年5月29日上午12: 00:00
    # "sessionInterval": "2000-01-01T02:00:00.000Z", // 间隔交易时间，每2小时
    # "prevClosePrice": 7222.44, // 前一个收盘价格
    # "limitDownPrice": null, // 价格下限
    # "limitUpPrice": null, // 价格上限
    # "bankruptLimitDownPrice": null, // 破产最低限价
    # "bankruptLimitUpPrice": null, // 破产最高限价
    # "prevTotalVolume": 42350732841, // 迁移时间段的总交易量，
    # "totalVolume": 42368081431, // 总交易量
    # xx(sessionvolume) // 时段交易量
    # "volume24h": 199011001, // 24小时交易量
    # "prevTotalTurnover": 586666402008409, // 前一时间段的总交易量，单位聪
    # "totalTurnover": 586905752314796, // 交易额，单位聪
    # "turnover": 239350306387, // 交易额，单位聪
    # "turnover24h": 2738167830334, // 24
    # 小时营业额，单位聪
    # "prevPrice24h": 7262.5, // 24小时前的价格
    # "vwap": 7268.4983, // 交易量加权平均价格
    # "highPrice": 7420, // 最高价格
    # "lowPrice": 7174.5, // 最低价格
    # xx(lastprice) // 最新成交价
    # "lastPriceProtected": 7262, // 受保护的最新成交价格
    # "lastTickDirection": "ZeroMinusTick", // 最新价格升跌方向
    # "lastChangePcnt": -0.0001, // 最新价格变化 %，0.01 %
    # "bidPrice": 7262, // 买价
    # "midPrice": 7263, // 中间价格
    # "askPrice": 7264, // 卖价
    # "impactBidPrice": 7261.1095, // 深度加权买价
    # "impactMidPrice": 7264.25, // 深度加权中间价
    # "impactAskPrice": 7267.4419, // 深度加权卖价
    # "hasLiquidity": true, // 是否又流动性
    # "openInterest": 131845125, // 为平仓合约数量
    # "fairMethod": "FundingRate", // 又名fairBasisCalculation合约基差计算公式
    # "fairBasisRate": -2.3772450000000003, // 合约基差率，-237 %
    # "fairBasis": -12.76, // 合理基差
    # "fairPrice": 7256.78, // 合理价格
    # "markMethod": "FairPrice", // 标记方法
    # "markPrice": 7256.78, // 标记价格
    # "indicativeSettlePrice": 7269.54, // 预计结算价格
    # "settledPrice": null, // 结算价格
    #
    # "timestamp": "2018-05-28T13:32:01.056Z", // 网络请求时的时间戳
    #
    # 以下几个是返回值中，不知道干什么的
    # "fundingTimestamp": "2018-05-28T20:00:00.000Z",
    # "indicativeTaxRate": 0,
    # "optionUnderlyingPrice": null,
    # "taxed": true,
    # "capped": false,
    # "volume": 17348590,
    # "optionMultiplier": null,
    def get_instrument(self, symbol=None):
        '''返回字典类型'''
        if symbol is None:
            symbol = self.symbol
        return self.bitmex.instrument(symbol)

    # 'withdrawableMargin': 53852623, // 可提现余额
    # 'prevRealisedPnl': 9154,
    # 'confirmedDebit': 0,
    # 'account': 22098,
    # 'marginUsedPcnt': 0.1993, // 19.93 % 的保证金已被使用
    # 'marginLeverage': 0.5943395237567431, // 0.59倍杠杆
    # 'syntheticMargin': 0,
    # 'action': '',
    # 'maintMargin': 13406912, // 仓位保证金，单位聪
    # 'grossLastValue': 39975000, // 总仓位价值 ，单位聪
    # 'grossComm': 29932,
    # 'sessionMargin': 0,
    # 'taxableMargin': 0,
    # 'state': '',
    # 'riskLimit': 1000000000000,   // 风险限额，单位聪
    # 'availableMargin': 53852623, // 可用余额，单位聪
    # 'initMargin': 0,
    # 'grossMarkValue': 39975000, // 总仓位价值 ，单位聪
    # 'grossOpenCost': 0,
    # 'excessMarginPcnt': 1,
    # 'amount': 67226467,
    # 'riskValue': 39975000, // 总仓位价值 ，单位聪
    # 'unrealisedProfit': 0,
    # 'walletBalance': 67196535, // 钱包余额，单位聪
    # 'marginBalance': 67259535, // 保证金余额，单位聪
    # 'marginBalancePcnt': 1,
    # 'excessMargin': 53852623,
    # 'varMargin': 0,
    # 'commission': None,
    # 'prevUnrealisedPnl': 0,
    # 'grossExecCost': 39912000,
    # 'currency': 'XBt', // 货币
    # 'unrealisedPnl': 63000, // 未实现盈亏，单位聪
    # 'targetExcessMargin': 0,
    # 'grossOpenPremium': 0,
    # 'timestamp': '2018-05-30T13:11:25.460Z', // 获取该信息的时间戳
    # 'indicativeTax': 0,
    # 'pendingCredit': 0,
    # 'realisedPnl': -29932, // 已实现盈亏
    # 'pendingDebit': 0,
    # 'prevState': ''
    def get_margin(self):
        '''保证金'''
        '''返回字典类型'''
        if self.dry_run:
            return {'marginBalance': float(settings.DRY_BTC), 'availableFunds': float(settings.DRY_BTC)}
        return self.bitmex.funds()

    # [
    #     {
    #         'ordStatus': 'New',
    #         'displayQty': None,
    #         'transactTime': '2018-05-31T07:57:26.719Z', // 办理的时间
    #         'workingIndicator': True,
    #         'currency': 'USD', // 货币
    #         'simpleCumQty': 0,
    #         'simpleLeavesQty': 0.0684,
    #         'clOrdLinkID': '',
    #         'execInst': '',
    #         'symbol': 'XBTUSD', // 合约类型
    #         'contingencyType': '',
    #         'orderQty': 456, // 订单数量
    #         'account': 22098,
    #         'triggered': '',
    #         'settlCurrency': 'XBt', // 结算货币
    #         'ordType': 'Limit', // 订单类型，限价单
    #         'simpleOrderQty': None,
    #         'timestamp': '2018-05-31T07:57:26.719Z', // 时间戳
    #         'ordRejReason': '',
    #         'cumQty': 0,
    #         'timeInForce': 'GoodTillCancel',
    #         'multiLegReportingType': 'SingleSecurity',
    #         'text': 'Submitted via API.', //
    #         'price': 6666, // 下单价格
    #         'clOrdID': 'mm_bitmex_P2d/1RG6SGOmQEm5XAr8rw', // 标记的id
    #         'exDestination': 'XBME',
    #         'side': 'Buy', // 买单还是卖单
    #         'pegOffsetValue': None,
    #         'leavesQty': 456,
    #         'pegPriceType': '',
    #         'stopPx': None,
    #         'avgPx': None,
    #         'orderID': '652b61de-a051-e846-eb4d-9a12dbb12a69' // 订单id
    #     }, {
    #         ...
    #         ...
    #     }
    # ]
    def get_orders(self):
        '''获取还没成交的委托'''
        '''顺序是 买单-6 -5 -4 -3 -2 -1  卖单6 5 4 3 2 1'''
        '''返回列表，列表里每个order是一个字典'''
        if self.dry_run:
            return []
        return self.bitmex.open_orders()

    def get_highest_buy(self):
        '''已存在订单(未成交委托)，买单中的最高买价'''
        buys = [o for o in self.get_orders() if o['side'] == 'Buy']
        if not len(buys):
            return {'price': -2 ** 32}
        highest_buy = max(buys or [], key=lambda o: o['price'])
        return highest_buy if highest_buy else {'price': -2 ** 32}

    def get_lowest_sell(self):
        '''已存在订单(未成交委托)，卖单中的最低卖价'''
        sells = [o for o in self.get_orders() if o['side'] == 'Sell']
        if not len(sells):
            return {'price': 2 ** 32}
        lowest_sell = min(sells or [], key=lambda o: o['price'])
        return lowest_sell if lowest_sell else {'price': 2 ** 32}  # ought to be enough for anyone

    # 'execBuyQty': 6590,
    # 'markPrice': 7539.68,               // 标记价格
    # 'unrealisedPnlPcnt': -0.0009,
    # 'posComm': 73530,
    # 'execQty': 5678,
    # 'currentCost': -75219570,
    # 'simpleQty': 0.7524,
    # 'openingComm': 0,
    # 'currency': 'XBt',
    # 'avgEntryPrice': 7546.5,           // 开仓价格
    # 'riskValue': 75307314,
    # 'sessionMargin': 0,
    # 'deleveragePercentile': 1,
    # 'posInit': 22799751,
    # 'initMargin': 0,
    # 'posMaint': 461163,
    # 'posAllowance': 0,
    # 'crossMargin': False,
    # 'account': 22098,
    # 'execSellQty': 912,
    # 'homeNotional': 0.75307314,
    # 'foreignNotional': -5678,           // 仓位价值，美元
    # 'markValue': -75307314,             // 仓位价值，单位聪，
    # 'rebalancedPnl': 37739,
    # 'taxableMargin': 0,
    # 'indicativeTaxRate': 0,
    # 'execBuyCost': 87319074,
    # 'openOrderBuyQty': 0,
    # 'grossOpenPremium': 0,
    # 'prevUnrealisedPnl': 0,
    # 'currentQty': 5678,                // 目前仓位数量，有正负之分，负的就是做空的
    # 'openingQty': 0,
    # 'maintMarginReq': 0.005,           // 维持保证金要求 0.5 %
    # 'openOrderSellCost': 0,
    # 'posLoss': 0,
    # 'taxBase': 0,
    # 'execSellCost': 12099504,
    # 'posMargin': 22873281,
    # 'currentComm': 74560,
    # 'openOrderBuyPremium': 0,
    # 'commission': 0.00075,
    # 'quoteCurrency': 'USD',
    # 'lastValue': -75307314,
    # 'symbol': 'XBTUSD', // 合约类型
    # 'indicativeTax': 0,
    # 'openingCost': 0,
    # 'openOrderSellQty': 0,
    # 'realisedCost': 19608,
    # 'unrealisedTax': 0,
    # 'grossOpenCost': 0,
    # 'timestamp': '2018-05-31T13:55:05.170Z',
    # 'posCost': -75239178,
    # 'bankruptPrice': 5792,            // 破产价格(todo)
    # 'execComm': 74560,
    # 'realisedPnl': -94168,
    # 'underlying': 'XBT',             // 标的资产
    # 'posCost2': -75239178,
    # 'posCross': 0,
    # 'simplePnlPcnt': -0.0009,
    # 'openOrderBuyCost': 0,
    # 'openOrderSellPremium': 0,
    # 'marginCallPrice': 5815,         // 强平价格
    # 'targetExcessMargin': 0,
    # 'varMargin': 0,
    # 'initMarginReq': 0.30303030303030304,
    # 'breakEvenPrice': 7552.5,
    # 'avgCostPrice': 7546.5,         // 开仓价格
    # 'execCost': -75219570,
    # 'isOpen': True,
    # 'maintMargin': 22805145,
    # 'unrealisedPnl': -68136,
    # 'leverage': 3.3,               // 杠杆
    # 'realisedTax': 0,
    # 'simplePnl': -5,
    # 'grossExecCost': 75234857,
    # 'simpleCost': 5678,
    # 'posState': '',
    # 'prevRealisedPnl': -13633,
    # 'riskLimit': 20000000000,     // 风险限额，单位聪
    # 'lastPrice': 7539.68,         // 最新价格 = 标记价格
    # 'prevClosePrice': 7537.71,
    # 'unrealisedGrossPnl': -68136, // 未平仓合约 未实现盈亏，单位聪，负数表示亏
    # 'realisedGrossPnl': -19608,        // 好像是 已实现盈亏(todo)
    # 'openingTimestamp': '2018-05-31T12:00:00.000Z',
    # 'unrealisedCost': -75239178,
    # 'liquidationPrice': 5815,
    # 'currentTimestamp': '2018-05-31T13:55:05.170Z',
    # 'unrealisedRoePcnt': -0.003,
    # 'longBankrupt': 0,
    # 'shortBankrupt': 0,
    # 'simpleValue': 5673
    def get_position(self, symbol=None):
        '''仓位的更新'''
        '''返回字典类型'''
        if symbol is None:
            symbol = self.symbol
        return self.bitmex.position(symbol)

    # 'last': 7486.0,  // 最新成交价
    # 'sell': 7476.5,  // 卖价
    # 'buy': 7473.5,   // 买价
    # 'mid': 7475.0,   // 中间价格
    def get_ticker(self, symbol=None):
        '''最新的市场买卖价格，从intrument中获得'''
        '''返回字典类型'''
        if symbol is None:
            symbol = self.symbol
        return self.bitmex.ticker_data(symbol)

    # ws是否连接中
    def is_open(self):
        """Check that websockets are still open."""
        return not self.bitmex.ws.exited

    # 检查symbol类型的合约目前是否可以交易
    # 无返回值，不可以交易，直接抛出异常
    def check_market_open(self):
        instrument = self.get_instrument()
        if instrument["state"] != "Open" and instrument["state"] != "Closed":  # state:合约状态
            raise errors.MarketClosedError("The instrument %s is not open. State: %s" %
                                           (self.symbol, instrument["state"]))

    # 委托列表是否根据就没有委托
    # 无返回值，为空，直接抛出异常
    def check_if_orderbook_empty(self):
        """This function checks whether the order book is empty"""
        instrument = self.get_instrument()
        if instrument['midPrice'] is None:  # midPrice:中间价格
            raise errors.MarketEmptyError("Orderbook is empty, cannot quote")

    # 修改订单
    def amend_bulk_orders(self, orders):
        if self.dry_run:
            return orders
        return self.bitmex.amend_bulk_orders(orders)

    # 创建订单
    def create_bulk_orders(self, orders):
        if self.dry_run:
            return orders
        return self.bitmex.create_bulk_orders(orders)

    # 取消订单
    def cancel_bulk_orders(self, orders):
        if self.dry_run:
            return orders
        return self.bitmex.cancel([order['orderID'] for order in orders])

    # 设置杠杆
    def isolate_margin(self, leverage, symbol=None):
        if symbol is None:
            symbol = self.symbol
        self.bitmex.isolate_margin(symbol=symbol, leverage=leverage)


class OrderManager:
    def __init__(self, tag=None, apiKey=None, apiSecret=None):
        # 用于标记是哪个账户
        self.tag = tag
        # 交易所接口
        self.exchange = ExchangeInterface(settings.DRY_RUN, apiKey=apiKey, apiSecret=apiSecret)
        # Once exchange is created, register exit handler that will always cancel orders
        # on any error.
        # 注册系统退出(发生错误时)回调，会取消订单
        atexit.register(self.exit)
        signal.signal(signal.SIGTERM, self.exit)  # todo
        self.logger = log.setup_custom_logger(self.tag, logging.INFO)

        self.logger.info("Using symbol %s." % self.exchange.symbol)

        if settings.DRY_RUN:
            self.logger.info("Initializing dry run. Orders printed below represent what would be posted to BitMEX.")
        else:
            self.logger.info("Order Manager initializing, connecting to BitMEX. Live run: executing real trades.")

        self.start_time = datetime.now()
        self.instrument = self.exchange.get_instrument()
        self.starting_qty = self.exchange.get_delta()
        self.running_qty = self.starting_qty
        # 首先会取消所有订单，打印状态
        self.reset()

    # reset
    def reset(self):
        self.exchange.cancel_all_orders()  # 取消所有订单
        self.sanity_check()  # 心跳
        self.print_status()  # 打印状态

        # Create orders and converge.
        # self.place_orders() # 一开始不放置订单，策略中开单

    def print_status(self):
        """Print the current MM status."""

        margin = self.exchange.get_margin()
        position = self.exchange.get_position()
        self.running_qty = self.exchange.get_delta()
        tickLog = self.exchange.get_instrument()['tickLog']  # 合约价值(1usd)
        self.start_XBt = margin["marginBalance"]

        self.logger.info("Current XBT Balance: %.6f" % XBt_to_XBT(self.start_XBt))  # 当前余额(小数点有6位)
        self.logger.info("Current Contract Position: %d" % self.running_qty)  # 目前仓位数量
        if settings.CHECK_POSITION_LIMITS:  # 仓位数量限制
            self.logger.info("Position limits: %d/%d" % (settings.MIN_POSITION, settings.MAX_POSITION))
        # 仓位情况
        if position['currentQty'] != 0:
            self.logger.info("Avg Cost Price: %.*f" % (tickLog, float(position['avgCostPrice'])))
            self.logger.info("Avg Entry Price: %.*f" % (tickLog, float(position['avgEntryPrice'])))
        self.logger.info("Contracts Traded This Run: %d" % (self.running_qty - self.starting_qty))
        self.logger.info("Total Contract Delta: %.4f XBT" % self.exchange.calc_delta()['spot'])

    def get_ticker(self):
        '''返回策略的开仓价格，最高买价，最低卖价'''
        ticker = self.exchange.get_ticker()  # 最新的市场买卖价格，从intrument中获得
        tickLog = self.exchange.get_instrument()['tickLog']  # 合约价值(1usd)

        # Set up our buy & sell positions as the smallest possible unit above and below the current spread
        # and we'll work out from there. That way we always have the best price but we don't kill wide
        # and potentially profitable spreads.
        self.start_position_buy = ticker["buy"] + self.instrument['tickSize']  # tickSize:最小价格变动
        self.start_position_sell = ticker["sell"] - self.instrument['tickSize']

        # If we're maintaining spreads and we already have orders in place,
        # make sure they're not ours. If they are, we need to adjust, otherwise we'll
        # just work the orders inward until they collide.
        # 已经存在为成交委托
        if settings.MAINTAIN_SPREADS:
            if ticker['buy'] == self.exchange.get_highest_buy()['price']:
                self.start_position_buy = ticker["buy"]
            if ticker['sell'] == self.exchange.get_lowest_sell()['price']:
                self.start_position_sell = ticker["sell"]

        # Back off if our spread is too small.
        # 如果(卖价-买价)/买价<1%  买卖价格价差
        if self.start_position_buy * (1.00 + settings.MIN_SPREAD) > self.start_position_sell:  # MIN_SPREAD=0.01
            self.start_position_buy *= (1.00 - (settings.MIN_SPREAD / 2))   # 买价降低一些
            self.start_position_sell *= (1.00 + (settings.MIN_SPREAD / 2))  # 卖价提高一些

        # Midpoint, used for simpler order placement.
        self.start_position_mid = ticker["mid"]
        # log信息
        self.logger.info(
            "%s Ticker: Buy: %.*f, Sell: %.*f" %
            (self.instrument['symbol'], tickLog, ticker["buy"], tickLog, ticker["sell"])
        )
        self.logger.info('Start Positions: Buy: %.*f, Sell: %.*f, Mid: %.*f' %
                    (tickLog, self.start_position_buy, tickLog, self.start_position_sell,
                     tickLog, self.start_position_mid))
        return ticker

    def get_price_offset(self, index):
        '''确定每一单下单价格'''
        """Given an index (1, -1, 2, -2, etc.) return the price for that side of the book.
           Negative is a buy, positive is a sell."""
        # Maintain existing spreads for max profit
        if settings.MAINTAIN_SPREADS:
            start_position = self.start_position_buy if index < 0 else self.start_position_sell
            # First positions (index 1, -1) should start right at start_position, others should branch from there
            index = index + 1 if index < 0 else index - 1
        else:
            # Offset mode: ticker comes from a reference exchange and we define an offset.
            start_position = self.start_position_buy if index < 0 else self.start_position_sell

            # If we're attempting to sell, but our sell price is actually lower than the buy,
            # move over to the sell side.卖出时，卖出价格低于买入价格，买入价格高于卖出价格
            if index > 0 and start_position < self.start_position_buy:
                start_position = self.start_position_sell
            # Same for buys.
            if index < 0 and start_position > self.start_position_sell:
                start_position = self.start_position_buy

        # INTERVAL 0.005，tickSize 最小变动价格0.5，toNearest 取最靠近0.5的值(比如100.6，最靠近100.5)
        return math.toNearest(start_position * (1 + settings.INTERVAL) ** index, self.instrument['tickSize'])

    ###
    # Orders
    ###

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

    def prepare_order(self, index):
        """Create an order object."""
        '''确定每一个订单(价格、数量)'''

        # 确定一个订单合约数
        if settings.RANDOM_ORDER_SIZE is True:
            quantity = random.randint(settings.MIN_ORDER_SIZE, settings.MAX_ORDER_SIZE)
        else:
            quantity = settings.ORDER_START_SIZE + ((abs(index) - 1) * settings.ORDER_STEP_SIZE)  # 100 + ( x * 100)

        # 确定下单价格
        price = self.get_price_offset(index)

        return {'price': price, 'orderQty': quantity, 'side': "Buy" if index < 0 else "Sell"}  # 字典

    def converge_orders(self, buy_orders, sell_orders):
        """Converge the orders we currently have in the book with what we want to be in the book.
           This involves amending any open orders and creating new ones if any have filled completely.
           We start from the closest orders outward."""
        '''将已存在订单与将要放置的订单合并'''

        tickLog = self.exchange.get_instrument()['tickLog']  # 合约价值 1usd
        to_amend = []
        to_create = []
        to_cancel = []
        buys_matched = 0
        sells_matched = 0
        # 已经存在的订单
        existing_orders = self.exchange.get_orders()

        # Check all existing orders and match them up with what we want to place.
        # If there's an open one, we might be able to amend it to fit what we want.
        # 把所有已有的订单与将要放置的订单进行比较，可能需要修改已存在的订单
        for order in existing_orders:
            try:
                if order['side'] == 'Buy':
                    desired_order = buy_orders[buys_matched]
                    buys_matched += 1
                else:
                    desired_order = sell_orders[sells_matched]
                    sells_matched += 1

                # Found an existing order. Do we need to amend it?
                # 判断已存在订单是否需要修改
                if desired_order['orderQty'] != order['leavesQty'] or (  # 数量不同
                        # If price has changed, and the change is more than our RELIST_INTERVAL, amend.
                        desired_order['price'] != order['price'] and  # 价格不同并且插值超过，预定价差
                        abs((desired_order['price'] / order['price']) - 1) > settings.RELIST_INTERVAL):
                    to_amend.append(  # 修改订单
                        {'orderID': order['orderID'], 'orderQty': order['cumQty'] + desired_order['orderQty'],  # todo cumQty 推测是还未成交数量
                         'price': desired_order['price'], 'side': order['side']})
            except IndexError:
                # Will throw if there isn't a desired order to match. In that case, cancel it.
                # 如果已存的订单没有和将要放置的订单匹配，就取消这个已存的订单(已存在订单数超过要放的订单数时，会把多余的已存在订单取消掉)
                to_cancel.append(order)

        # 补齐已成交的买单(因为价格变动，已经成交了)
        while buys_matched < len(buy_orders):
            to_create.append(buy_orders[buys_matched])
            buys_matched += 1

        # 补齐已成交的卖单(因为价格变动，已经成交了)
        while sells_matched < len(sell_orders):
            to_create.append(sell_orders[sells_matched])
            sells_matched += 1

        if len(to_amend) > 0:
            # 打印修改订单信息
            for amended_order in reversed(to_amend):
                reference_order = [o for o in existing_orders if o['orderID'] == amended_order['orderID']][0]
                self.logger.info("Amending %4s: %d @ %.*f to %d @ %.*f (%+.*f)" % (amended_order['side'],
                    reference_order['leavesQty'], tickLog, reference_order['price'],
                    (amended_order['orderQty'] - reference_order['cumQty']), tickLog, amended_order['price'],
                    tickLog, (amended_order['price'] - reference_order['price'])
                ))
            # This can fail if an order has closed in the time we were processing.
            # The API will send us `invalid ordStatus`, which means that the order's status (Filled/Canceled)
            # made it not amendable.
            # If that happens, we need to catch it and re-tick.
            try:
                # 修改订单，发送请求
                self.exchange.amend_bulk_orders(to_amend)
            except requests.exceptions.HTTPError as e:
                errorObj = e.response.json()
                if errorObj['error']['message'] == 'Invalid ordStatus':
                    self.logger.warn("Amending failed. Waiting for order data to converge and retrying.")
                    sleep(0.5)
                    return self.place_orders()
                else:
                    self.logger.error("Unknown error on amend: %s. Exiting" % errorObj)
                    sys.exit(1)

        if len(to_create) > 0:
            self.logger.info("Creating %d orders:" % (len(to_create)))
            for order in reversed(to_create):
                self.logger.info("%4s %d @ %.*f" % (order['side'], order['orderQty'], tickLog, order['price']))
            # 创建订单，发送请求
            self.exchange.create_bulk_orders(to_create)

        # Could happen if we exceed a delta limit
        if len(to_cancel) > 0:
            self.logger.info("Canceling %d orders:" % (len(to_cancel)))
            for order in reversed(to_cancel):
                self.logger.info("%4s %d @ %.*f" % (order['side'], order['leavesQty'], tickLog, order['price']))
            # 取消订单，发送请求
            self.exchange.cancel_bulk_orders(to_cancel)

    ###
    # Position Limits
    ###

    # 仓位数量限制
    def short_position_limit_exceeded(self):
        """Returns True if the short position limit is exceeded"""
        if not settings.CHECK_POSITION_LIMITS:
            return False
        position = self.exchange.get_delta()
        return position <= settings.MIN_POSITION

    # 仓位数量限制
    def long_position_limit_exceeded(self):
        """Returns True if the long position limit is exceeded"""
        if not settings.CHECK_POSITION_LIMITS:
            return False
        position = self.exchange.get_delta()
        return position >= settings.MAX_POSITION

    ###
    # Sanity
    # 心跳
    ##

    def sanity_check(self):
        """Perform checks before placing orders."""

        # Check if OB is empty - if so, can't quote.
        # 委托列表为空，不进行报价
        self.exchange.check_if_orderbook_empty()

        # Ensure market is still open.
        # 检查symbol类型的合约目前是否可以交易
        self.exchange.check_market_open()

        # Get ticker, which sets price offsets and prints some debugging info.
        # 获取市场最新卖/买价格、策略的买/卖价格
        ticker = self.get_ticker()

        # Sanity check:
        if self.get_price_offset(-1) >= ticker["sell"] or self.get_price_offset(1) <= ticker["buy"]:
            self.logger.error("Buy: %s, Sell: %s" % (self.start_position_buy, self.start_position_sell))
            self.logger.error("First buy position: %s\nBitMEX Best Ask: %s\nFirst sell position: %s\nBitMEX Best Bid: %s" %
                         (self.get_price_offset(-1), ticker["sell"], self.get_price_offset(1), ticker["buy"]))
            self.logger.error("Sanity check failed, exchange data is inconsistent")
            self.exit()

        # Messaging if the position limits are reached
        if self.long_position_limit_exceeded():
            self.logger.info("Long delta limit exceeded")
            self.logger.info("Current Position: %.f, Maximum Position: %.f" %
                        (self.exchange.get_delta(), settings.MAX_POSITION))

        if self.short_position_limit_exceeded():
            self.logger.info("Short delta limit exceeded")
            self.logger.info("Current Position: %.f, Minimum Position: %.f" %
                        (self.exchange.get_delta(), settings.MIN_POSITION))

    ###
    # Running
    ###

    def check_file_change(self):
        """Restart if any files we're watching have changed."""
        for f, mtime in watched_files_mtimes:
            if getmtime(f) > mtime:
                self.restart()

    def check_connection(self):
        """Ensure the WS connections are still open."""
        return self.exchange.is_open()

    # 退出
    def exit(self):
        self.logger.info("Shutting down. All open orders will be cancelled.")
        try:
            # 取消所有订单
            # self.exchange.cancel_all_orders() # 系统推出时，不取消未成交订单

            # 断开ws连接
            self.exchange.bitmex.exit()
        except errors.AuthenticationError as e:
            self.logger.info("Was not authenticated; could not cancel orders.")
        except Exception as e:
            self.logger.info("Unable to cancel orders: %s" % e)

        sys.exit()

    def run_loop(self):
        while True:
            sys.stdout.write("-----\n")
            sys.stdout.flush()

            # 检查文件改变，重启
            self.check_file_change()
            sleep(settings.LOOP_INTERVAL)

            # This will restart on very short downtime, but if it's longer,
            # the MM will crash entirely as it is unable to connect to the WS on boot.
            # 如果ws断开连接，重连
            if not self.check_connection():
                self.logger.error("Realtime data connection unexpectedly closed, restarting.")
                self.restart()

            self.sanity_check()  # Ensures health of mm - several cut-out points here
            self.print_status()  # Print skew, delta, etc
            self.place_orders()  # Creates desired orders and converges to existing orders

    def restart(self):
        self.logger.info("Restarting the market maker...")
        os.execv(sys.executable, [sys.executable] + sys.argv)


class MulOrderManager:
    def __init__(self, key_secrets=None):
        self.logger = log.setup_custom_logger('multi-manager', logging.INFO)
        self.key_secrets = key_secrets
        self.order_managers = {}
        for key_secret in self.key_secrets:
            order_manager = self.create_order_manager(tag=key_secret['tag'], apiKey=key_secret['apiKey'], apiSecret=key_secret['apiSecret'])
            self.order_managers.update({key_secret['tag']: order_manager})
        pass

    # 子类创建自己的orderManager
    def create_order_manager(self, tag=None, apiKey=None, apiSecret=None):
        return OrderManager(tag=tag, apiKey=apiKey, apiSecret=apiSecret)

    def strategy(self):
        # 具体的多账户策略，子类实现
        pass

    def run_loop(self):
        while True:
            sys.stdout.write("-----\n")
            sys.stdout.flush()

            for tag, order_manager in self.order_managers.items():
                # 检查文件改变，重启
                order_manager.check_file_change()
                # This will restart on very short downtime, but if it's longer,
                # the MM will crash entirely as it is unable to connect to the WS on boot.
                # 如果ws断开连接，重连
                if not order_manager.check_connection():
                    logger.error("Realtime data connection unexpectedly closed, restarting.")
                    order_manager.restart()

                order_manager.sanity_check()  # Ensures health of mm - several cut-out points here
                order_manager.print_status()  # Print skew, delta, etc
            # 具体的策略下单逻辑
            self.strategy()
            sleep(settings.LOOP_INTERVAL)


#
# Helpers
#

# 聪 to 比特币
def XBt_to_XBT(XBt):
    return float(XBt) / constants.XBt_TO_XBT


def cost(instrument, quantity, price):
    mult = instrument["multiplier"]  # multiplier:乘数(-100000000)
    P = mult * price if mult >= 0 else mult / price
    return abs(quantity * P)


def margin(instrument, quantity, price):
    return cost(instrument, quantity, price) * instrument["initMargin"]  # initMargin:其实保证金(0.01)


# 程序入口
def run():
    logger.info('BitMEX Market Maker Version: %s\n' % constants.VERSION)  # 信息：软件版本

    # 读取密钥配置，list类型
    key_secrets = settings.API_SECRETS
    mom = MulOrderManager(key_secrets=key_secrets)
    # Try/except just keeps ctrl-c from printing an ugly stacktrace
    try:
        mom.run_loop()
    except (KeyboardInterrupt, SystemExit):
        sys.exit()

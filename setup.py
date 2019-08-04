#!/usr/bin/env python
# python标准的打包、分发工具
from setuptools import setup
from os.path import dirname, join

import market_maker

# 当前文件路径
here = dirname(__file__)


setup(name='bitmex-market-maker', # 应用名称
      version=market_maker.__version__,  # 应用版本
      description='Market making bot for BitMEX API',
      url='https://github.com/BitMEX/sample-market-maker', # 项目主页
      long_description=open(join(here, 'README.md')).read(),
      long_description_content_type='text/markdown',
      author='clark',
      author_email='996719704@qq.com',
      install_requires=[ # 自动安装所需依赖
          'requests',
          'websocket-client',
          'future',
          'appdirs==1.4.3',
          'backports.ssl-match-hostname==3.5.0.1',
          'packaging==16.8',
          'pyparsing==2.2.0',
          'six==1.10.0'
      ],
      packages=['market_maker', 'market_maker.auth', 'market_maker.utils', 'market_maker.ws'],  # 应用源代码
      entry_points={
          'console_scripts': ['marketmaker = market_maker:run']  # 命令行下执行marketmaker，将会运行market_maker(目录下的__init__.py)下的run函数
      }
      )

# 该文件用于打包

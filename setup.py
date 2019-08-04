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
      author='Samuel Reed',
      author_email='sam@bitmex.com',
      install_requires=[
          'requests',
          'websocket-client',
          'future'
      ],
      packages=['market_maker', 'market_maker.auth', 'market_maker.utils', 'market_maker.ws'],  # 应用源代码
      entry_points={
          'console_scripts': ['marketmaker = market_maker:run']  # 命令行下执行marketmaker，将会运行market_maker(目录下的__init__.py)下的run函数
      }
      )

# 改文件用户打包

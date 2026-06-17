import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import config

config.USE_KR_MARKET = True
config.USE_US_MARKET = True
config.US_UNIVERSE = 'CUSTOM'
config.US_CUSTOM_SYMBOLS = ['TSLA', 'NVDA', 'SATL', 'IONQ', 'SMR', 'PLTR', 'META', 'AAPL']
config.KR_UNIVERSE = 'CUSTOM'
config.KR_CUSTOM_SYMBOLS = ['000660', '005930', '005380']
config.MIN_SIGNALS_TO_SHOW = 1

import screener
screener.main()

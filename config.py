
# ====== config.py (Hardcoded keys + PATCH v2) ======
FINNHUB_API_KEY   = "d2f3fq9r01qj3egr0apgd2f3fq9r01qj3egr0aq0"
ALPACA_API_KEY    = "PKXB8N50RX1YLX2N39AE"
ALPACA_API_SECRET = "3IGZrOtdWnuOCNGOVAYfGTCaccZh7h0tPDmNvFHq"

UNIVERSE_MODE = "AUTO"         # AUTO: Finnhub symbols ∩ Alpaca tradable assets
UNIVERSE_FILE = "symbols_all.txt"

SCAN_BATCH_SIZE = 500
CONCURRENCY = 40               # keep friendly to Finnhub
BASE_SCAN_DELAY = 2.5
TAKE_PER_SCAN = 5
FORCE_BUY_ON_FIRST_PASS = True

# Filters
MIN_PRICE = 1.00               # skip sub-$1
MIN_DAY_PCT = -10.0
MIN_1MOMENTUM_PCT = -10.0

# Risk / Sizing
DOLLARS_PER_TRADE = 75
MAX_OPEN_POSITIONS = 15
ALLOW_FRACTIONAL = False       # whole shares to avoid fractional rejections

# Orders / exits
USE_EXTENDED_HOURS = True
LIMIT_SLIPPAGE_BPS = 15
TRAIL_PERCENT = 3.0
TIME_EXIT_MINUTES = 7

ALPACA_BROKER_BASE = "https://paper-api.alpaca.markets"

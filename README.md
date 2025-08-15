
# PATCH v2
- Filters universe to **Alpaca-tradable** listed symbols (NYSE/NASDAQ/AMEX/ARCA) — avoids OTC 422 errors.
- **Whole shares** by default; set `ALLOW_FRACTIONAL=True` if your paper account supports fractional.
- Skips **sub-$1** names with `MIN_PRICE`.
- Prints full Alpaca rejection body so you can see the exact reason if any order is refused.
- Gentler Finnhub pacing to reduce throttle warnings.


# ====== bot.py (PATCH v2) ======
import os, sys, time, math, asyncio, itertools, json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Tuple
import httpx

from config import *

HEADERS_ALPACA = {
    "APCA-API-KEY-ID": ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": ALPACA_API_SECRET,
}

FINNHUB_BASE = "https://finnhub.io/api/v1"

def now_utc(): return datetime.now(timezone.utc)

async def fetch_symbols_finnhub(client: httpx.AsyncClient) -> List[str]:
    url = f"{FINNHUB_BASE}/stock/symbol"
    params = {"exchange":"US", "token": FINNHUB_API_KEY}
    r = await client.get(url, params=params, timeout=30.0)
    r.raise_for_status()
    data = r.json()
    syms = []
    for d in data:
        s = d.get("symbol")
        if not s: continue
        if s.isupper() and s.isascii():
            syms.append(s)
    return sorted(set(syms))

def alpaca_get(session: httpx.Client, path: str, params=None):
    r = session.get(ALPACA_BROKER_BASE + path, headers=HEADERS_ALPACA, timeout=40.0, params=params)
    r.raise_for_status(); return r.json()

def alpaca_post(session: httpx.Client, path: str, payload: dict):
    r = session.post(ALPACA_BROKER_BASE + path, headers=HEADERS_ALPACA, timeout=40.0, json=payload)
    if r.status_code >= 400:
        try: body = r.json()
        except Exception: body = {"text": r.text[:400]}
        raise RuntimeError(f"HTTP {r.status_code} {body}")
    return r.json()

def alpaca_tradable_set(session: httpx.Client) -> set:
    out=set(); page=1
    while True:
        r = session.get(ALPACA_BROKER_BASE + "/v2/assets",
                        headers=HEADERS_ALPACA, timeout=60.0,
                        params={"status":"active","asset_class":"us_equity","page":page,"per_page":1000})
        r.raise_for_status()
        arr = r.json()
        if not arr: break
        for a in arr:
            exch = (a.get("exchange") or "").upper()
            sym = a.get("symbol") or ""
            if a.get("tradable") and exch in ("NYSE","NASDAQ","AMEX","ARCA"):
                if not sym.endswith(".W"):
                    out.add(sym)
        page += 1
    return out

async def fetch_quote(client: httpx.AsyncClient, sym: str) -> Tuple[str, Dict[str, Any]]:
    url = f"{FINNHUB_BASE}/quote"
    params = {"symbol": sym, "token": FINNHUB_API_KEY}
    try:
        r = await client.get(url, params=params, timeout=10.0)
        if r.status_code != 200:
            return sym, {}
        q = r.json()
        price = float(q.get("c") or 0)
        if price <= 0:
            return sym, {}
        return sym, q
    except Exception:
        return sym, {}

async def fetch_batch_quotes(symbols: List[str], concurrency: int) -> Dict[str, Dict[str, Any]]:
    out = {}
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient() as client:
        async def worker(sym):
            async with sem:
                s, q = await fetch_quote(client, sym)
                if q:
                    out[s] = q
        await asyncio.gather(*[worker(s) for s in symbols])
    return out

def qty_from_dollars(price: float, dollars: float) -> str:
    if not price or price <= 0: return "0"
    if ALLOW_FRACTIONAL:
        return f"{max(dollars/price, 0.0):.4f}"
    else:
        whole = max(int(dollars // price), 1)
        return str(whole)

def limit_price(price: float) -> float:
    return round(price * (1.0 + LIMIT_SLIPPAGE_BPS/10000.0), 4)

def rank_by_momentum(quotes: Dict[str, Dict[str, Any]]):
    ranked=[]
    for s,q in quotes.items():
        price=float(q.get("c") or 0)
        if price < MIN_PRICE: continue
        day_pct=float(q.get("dp") or 0)
        ranked.append((s, day_pct, day_pct, price))  # mom proxy = day pct
    ranked.sort(key=lambda x:x[1], reverse=True)
    return ranked

def qualifies(day_pct, mom): return (mom>=MIN_1MOMENTUM_PCT) and (day_pct>=MIN_DAY_PCT)

async def main():
    print("=== Grandmaster Finnhub + Alpaca — PATCH v2 ===")
    alp = httpx.Client()
    print("[UNIVERSE] Fetching Finnhub symbols...")
    async with httpx.AsyncClient() as ac:
        fh_syms = await fetch_symbols_finnhub(ac)
    print(f"[UNIVERSE] Finnhub symbols: {len(fh_syms)}")

    print("[UNIVERSE] Fetching Alpaca tradable symbols...")
    tradable = alpaca_tradable_set(alp)
    print(f"[UNIVERSE] Alpaca tradable: {len(tradable)}")

    syms = sorted(set(fh_syms).intersection(tradable))
    print(f"[UNIVERSE] Intersection (scannable): {len(syms)}")

    def batches(seq,n):
        it=iter(seq)
        while True:
            chunk=tuple(itertools.islice(it,n))
            if not chunk: return
            yield chunk
    batch_iter = itertools.cycle(list(batches(syms, SCAN_BATCH_SIZE)))

    first_loop=True
    opened_at={}; timed_out={}

    while True:
        try:
            positions = alpaca_get(alp, "/v2/positions")
        except Exception as e:
            print(f"[WARN] positions: {e}"); positions=[]
        now = now_utc()
        for p in positions:
            sym=p.get("symbol")
            if sym not in opened_at: opened_at[sym]=now
        active={p.get("symbol") for p in positions}
        for s in list(opened_at.keys()):
            if s not in active:
                opened_at.pop(s,None); timed_out.pop(s,None)

        if TIME_EXIT_MINUTES and TIME_EXIT_MINUTES>0:
            cutoff = now - timedelta(minutes=TIME_EXIT_MINUTES)
            for p in positions:
                sym=p.get("symbol"); qty=p.get("qty")
                if sym in opened_at and opened_at[sym] <= cutoff and not timed_out.get(sym):
                    try:
                        alpaca_post(alp, "/v2/orders", {"symbol":sym,"qty":qty,"side":"sell","type":"market","time_in_force":"day"})
                        print(f"[TIME-EXIT] Market sell {sym} qty={qty}")
                    except Exception as e:
                        print(f"[WARN] time-exit {sym}: {e}")
                    timed_out[sym]=True

        if len(positions) >= MAX_OPEN_POSITIONS:
            # ensure trailing stops
            try:
                oo = alpaca_get(alp, "/v2/orders", params={"status":"open"})
            except Exception as e:
                print(f"[WARN] open orders: {e}"); oo=[]
            has_sell = {o.get("symbol"):True for o in oo if o.get("side")=="sell"}
            for p in positions:
                sym=p.get("symbol"); qty=p.get("qty")
                if sym and qty and not has_sell.get(sym):
                    try:
                        alpaca_post(alp, "/v2/orders", {"symbol":sym,"qty":qty,"side":"sell","type":"trailing_stop",
                                                        "time_in_force":"day","trail_percent":TRAIL_PERCENT,
                                                        "extended_hours":bool(USE_EXTENDED_HOURS)})
                        print(f"[EXIT] Trailing stop for {sym} {TRAIL_PERCENT}%")
                    except Exception as e:
                        print(f"[WARN] trailing stop {sym}: {e}")
            time.sleep(BASE_SCAN_DELAY); continue

        batch = next(batch_iter)
        print(f"[SCAN] {len(batch)} symbols @ {datetime.now().strftime('%H:%M:%S')}")

        quotes = await fetch_batch_quotes(list(batch), CONCURRENCY)
        if not quotes:
            print("[WARN] No quotes in this batch (throttle/off-hours).")
            time.sleep(BASE_SCAN_DELAY); continue

        ranked = rank_by_momentum(quotes)
        ranked = [(s,m,dp,pr) for (s,m,dp,pr) in ranked if qualifies(dp, m)]
        if not ranked and FORCE_BUY_ON_FIRST_PASS and first_loop:
            for s,q in list(quotes.items())[:TAKE_PER_SCAN]:
                p = float(q.get("c") or 0)
                if p >= MIN_PRICE:
                    ranked.append((s, 0.0, float(q.get("dp") or 0), p))

        if ranked:
            print("[TOP]", " | ".join([f"{s}: day {d:+.2f}% @ {p:.2f}" for s,m,d,p in ranked[:10]]))
        else:
            print("[TOP] No qualifiers.")

        slots = max(MAX_OPEN_POSITIONS - len(positions), 0)
        to_take = min(slots, TAKE_PER_SCAN)
        if to_take>0 and ranked:
            picks = ranked[:to_take]
            for s,m,d,p in picks:
                qty = qty_from_dollars(p, DOLLARS_PER_TRADE)
                try:
                    order = alpaca_post(alp, "/v2/orders", {
                        "symbol": s, "qty": qty, "side":"buy", "type":"limit",
                        "time_in_force":"day", "limit_price": limit_price(p),
                        "extended_hours": bool(USE_EXTENDED_HOURS),
                    })
                    print(f"[ENTRY] {s} qty={qty} lim={order.get('limit_price','?')} | day {d:+.2f}%")
                except Exception as e:
                    print(f"[ERR] order {s}: {e}")
        time.sleep(BASE_SCAN_DELAY)

if __name__ == "__main__":
    try:
        import asyncio; asyncio.run(main())
    except KeyboardInterrupt:
        print("Exiting...")

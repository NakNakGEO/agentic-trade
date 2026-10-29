import time
from tradingview_ta import TA_Handler, Interval, get_multiple_analysis
t = time.time()
for interval in (Interval.INTERVAL_1_MINUTE, Interval.INTERVAL_1_DAY):
    for screener, syms in (("forex", ["FX_IDC:EURUSD", "FX_IDC:USDJPY", "FX_IDC:NZDUSD", "OANDA:EURUSD"]),
                           ("cfd", ["OANDA:XAUUSD"]), ("crypto", ["COINBASE:BTCUSD", "COINBASE:ETHUSD"])):
        try:
            res = get_multiple_analysis(screener=screener, interval=interval, symbols=syms, additional_indicators=["ATR"])
        except TypeError:
            res = get_multiple_analysis(screener=screener, interval=interval, symbols=syms)
        for k, a in res.items():
            if a is None:
                print(interval, k, "-> None"); continue
            i = a.indicators
            print(f"{interval:3} {k:18} O {i.get('open')} H {i.get('high')} L {i.get('low')} C {i.get('close')} ATR {i.get('ATR')} time {a.time}")
print("took", round(time.time() - t, 1), "s")

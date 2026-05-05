import os
import ccxt
import time
import pandas as pd
import pandas_ta as ta
import requests

# === TELEGRAM SETTINGS ===
def send_telegram_msg(message):
    token = "8339067672:AAGdd4lOZk6Q7rDZe71avtXWnYakMUy2UXk"
    chat_id = "1887494098"
    url = f"https://api.telegram.org/bot{token}/sendMessage?chat_id={chat_id}&text={message}"
    try:
        requests.get(url)
    except Exception as e:
        print(f"Telegram Error: {e}")

# === API Connection (Hidden) ===
api_key = os.getenv('OKX_API_KEY')
api_secret = os.getenv('OKX_SECRET')
api_pass = os.getenv('OKX_PASS')

# Connection fix: Sirf proxy aur hostname add kiya hai jo free account ke liye lazmi hai
exchange = ccxt.okx({
    'apiKey': api_key,
    'secret': api_secret,
    'password': api_pass,
    'enableRateLimit': True,
    'hostname': 'aws.okx.com', 
    'proxies': {
        'http': 'http://proxy.server:3128',
        'https': 'http://proxy.server:3128',
    },
})

# Ye dictionaries global honi chahiye
last_signals = {}
watchlist = {}

# Global Settings
COOLDOWN_MINUTES = 30

def htf_close_safe(df_htf):
    """Helper function to check HTF health with error safety"""
    try:
        if df_htf is None or len(df_htf) < 200:
            return True

        close_htf = df_htf['close']
        volume_htf = df_htf['volume']

        ema50_htf = df_htf.ta.ema(length=50)
        ema200_htf = df_htf.ta.ema(length=200)
        rsi_htf = df_htf.ta.rsi(length=14)
        vol_avg_htf = df_htf.ta.sma(volume_htf, length=20)

        if (
            close_htf.empty or
            ema50_htf is None or
            ema200_htf is None or
            rsi_htf is None or
            vol_avg_htf is None
        ):
            return True

        return (
            close_htf.iloc[-1] > ema50_htf.iloc[-1]
            and ema50_htf.iloc[-1] > ema200_htf.iloc[-1]
            and rsi_htf.iloc[-1] > 50
            and volume_htf.iloc[-1] > vol_avg_htf.iloc[-1] * 1.0
        )

    except Exception as e:
        print(f"HTF Check Error: {e}")
        return True


def generate_execution_output(df, is_buy, is_sell, adx_val, curr_close, curr_atr, coin_name, is_hold=False):
    """Generates Market-Adaptive TP/SL with Wallet Loss Protection and 1.5% TP1 Cap"""
    try:
        global last_signals
        last_signals[coin_name] = time.time()

        # Dynamic Leverage
        if is_hold:
            lev = 7
        else:
            dynamic_lev = 5 + (int(adx_val) - 21)
            if any(x in coin_name for x in ['BTCUSDT', 'ETHUSDT', 'BTC/USDT', 'ETH/USDT']):
                lev = min(max(5, dynamic_lev), 40)
            else:
                lev = min(max(5, dynamic_lev), 30)

        m = 1 if is_buy else -1

        # ================= NEW MARKET-ADAPTIVE TP & SL (OPTIMIZED) =================
        tp1_cap = 0.015   # Max 1.5% price move for TP1
        min_move = 0.008  # Min 0.8% price move for TP1

        local_res = df['high'].rolling(10).max().iloc[-1]
        local_sup = df['low'].rolling(10).min().iloc[-1]

        max_sl_move = (22.0 / lev / 100)

        if is_buy:
            tp1_ideal = min(local_res * 0.999, curr_close * (1 + tp1_cap))
            tp1 = max(tp1_ideal, curr_close * (1 + min_move))
            struct_sl = df['low'].rolling(15).min().iloc[-1] * 0.998
            sl = max(struct_sl, curr_close * (1 - max_sl_move))
        else:
            tp1_ideal = max(local_sup * 1.001, curr_close * (1 - tp1_cap))
            tp1 = min(tp1_ideal, curr_close * (1 - min_move))
            struct_sl = df['high'].rolling(15).max().iloc[-1] * 1.002
            sl = min(struct_sl, curr_close * (1 + max_sl_move))

        tps = [
            tp1,
            tp1 + (m * curr_atr * 1.5),
            tp1 + (m * curr_atr * 2.5),
            tp1 + (m * curr_atr * 4.0),
            tp1 + (m * curr_atr * 5.5)
        ]

        signal_label = "HOLD" if is_hold else ("BUY" if is_buy else "SELL")
        
        # --- TELEGRAM NOTIFICATION ---
        msg = (f"🚀 ELITE PRO v14: {coin_name}\n"
               f"Type: {signal_label}\n"
               f"Price: {curr_close}\n"
               f"Leverage: {lev}x\n"
               f"SL: {sl:.4f}\n"
               f"TP1: {tps[0]:.4f}\n"
               f"TP2: {tps[1]:.4f}")
        send_telegram_msg(msg)
        # -----------------------------

        return signal_label, is_buy, is_sell, lev, curr_close, sl, *tps

    except Exception as e:
        print(f"Execution Output Error for {coin_name}: {e}")
        return False, False, 0, 0, 0, 0, 0, 0, 0, 0


def calculate_v14_ultra_signals(df, df_htf, coin_name, btc_trend_ok):
    global last_signals, watchlist

    if df is None or len(df) < 300 or df_htf is None:
        return False, False, 0, 0, 0, 0, 0, 0, 0, 0

    try:
        current_time = time.time()
        if coin_name in last_signals:
            if (current_time - last_signals[coin_name]) < (COOLDOWN_MINUTES * 60):
                return False, False, 0, 0, 0, 0, 0, 0, 0, 0

        # Indicators
        ema10 = df.ta.ema(length=10)
        ema20 = df.ta.ema(length=20)
        ema50 = df.ta.ema(length=50)
        ema200 = df.ta.ema(length=200)
        rsi = df.ta.rsi(length=14)
        atr = df.ta.atr(length=14)
        adx_df = df.ta.adx(length=14)
        macd = df.ta.macd()

        if any(v is None for v in [ema10, ema20, ema50, ema200, rsi, atr, adx_df, macd]):
            return False, False, 0, 0, 0, 0, 0, 0, 0, 0

        adx = adx_df['ADX_14']
        macd_line = macd['MACD_12_26_9']
        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']
        open_ = df['open']
        vol_avg = df.ta.sma(volume, length=20)

        curr_close = close.iloc[-1]
        curr_ema10 = ema10.iloc[-1]
        curr_atr = atr.iloc[-1]

        if pd.isna(curr_ema10) or pd.isna(curr_atr) or pd.isna(adx.iloc[-1]):
            return False, False, 0, 0, 0, 0, 0, 0, 0, 0

        btc_final_ok = btc_trend_ok and htf_close_safe(df_htf)

        if coin_name in watchlist:
            item = watchlist[coin_name]
            if (current_time - item['setup_time']) > (15 * 60):
                del watchlist[coin_name]
            else:
                gap_to_ema = abs(curr_close - item['entry_zone']) / item['entry_zone'] * 100
                vol_surging = volume.iloc[-1] > volume.iloc[-2]

                trigger_buy = (
                    item['type'] == 'BUY' 
                    and (low.iloc[-1] <= item['entry_zone'] or gap_to_ema <= 0.25)
                    and close.iloc[-1] > open_.iloc[-1]
                    and vol_surging
                )
                trigger_sell = (
                    item['type'] == 'SELL' 
                    and (high.iloc[-1] >= item['entry_zone'] or gap_to_ema <= 0.25)
                    and close.iloc[-1] < open_.iloc[-1]
                    and vol_surging
                )

                if trigger_buy or trigger_sell:
                    is_buy, is_sell = (True, False) if item['type'] == 'BUY' else (False, True)
                    res = generate_execution_output(df, is_buy, is_sell, item['adx_val'], curr_close, curr_atr, coin_name)
                    del watchlist[coin_name]
                    return res

        htf_ema = df_htf.ta.ema(length=50)
        htf_up = df_htf['close'].iloc[-1] > htf_ema.iloc[-1] if htf_ema is not None else True
        htf_down = not htf_up

        trend_up = (ema10 > ema20) & (ema20 > ema50) & (ema50 > ema200) & (close > ema10)
        trend_down = (ema10 < ema20) & (ema20 < ema50) & (ema20 < ema50) & (ema50 < ema200) & (close < ema10)
        vol_ok = volume > (vol_avg * 1.0)
        macd_moving_up = macd_line.iloc[-1] > macd_line.iloc[-2]
        macd_moving_down = macd_line.iloc[-1] < macd_line.iloc[-2]

        buy_score = (trend_up.astype(int) * 2) + int(htf_up) + int(macd_moving_up) + vol_ok.astype(int)
        sell_score = (trend_down.astype(int) * 2) + int(htf_down) + int(macd_moving_down) + vol_ok.astype(int)

        recent_high = high.rolling(10).max(); recent_low = low.rolling(10).min()
        liquidity_sweep_buy = (low < recent_low.shift(1)) & (close > recent_low.shift(1))
        liquidity_sweep_sell = (high > recent_high.shift(1)) & (close < recent_high.shift(1))
        body = abs(close - open_); candle_strength = body > (atr * 0.5)

        bullish_confirm = (close.iloc[-1] > open_.iloc[-1] and close.iloc[-1] > high.iloc[-2])
        bearish_confirm = (close.iloc[-1] < open_.iloc[-1] and close.iloc[-1] < low.iloc[-2])

        pump_ok = (body.iloc[-1] < (curr_atr * 1.8) and (high.iloc[-1] - low.iloc[-1]) < (curr_atr * 2.3))
        market_trending = abs(ema50.iloc[-1] - ema200.iloc[-1]) > (curr_atr * 0.5)

        bos_confirmed = curr_close > high.rolling(window=20).max().iloc[-2]
        if trend_up.iloc[-1] and htf_up and bos_confirmed and (adx.iloc[-1] > 21) and (52 <= rsi.iloc[-1] <= 65):
            return generate_execution_output(df, True, False, adx.iloc[-1], curr_close, curr_atr, coin_name, is_hold=True)

        setup_buy_base = (buy_score.iloc[-1] >= 5 and adx.iloc[-1] > 21 and (50 <= rsi.iloc[-1] <= 72) and liquidity_sweep_buy.iloc[-1] and btc_final_ok and candle_strength.iloc[-1] and bullish_confirm and pump_ok and market_trending)
        setup_sell_base = (sell_score.iloc[-1] >= 5 and adx.iloc[-1] > 21 and (28 <= rsi.iloc[-1] <= 48) and liquidity_sweep_sell.iloc[-1] and (not btc_final_ok) and candle_strength.iloc[-1] and bearish_confirm and pump_ok and market_trending)

        if abs(curr_close - curr_ema10) / curr_ema10 * 100 > 3.0:
            return False, False, 0, 0, 0, 0, 0, 0, 0, 0

        if setup_buy_base:
            watchlist[coin_name] = {'type': 'BUY', 'entry_zone': curr_ema10, 'adx_val': adx.iloc[-1], 'setup_time': time.time()}
        if setup_sell_base:
            watchlist[coin_name] = {'type': 'SELL', 'entry_zone': curr_ema10, 'adx_val': adx.iloc[-1], 'setup_time': time.time()}

        return False, False, 0, 0, 0, 0, 0, 0, 0, 0

    except Exception as e:
        print(f"Signal Calculation Error: {e}")
        return False, False, 0, 0, 0, 0, 0, 0, 0, 0

# === Main Loop ===
print("✅ ELITE PRO v14 is Live! Checking Market...")
while True:
    try:
        # Example BTC check
        ohlcv = exchange.fetch_ohlcv('BTC/USDT', timeframe='15m', limit=300)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        ohlcv_htf = exchange.fetch_ohlcv('BTC/USDT', timeframe='1h', limit=300)
        df_htf = pd.DataFrame(ohlcv_htf, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Trend check
        res = calculate_v14_ultra_signals(df, df_htf, 'BTC/USDT', True)
        time.sleep(60)
    except Exception as e:
        print(f"Loop Error: {e}")
        time.sleep(10)
        my_coins = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'BNB/USDT', 
    'DOGE/USDT', 'PEPE/USDT', 'SHIB/USDT', 'NEAR/USDT', 'LINK/USDT',
    'AVAX/USDT', 'SUI/USDT', 'APT/USDT', 'TIA/USDT', 'ARB/USDT',
    'OP/USDT', 'INJ/USDT', 'SEI/USDT', 'DOT/USDT', 'MATIC/USDT',
    'LTC/USDT', 'BCH/USDT', 'TRX/USDT', 'ICP/USDT', 'FIL/USDT',
    'STX/USDT', 'WIF/USDT', 'FLOKI/USDT', 'BONK/USDT', 'ADA/USDT'
]

import os
import time
import threading
import logging
import requests
import pandas as pd
import talib
import random
import json
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Load environment variables
load_dotenv()

# API Credentials
CAPITAL_API_KEY = os.getenv("CAPITAL_API_KEY")
CAPITAL_API_PASSWORD = os.getenv("CAPITAL_API_PASSWORD")
CAPITAL_IDENTIFIER = os.getenv("CAPITAL_IDENTIFIER")
CAPITAL_API_URL = os.getenv("CAPITAL_API_URL", "https://demo-api-capital.backend-capital.com/api/v1")

# Trading Settings
TRADE_INTERVAL = int(os.getenv("TRADE_INTERVAL", 300))  # 5 minutes
TP_MOVE_PERCENT = float(os.getenv("TP_MOVE_PERCENT", 0.005))  # Move TP by 0.5% when price moves
BREAKEVEN_TRIGGER = 1 / 100  # Move SL to breakeven at 1% profit
SMA_PERIOD = 20
RSI_PERIOD = 14

# Symbols & Lot Sizes
SYMBOLS = ["BTCUSD", "ETHUSD", "XRPUSD", "LTCUSD", "ADAUSD", "SOLUSD", "DOGEUSD", "DOTUSD", "MATICUSD", "BNBUSD"]
LOT_SIZES = {
    "BTCUSD": 0.001, "ETHUSD": 0.01, "ADAUSD": 0.5, "XRPUSD": 100, "LTCUSD": 1,
    "SOLUSD": 10, "DOGEUSD": 1000, "DOTUSD": 10, "MATICUSD": 100, "BNBUSD": 1
}
DEFAULT_LOT_SIZE = 0.01

# Token Expiry
TOKEN_EXPIRY = 3600  # 1 hour (adjust according to API docs)
last_auth_time = time.time()

# Enhanced Logging Configuration
LOG_FILE = "trading_bot.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# Create a logger for detailed API interactions
api_logger = logging.getLogger('api_interactions')
api_logger.setLevel(logging.DEBUG)
api_handler = logging.FileHandler('api_debug.log', mode="w", encoding="utf-8")
api_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
api_logger.addHandler(api_handler)

# Cache for API responses to reduce calls
api_cache = {}
API_CACHE_TTL = 60  # seconds

# Create session with retry mechanism
def create_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PUT", "DELETE"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

# Authenticate with Capital.com API with rate limiting and caching
def authenticate():
    cache_key = "auth_tokens"
    
    # Check if we have valid cached tokens
    if cache_key in api_cache and time.time() < api_cache[cache_key]["expiry"]:
        return {
            'security_token': api_cache[cache_key]["x_security"],
            'cst_token': api_cache[cache_key]["cst"]
        }
    
    # Add jitter to prevent synchronized API calls
    time.sleep(random.uniform(0.1, 0.5))
    
    url = f"{CAPITAL_API_URL}/session"
    headers = {"X-CAP-API-KEY": CAPITAL_API_KEY, "Content-Type": "application/json"}
    payload = {"identifier": CAPITAL_IDENTIFIER, "password": CAPITAL_API_PASSWORD}

    try:
        session = create_session()
        api_logger.debug(f"Authentication request to {url}")
        response = session.post(url, headers=headers, json=payload)
        
        api_logger.debug(f"Authentication response: {response.status_code}")
        
        if response.status_code == 200:
            cst = response.headers.get("CST")
            x_security = response.headers.get("X-SECURITY-TOKEN")
            
            # Cache the tokens for 10 minutes
            api_cache[cache_key] = {
                "cst": cst,
                "x_security": x_security,
                "expiry": time.time() + 600  # 10 minutes
            }
            
            return {
                'security_token': x_security,
                'cst_token': cst
            }
        else:
            error_data = "Unknown error"
            try:
                error_data = response.json()
            except Exception:
                pass
            logging.error(f"Authentication failed: {response.status_code} - {error_data}")
            return None
    except Exception as e:
        logging.error(f"Exception during authentication: {str(e)}", exc_info=True)
        return None

# Fetch market data
def fetch_market_data(symbol, session_tokens):
    url = f"{CAPITAL_API_URL}/prices/{symbol}"  # Adjust the endpoint as needed
    headers = {
        "X-CAP-API-KEY": CAPITAL_API_KEY,
        "X-SECURITY-TOKEN": session_tokens['security_token'],
        "CST": session_tokens['cst_token'],
        "Content-Type": "application/json"
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        if 'prices' not in data or not isinstance(data['prices'], list):
            logging.error(f"Invalid market data structure for {symbol}")
            return None
        return data
    else:
        logging.error(f"Failed to fetch market data for {symbol}. Response: {response.status_code}, {response.text}")
        return None

# Perform technical analysis
def perform_technical_analysis(symbol, session_tokens):
    data = fetch_market_data(symbol, session_tokens)
    if data:
        logging.info(f"Market data for {symbol}: {data}")  # Debug print to inspect the data structure
        df = pd.DataFrame(data['prices'])
        if 'closePrice' not in df.columns:
            logging.error(f"'closePrice' column not found in market data for {symbol}. Available columns: {df.columns}")
            return None
        df['close'] = df['closePrice'].apply(lambda x: x['bid'])  # Assuming you want to use the 'bid' price
        df['close'] = df['close'].astype(float)
        df['sma'] = talib.SMA(df['close'], timeperiod=SMA_PERIOD)
        df['rsi'] = talib.RSI(df['close'], timeperiod=RSI_PERIOD)
        logging.info(f"Technical analysis for {symbol}: SMA={df['sma'].iloc[-1]}, RSI={df['rsi'].iloc[-1]}")
        return df
    return None

# Place order
def place_order(session_tokens, symbol, direction, lot_size):
    url = f"{CAPITAL_API_URL}/orders"
    headers = {
        "X-CAP-API-KEY": CAPITAL_API_KEY,
        "X-SECURITY-TOKEN": session_tokens['security_token'],
        "CST": session_tokens['cst_token'],
        "Content-Type": "application/json"
    }
    payload = {
        "epic": symbol,
        "direction": direction.upper(),
        "size": LOT_SIZES.get(symbol, DEFAULT_LOT_SIZE),
        "type": "MARKET"
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        logging.info(f"Order executed: {direction} {symbol}")
        return response.json()['dealReference']
    else:
        logging.error(f"Order failed: {response.text}")
        return None

# Modify order
def modify_order(session_tokens, deal_id, stop_loss, take_profit):
    url = f"{CAPITAL_API_URL}/positions/{deal_id}"
    headers = {
        "X-CAP-API-KEY": CAPITAL_API_KEY,
        "X-SECURITY-TOKEN": session_tokens['security_token'],
        "CST": session_tokens['cst_token'],
        "Content-Type": "application/json"
    }
    payload = {
        "stopLoss": stop_loss,
        "takeProfit": take_profit
    }
    response = requests.put(url, headers=headers, json=payload)
    if response.status_code == 200:
        logging.info(f"Order modified: {deal_id}")
    else:
        logging.error(f"Order modification failed: {response.text}")

# Trading logic
def trade_logic(session_tokens):
    for symbol in SYMBOLS:
        df = perform_technical_analysis(symbol, session_tokens)
        if df is not None:
            # Example trading logic based on SMA and RSI
            if df['rsi'].iloc[-1] < 30:
                logging.info(f"Buy signal for {symbol}")
            elif df['rsi'].iloc[-1] > 70:
                logging.info(f"Sell signal for {symbol}")

# Schedule trading
def schedule_trading(session_tokens):
    global last_auth_time
    while True:
        # Refresh tokens if expired
        if time.time() - last_auth_time > TOKEN_EXPIRY:
            new_tokens = authenticate()
            if new_tokens:
                session_tokens.update(new_tokens)
                last_auth_time = time.time()
        try:
            trade_logic(session_tokens)
        except Exception as e:
            logging.error(f"Error in trading thread: {str(e)}", exc_info=True)
        time.sleep(TRADE_INTERVAL)

# Flask Webhook
app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    global session_tokens
    try:
        data = request.get_json()
        symbol = data.get("symbol")
        action = data.get("action")
        
        if not symbol or not action:
            return jsonify({"status": "error", "message": "Missing required fields"}), 400
            
        try:
            price = float(data.get("price", 0))
        except (ValueError, TypeError):
            return jsonify({"status": "error", "message": "Invalid price value"}), 400
            
        logging.info(f"🌐 Webhook received: {json.dumps(data)}")
        
        # Execute trade
        if action.lower() in ['buy', 'sell']:
            place_order(session_tokens, symbol, action, LOT_SIZES.get(symbol, DEFAULT_LOT_SIZE))
        
        return jsonify({
            "status": "success", 
            "message": f"✅ Trade request received: {action} {symbol} at {price}"
        }), 200
    except Exception as e:
        logging.error(f"❌ Webhook error: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"Internal server error: {str(e)}"}), 500

def main():
    logging.info("🚀 Starting Capital.com Trading Bot")
    session_tokens = authenticate()
    if session_tokens:
        threading.Thread(target=schedule_trading, args=(session_tokens,)).start()
        app.run(host="0.0.0.0", port=5000, threaded=True)
    else:
        logging.error("❌ Failed to authenticate. Exiting.")

if __name__ == "__main__":
    main()

import os
import sys  # Ensure sys is imported for proper debugging
import time  # Ensure this is imported
import threading
import logging
import requests
import pandas as pd
import talib  # Ensure this is imported
import random  # Ensure this is imported
import json
from flask import Flask, request, jsonify, has_request_context, send_file
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import numpy as np  # Ensure this is imported
from cryptography.fernet import Fernet
import subprocess
import shutil

def install_node_npm():
    """Check if Node.js & npm are installed; if they are, skip installation."""
    try:
        # Check if Node.js and npm are installed
        node_version = subprocess.run(["node", "-v"], capture_output=True, text=True)
        npm_version = subprocess.run(["npm", "-v"], capture_output=True, text=True)

        if node_version.returncode == 0 and npm_version.returncode == 0:
            print(f"✅ Node.js is already installed: {node_version.stdout.strip()}")
            print(f"✅ npm is already installed: {npm_version.stdout.strip()}")
            return  # Exit function if already installed
    except FileNotFoundError:
        print("⚠️ Node.js or npm not found. Skipping installation...")

install_node_npm()

# Ensure npm dependencies are installed
if not os.path.exists("package.json"):
    print("⚠️ package.json missing. Creating default package.json...")
    with open("package.json", "w") as f:
        f.write('{\n  "name": "trading-bot",\n  "version": "1.0.0",\n  "dependencies": {} \n}')

# Find the full path of npm
npm_path = shutil.which("npm")

if npm_path:
    print(f"✅ Found npm at: {npm_path}")
    subprocess.run([npm_path, "install"], shell=True, check=True)
else:
    print("❌ npm is not found. Make sure Node.js is installed and added to PATH.")

# Load environment variables
load_dotenv()

# API Credentials
def get_api_key():
    encrypted_key = os.getenv("ENCRYPTED_API_KEY")
    encryption_key = os.getenv("ENCRYPTION_KEY")

    if not encryption_key:
        logging.error("❌ Missing ENCRYPTION_KEY in .env file! Using unencrypted API key instead.")
        return os.getenv("CAPITAL_API_KEY")  # Fallback

    try:
        cipher_suite = Fernet(encryption_key.encode())
        return cipher_suite.decrypt(encrypted_key.encode()).decode()
    except Exception as e:
        logging.error(f"❌ Failed to decrypt API Key: {e}")
        return os.getenv("CAPITAL_API_KEY")  # Fallback

CAPITAL_API_KEY = os.getenv("CAPITAL_API_KEY")
CAPITAL_API_PASSWORD = os.getenv("CAPITAL_API_PASSWORD")
CAPITAL_IDENTIFIER = os.getenv("CAPITAL_IDENTIFIER")
CAPITAL_API_URL = "https://demo-api-capital.backend-capital.com/api/v1"

# Trading Settings
TRADE_INTERVAL = 300  # 5 minutes
TP_MOVE_PERCENT = 0.5 / 100  # Move TP by 0.5% when price moves
BREAKEVEN_TRIGGER = 1 / 100  # Move SL to breakeven at 1% profit
TP_RATIO = 0.02  # Take Profit ratio (example value)
RISK_PERCENT = 1  # Risk percentage (example value)

# Symbols & Lot Sizes
if os.getenv("USE_ALL_MARKETS") == "True":
    SYMBOLS = [
        "BTCUSD", "ETHUSD", "XRPUSD", "LTCUSD", "ADAUSD", "SOLUSD", "DOGEUSD", "DOTUSD", "MATICUSD", "BNBUSD",  # Crypto
        "XAUUSD", "XAGUSD", "OIL", "NATGAS", "GER40"  # Commodities & Indices
    ]
else:
    SYMBOLS = os.getenv("SYMBOLS", "BTCUSD,ETHUSD").split(",")  # Use defined symbols from .env

LOT_SIZES = {
    "BTCUSD": 0.001, "ETHUSD": 0.01, "ADAUSD": 1.0, "XRPUSD": 100, "LTCUSD": 1,
    "SOLUSD": 10, "DOGEUSD": 1000, "DOTUSD": 10, "MATICUSD": 100, "BNBUSD": 1
}
DEFAULT_LOT_SIZE = 0.01

# Enhanced Logging Configuration
LOG_FILE = "trading_bot.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# Create a logger for detailed API interactions
api_logger = logging.getLogger('api_interactions')
api_logger.setLevel(logging.DEBUG)
api_handler = logging.FileHandler('api_debug.log', mode="w", encoding="utf-8")
api_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
api_logger.addHandler(api_handler)

# Initialize logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

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

# Verify position details
def verify_position(deal_reference, cst, x_security):
    """Verify that a position was created with the correct TP/SL levels"""
    # Wait for position to be processed
    time.sleep(2)
    
    url = f"{CAPITAL_API_URL}/confirms/{deal_reference}"
    headers = {
        "X-CAP-API-KEY": get_api_key(),
        "CST": cst,
        "X-SECURITY-TOKEN": x_security,
        "Content-Type": "application/json"
    }
    
    try:
        session = create_session()
        api_logger.debug(f"Position verification request for {deal_reference}")
        response = session.get(url, headers=headers)
        
        if response.status_code == 200:
            position_data = response.json()
            api_logger.debug(f"Position verification response: {json.dumps(position_data)}")
            
            # Extract the affected deal ID from the confirmation
            deal_id = None
            if "affectedDeals" in position_data and position_data["affectedDeals"]:
                for deal in position_data["affectedDeals"]:
                    if deal.get("status") == "OPENED":
                        deal_id = deal.get("dealId")
                        break
            
            if not deal_id:
                deal_id = position_data.get("dealId")
            
            if deal_id:
                # Get full position details
                full_position = get_position_details(deal_id, cst, x_security)
                
                if full_position:
                    # Check if TP was set correctly
                    if "limitLevel" in full_position:
                        logging.info(f"✅ Take Profit confirmed: {full_position['limitLevel']}")
                    else:
                        logging.warning("⚠️ Take Profit not found in position data")
                        
                        # Set the TP if it's missing
                        symbol = position_data.get("epic")
                        price = float(position_data.get("level", 0))
                        direction = position_data.get("direction")
                        
                        if symbol and price > 0 and direction:
                            # Calculate TP based on direction
                            tp = round(price * (0.995 if direction == "SELL" else 1.005), 2)
                            
                            # Set the TP directly using the deal ID
                            set_take_profit_after_open(deal_id, symbol, price, direction, cst, x_security)
                    
                    # Check if SL was set correctly
                    if "stopLevel" in full_position:
                        logging.info(f"✅ Stop Loss confirmed: {full_position['stopLevel']}")
                    else:
                        logging.warning("⚠️ Stop Loss not found in position data")
            else:
                # Fall back to the original confirmation data
                if "limitLevel" in position_data:
                    logging.info(f"✅ Take Profit confirmed: {position_data['limitLevel']}")
                else:
                    logging.warning("⚠️ Take Profit not found in position data")
                    
                    # Try to set TP directly
                    symbol = position_data.get("epic")
                    price = float(position_data.get("level", 0))
                    direction = position_data.get("direction")
                    
                    if symbol and price > 0 and direction:
                        # Calculate TP based on direction
                        tp = round(price * (0.995 if direction == "SELL" else 1.005), 2)
                        
                        # Set the TP
                        update_take_profit(symbol, tp, cst, x_security)
                
                if "stopLevel" in position_data:
                    logging.info(f"✅ Stop Loss confirmed: {position_data['stopLevel']}")
                else:
                    logging.warning("⚠️ Stop Loss not found in position data")
        else:
            error_data = "Unknown error"
            try:
                error_data = response.json()
            except:
                error_data = response.text
                
            logging.error(f"❌ Failed to verify position: {error_data}")
    except Exception as e:
        logging.error(f"❌ Position verification exception: {str(e)}", exc_info=True)
    return position_data

def verify_position_and_orders(deal_reference, cst, x_security):
    """Verify the position was created and check for missing TP"""
    position_response = verify_position(deal_reference, cst, x_security)
    if position_response and "affectedDeals" in position_response:
        deal_id = position_response["affectedDeals"][0]["dealId"]

        # Check for existing TP
        position_details = get_position_details(deal_id, cst, x_security)
        if position_details and "limitLevel" not in position_details:
            logging.warning(f"⚠️ No Take Profit found for {deal_id}, setting one...")
            entry_price = float(position_details["level"])
            direction = position_details["direction"]

            # Calculate new TP
            tp = round(entry_price * (1.005 if direction == "BUY" else 0.995), 2)
            set_take_profit_by_deal_id(deal_id, tp, cst, x_security)

def get_working_orders():
    """Fetch all working orders"""
    cst, x_security = authenticate()
    if not cst or not x_security:
        return {}

    url = f"{CAPITAL_API_URL}/workingorders"
    headers = {
        "X-CAP-API-KEY": get_api_key(),
        "CST": cst,
        "X-SECURITY-TOKEN": x_security,
        "Content-Type": "application/json"
    }
    
    try:
        session = create_session()
        response = session.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            logging.error(f"❌ Failed to fetch working orders: {response.text}")
            return {}
    except Exception as e:
        logging.error(f"❌ Exception fetching working orders: {str(e)}", exc_info=True)
        return {}

def create_take_profit_order(deal_id, position):
    """Create a take profit order for a given position"""
    direction = position.get("direction")
    level = float(position.get("level"))
    
    # Calculate take profit level (example calculation)
    if direction == "BUY":
        tp_level = round(level * 1.02, 2)  # 2% profit for buy
    else:
        tp_level = round(level * 0.98, 2)  # 2% profit for sell
    
    order_data = {
        "epic": position.get("epic"),
        "dealId": deal_id,
        "direction": "SELL" if direction == "BUY" else "BUY",  # Opposite of position direction
        "level": tp_level,
        "type": "LIMIT",
        "timeInForce": "GOOD_TILL_CANCELLED"
    }
    
    cst, x_security = authenticate()
    if not cst or not x_security:
        logging.error("❌ Authentication failed. Cannot create take profit order.")
        return
    
    url = f"{CAPITAL_API_URL}/workingorders"
    headers = {
        "X-CAP-API-KEY": get_api_key(),
        "CST": cst,
        "X-SECURITY-TOKEN": x_security,
        "Content-Type": "application/json"
    }
    
    try:
        session = create_session()
        response = session.post(url, headers=headers, json=order_data)
        
        if response.status_code == 200:
            logging.info(f"✅ Take Profit order created for position {deal_id}")
        else:
            logging.error(f"❌ Failed to create Take Profit order: {response.json()}")
    except Exception as e:
        logging.error(f"❌ Exception creating take profit order: {str(e)}", exc_info=True)

# Calculate ATR (Average True Range)
def get_atr(symbol, period=14):
    """
    Calculate the Average True Range (ATR) for a given symbol.
    """
    data = get_market_data(symbol, resolution="MINUTE_5")
    if not data or "prices" not in data:
        return 0

    df = pd.DataFrame(data["prices"])
    df["high"] = df["highPrice"].apply(lambda x: x.get("bid", 0))
    df["low"] = df["lowPrice"].apply(lambda x: x.get("bid", 0))
    df["close"] = df["closePrice"].apply(lambda x: x.get("bid", 0))

    df["tr"] = df[["high", "low", "close"]].max(axis=1) - df[["high", "low", "close"]].min(axis=1)
    atr = df["tr"].rolling(window=period).mean().iloc[-1]
    return atr

# Execute Trades
def verify_tp(deal_id, tp_price):
    """Ensure TP exists for an open position, set if missing"""
    cst, x_security = authenticate()
    if not cst or not x_security:
        return

    url = f"{CAPITAL_API_URL}/positions/{deal_id}"
    headers = {
        "X-CAP-API-KEY": get_api_key(),
        "CST": cst,
        "X-SECURITY-TOKEN": x_security,
        "Content-Type": "application/json"
    }

    try:
        session = create_session()
        response = session.get(url, headers=headers)

        if response.status_code == 200:
            position = response.json()
            if "profitLevel" not in position or position["profitLevel"] is None:
                logging.warning(f"⚠️ No Take Profit found for {deal_id}, setting one...")
                update_tp(deal_id, tp_price)
        else:
            logging.error(f"❌ Failed to verify TP: {response.text}")
    except Exception as e:
        logging.error(f"❌ Verify TP exception: {str(e)}", exc_info=True)

def trade_action(symbol, action, price, mode):
    """Execute or modify a trade"""
    cst, x_security = authenticate()
    if not cst or not x_security:
        logging.error("❌ Authentication failed. Cannot execute trade.")
        return

    lot_size = LOT_SIZES.get(symbol, DEFAULT_LOT_SIZE)

    # Get min required distance from broker API
    min_distance, _ = get_min_distance(symbol)  # Extract the minimum distance value
    if min_distance is None:
        logging.error(f"❌ Failed to get minimum TP/SL distance for {symbol}. Skipping trade.")
        return

    # Ensure min_distance is a single float value
    if isinstance(min_distance, (list, np.ndarray)):
        min_distance = float(min_distance[0])

    # Calculate TP & SL
    tp = round(float(price) * (1.005 if action == "BUY" else 0.995), 2)
    sl = round(float(price) * (0.995 if action == "BUY" else 1.005), 2)

    # Ensure TP & SL meet minimum distance
    if abs(float(tp) - float(price)) < float(min_distance):
        tp = round(price + (min_distance if action == "BUY" else -min_distance), 2)

    if abs(float(sl) - float(price)) < float(min_distance):
        sl = round(price - (min_distance if action == "BUY" else -min_distance), 2)

    # Updated payload for Capital.com API
    payload = {
        "epic": symbol,
        "direction": action,
        "size": lot_size,
        "stopLevel": sl,
        "profitLevel": tp,  # ✅ Ensure TP is correctly set
        "guaranteedStop": False,
        "trailingStop": False,
        "forceOpen": True
    }

    logging.info(f"🚀 Sending trade request: {json.dumps(payload)}")

    url = f"{CAPITAL_API_URL}/positions"
    headers = {
        "X-CAP-API-KEY": get_api_key(),
        "CST": cst,
        "X-SECURITY-TOKEN": x_security,
        "Content-Type": "application/json"
    }

    try:
        session = create_session()
        response = session.post(url, headers=headers, json=payload)

        if response.status_code == 200:
            response_data = response.json()
            logging.info(f"✅ Trade Executed: {action} {symbol} at {price} | TP: {tp} | SL: {sl}")
            logging.info(f"Response: {json.dumps(response_data)}")

            # Verify the position was created with TP
            deal_reference = response_data.get("dealReference")
            if deal_reference:
                verify_position_and_orders(deal_reference, cst, x_security)
            else:
                logging.warning("⚠️ No deal reference returned. Cannot verify position.")

            # 🔥 Verify TP after trade execution
            deal_id = response_data.get("dealId")
            if deal_id:
                verify_tp(deal_id, tp)
        else:
            logging.error(f"❌ Trade Execution Failed for {symbol}: {response.text}")
    except Exception as e:
        logging.error(f"❌ Trade execution exception: {str(e)}", exc_info=True)

def set_trailing_stop(symbol, tp1, sl, action):
    """
    Activate trailing stop when TP1 is hit.
    """
    while True:
        price = get_latest_price(symbol)
        if (action == "BUY" and price >= tp1) or (action == "SELL" and price <= tp1):
            new_sl = price - 0.5 if action == "BUY" else price + 0.5
            set_stop_loss(symbol, new_sl)
            logging.info(f"🔄 Trailing SL Activated: {symbol} at {new_sl}")
            break
        time.sleep(10)

def set_stop_loss(symbol, new_sl):
    """
    Update the stop loss level for an open position.
    """
    cst, x_security = authenticate()
    if not cst or not x_security:
        return

    # Fetch the open positions
    url = f"{CAPITAL_API_URL}/positions"
    headers = {
        "X-CAP-API-KEY": get_api_key(),
        "CST": cst,
        "X-SECURITY-TOKEN": x_security,
        "Content-Type": "application/json"
    }

    try:
        session = create_session()
        response = session.get(url, headers=headers)
        if response.status_code != 200:
            logging.error(f"❌ Failed to fetch open positions: {response.json()}")
            return

        positions = response.json().get("positions", [])
        for trade in positions:
            if trade["epic"] == symbol:
                deal_id = trade["dealId"]
                logging.info(f"🔄 Updating SL for {symbol} | New SL: {new_sl}")

                update_payload = {
                    "stopLevel": new_sl  # Updating SL level
                }

                update_url = f"{CAPITAL_API_URL}/positions/{deal_id}"
                update_response = session.put(update_url, headers=headers, json=update_payload)

                if update_response.status_code == 200:
                    logging.info(f"✅ SL Updated Successfully for {symbol} | New SL: {new_sl}")
                else:
                    logging.error(f"❌ Failed to update SL for {symbol}: {update_response.json()}")
    except Exception as e:
        logging.error(f"❌ Update SL exception: {str(e)}", exc_info=True)

def get_min_distance(symbol):
    """
    Fetches the minimum stop loss and take profit distance for the given symbol.
    Ensures the function always returns two values.
    """
    cst, x_security = authenticate()
    if not cst or not x_security:
        return 0.1, 0.5  # Always return two values to avoid unpacking errors

    url = f"{CAPITAL_API_URL}/markets/{symbol}"
    headers = {
        "X-CAP-API-KEY": get_api_key(),
        "CST": cst,
        "X-SECURITY-TOKEN": x_security,
        "Content-Type": "application/json"
    }

    try:
        session = create_session()
        response = session.get(url, headers=headers)
        if response.status_code == 200:
            market_data = response.json()
            min_distance = float(market_data.get("minControlledRiskStopDistance", 0.1))  # Use default if missing
            max_distance = float(market_data.get("maxStopDistance", 0.5))  # Ensure two values are returned
            logging.info(f"✅ {symbol} Min SL/TP Distance: {min_distance}, Max SL Distance: {max_distance}")
            return min_distance, max_distance  # Always return a tuple with two values
        else:
            logging.error(f"❌ Failed to fetch min SL/TP distance for {symbol}: {response.json()}")
            return 0.1, 0.5  # Prevent errors by always returning two values
    except Exception as e:
        logging.error(f"❌ Get min distance exception: {str(e)}", exc_info=True)
        return 0.1, 0.5  # Prevent errors by always returning two values

def get_min_lot_size(symbol):
    """
    Fetches the minimum lot size required by Capital.com API for a given symbol.
    """
    cst, x_security = authenticate()
    if not cst or not x_security:
        return DEFAULT_LOT_SIZE

    url = f"{CAPITAL_API_URL}/markets/{symbol}"
    headers = {
        "X-CAP-API-KEY": get_api_key(),
        "CST": cst,
        "X-SECURITY-TOKEN": x_security,
        "Content-Type": "application/json"
    }

    try:
        session = create_session()
        response = session.get(url, headers=headers)
        if response.status_code == 200:
            market_data = response.json()
            min_lot_size = float(market_data.get("minDealSize", DEFAULT_LOT_SIZE))  # Default to DEFAULT_LOT_SIZE if missing
            logging.info(f"✅ {symbol} Min Lot Size: {min_lot_size}")
            return min_lot_size
        else:
            error_data = "Unknown error"
            try:
                error_data = response.json()
            except:
                error_data = response.text
                
            logging.error(f"❌ Failed to fetch min lot size for {symbol}: {error_data}")
            return DEFAULT_LOT_SIZE
    except Exception as e:
        logging.error(f"❌ Get min lot size exception: {str(e)}", exc_info=True)
        return DEFAULT_LOT_SIZE

# Update take profit for an existing position
def update_take_profit(symbol, new_tp, cst, x_security):
    """Update the take profit level for an existing position"""
    url = f"{CAPITAL_API_URL}/positions"
    headers = {
        "X-CAP-API-KEY": get_api_key(),
        "CST": cst,
        "X-SECURITY-TOKEN": x_security,
        "Content-Type": "application/json"
    }

    try:
        session = create_session()
        response = session.get(url, headers=headers)
        
        if response.status_code == 200:
            positions = response.json().get("positions", [])
            
            for position in positions:
                if position.get("epic") == symbol:
                    position_id = position.get("dealId")

                    update_url = f"{CAPITAL_API_URL}/positions/{position_id}"
                    update_payload = {"limitLevel": new_tp}
                    
                    update_response = session.put(update_url, headers=headers, json=update_payload)
                    
                    if update_response.status_code == 200:
                        logging.info(f"✅ Updated TP for {symbol} to {new_tp}")
                    else:
                        logging.error(f"❌ Failed to update TP: {update_response.text}")
                    break
            else:
                logging.warning(f"⚠️ No open position found for {symbol}")
        else:
            logging.error(f"❌ Failed to fetch positions: {response.text}")
    except Exception as e:
        logging.error(f"❌ Exception in update_take_profit: {str(e)}")

def set_take_profit_after_open(deal_id, symbol, entry_price, direction, cst, x_security):
    """Set take profit after position is opened"""
    # Calculate TP level
    tp = round(entry_price * (0.995 if direction == "SELL" else 1.005), 2)
    
    # Get min required distance from broker API
    min_distance = get_min_distance(symbol)
    if min_distance is None:
        logging.error(f"❌ Failed to get minimum TP distance for {symbol}. Using default.")
        min_distance = 1.0
    
    # Ensure TP meets minimum distance
    if abs(tp - entry_price) < min_distance:
        tp = round(entry_price + (min_distance if direction == "BUY" else -min_distance), 2)
    
    url = f"{CAPITAL_API_URL}/positions/{deal_id}"
    headers = {
        "X-CAP-API-KEY": get_api_key(),
        "CST": cst,
        "X-SECURITY-TOKEN": x_security,
        "Content-Type": "application/json"
    }
    
    payload = {"limitLevel": tp}
    
    try:
        session = create_session()
        logging.info(f"🔄 Setting TP for {symbol} to {tp} (Deal ID: {deal_id})")
        response = session.put(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            logging.info(f"✅ Take Profit set after position open: {tp}")
            return True
        else:
            error_data = "Unknown error"
            try:
                error_data = response.json()
            except:
                error_data = response.text
                
            logging.error(f"❌ Failed to set take profit: {error_data}")
            return False
    except Exception as e:
        logging.error(f"❌ Set TP exception: {str(e)}")
        return False

def set_take_profit_by_deal_id(deal_id, tp_level, cst, x_security):
    """Set take profit for a specific deal ID"""
    url = f"{CAPITAL_API_URL}/positions/{deal_id}"
    headers = {
        "X-CAP-API-KEY": get_api_key(),
        "CST": cst,
        "X-SECURITY-TOKEN": x_security,
        "Content-Type": "application/json"
    }
    
    payload = {"limitLevel": tp_level}
    
    try:
        session = create_session()
        logging.info(f"🔄 Setting TP for deal {deal_id} to {tp_level}")
        response = session.put(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            logging.info(f"✅ Take Profit set for deal {deal_id}: {tp_level}")
            return True
        else:
            error_data = "Unknown error"
            try:
                error_data = response.json()
            except:
                error_data = response.text
                
            logging.error(f"❌ Failed to set take profit: {error_data}")
            return False
    except Exception as e:
        logging.error(f"❌ Set TP exception: {str(e)}")
        return False

def fix_missing_take_profits():
    """Check all open positions and add take profit orders to any that are missing them"""
    cst, x_security = authenticate()
    if not cst or not x_security:
        logging.error("❌ Authentication failed. Cannot fix take profits.")
        return

    url = f"{CAPITAL_API_URL}/positions"
    headers = {
        "X-CAP-API-KEY": get_api_key(),
        "CST": cst,
        "X-SECURITY-TOKEN": x_security,
        "Content-Type": "application/json"
    }
    
    try:
        session = create_session()
        response = session.get(url, headers=headers)
        
        if response.status_code == 200:
            positions = response.json().get("positions", [])
            
            for position in positions:
                deal_id = position.get("dealId")
                symbol = position.get("epic")
                direction = position.get("direction")
                entry_price = float(position.get("level", 0))
                
                # Check if TP is missing
                if "limitLevel" not in position or position["limitLevel"] is None:
                    logging.info(f"🔍 Found position without TP: {symbol} {direction} at {entry_price}")
                    
                    # Calculate TP based on direction
                    tp = round(entry_price * (0.995 if direction == "SELL" else 1.005), 2)
                    
                    # Get min required distance
                    min_distance = get_min_distance(symbol)
                    if min_distance is None:
                        min_distance = 1.0
                    
                    # Ensure TP meets minimum distance
                    if abs(tp - entry_price) < min_distance:
                        tp = round(entry_price + (min_distance if direction == "BUY" else -min_distance), 2)
                    
                    # Set the TP
                    set_take_profit_by_deal_id(deal_id, tp, cst, x_security)
        else:
            error_data = "Unknown error"
            try:
                error_data = response.json()
            except:
                error_data = response.text
                
            logging.error(f"❌ Failed to fetch positions: {error_data}")
    except Exception as e:
        logging.error(f"❌ Fix take profits exception: {str(e)}", exc_info=True)

# Flask Webhook
app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()

        if not data:
            logging.error("❌ Webhook received empty payload")
            return jsonify({"status": "error", "message": "Invalid webhook data"}), 400

        symbol = data.get("symbol")
        action = data.get("action")
        price = data.get("price")

        if not symbol or not action or price is None:
            logging.error(f"❌ Invalid webhook data: {data}")
            return jsonify({"status": "error", "message": "Invalid webhook parameters"}), 400

        price = float(price)
        logging.info(f"🌐 Webhook Triggered: {symbol} | {action} | {price}")
        
        trade_action(symbol, action, price, "SCALP")

        return jsonify({"status": "success", "message": f"✅ Trade executed: {action} {symbol} at {price}"}), 200
    except Exception as e:
        logging.error(f"❌ Webhook processing error: {str(e)}")
        return jsonify({"status": "error", "message": "Webhook processing error"}), 500

@app.route('/api/logs', methods=['GET'])
def get_logs():
    try:
        with open(LOG_FILE, 'r') as file:
            logs = file.read()
        return logs, 200
    except Exception as e:
        logging.error(f"Error reading log file: {str(e)}")
        return "Error reading log file", 500

# Authenticate with Capital.com API with rate limiting and caching
key = Fernet.generate_key()
cipher_suite = Fernet(key)

def encrypt_api_key(api_key):
    return cipher_suite.encrypt(api_key.encode()).decode()

def decrypt_api_key(encrypted_key):
    """
    Decrypts the API key using the stored encryption key.
    """
    encryption_key = os.getenv("ENCRYPTION_KEY")
    if not encryption_key:
        logging.critical("❌ ENCRYPTION_KEY is missing from .env file!")
        return None

    try:
        cipher_suite = Fernet(encryption_key.encode())
        return cipher_suite.decrypt(encrypted_key.encode()).decode()
    except Exception as e:
        logging.critical(f"❌ API Key Decryption Failed: {e}")
        return None

def authenticate(retries=3, delay=10):
    """Authenticate with Capital.com API with retry on failure."""
    headers = {
        "Content-Type": "application/json",
        "X-CAP-API-KEY": get_api_key(),
    }
    payload = {
        "identifier": os.getenv("CAPITAL_IDENTIFIER"),
        "password": os.getenv("CAPITAL_API_PASSWORD")
    }

    for attempt in range(retries):
        try:
            response = requests.post(f"{CAPITAL_API_URL}/session", headers=headers, json=payload)
            response_data = response.json()

            if response.status_code == 200:
                logging.info("✅ Authentication successful")
                cst = response_data.get("cst", "")
                x_security = response_data.get("x-security-token", "")
                logging.debug(f"CST: {cst[:5]}... | X-SECURITY-TOKEN: {x_security[:5]}...")
                return cst, x_security
            elif "error.too-many.requests" in response.text:
                logging.warning(f"⚠️ Too many requests. Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                logging.error(f"❌ Authentication Failed: {response.text}")
                return None, None
        except Exception as e:
            logging.error(f"❌ Authentication Exception: {str(e)}", exc_info=True)

    logging.error("❌ Max retries reached. Authentication failed.")
    return None, None

def check_available_markets():
    """Fetch all available markets from Capital.com API and log the full response for debugging."""
    retries = 3
    delay = 10  # seconds

    for attempt in range(retries):
        cst, x_security = authenticate()

        if not cst or not x_security:
            logging.error("❌ Authentication failed. Cannot fetch markets.")
            time.sleep(delay)
            continue

        url = f"{CAPITAL_API_URL}/markets"
        headers = {
            "X-CAP-API-KEY": get_api_key(),
            "CST": cst,
            "X-SECURITY-TOKEN": x_security,
            "Content-Type": "application/json"
        }

        session = requests.Session()
        
        try:
            response = session.get(url, headers=headers)

            # ✅ Log the full response (including status code & text)
            logging.error(f"📜 Market API Response ({response.status_code}): {response.text}")

            if response.status_code == 200:
                markets = response.json().get("markets", [])
                available_symbols = [market["epic"] for market in markets]
                logging.info(f"✅ Available Markets Fetched Successfully: {available_symbols}")
                return available_symbols
            
            elif response.status_code == 403:
                logging.error("❌ API Key Invalid or Lacks Permissions! Check your Capital.com API key settings.")
                return None

            elif response.status_code == 429:
                logging.warning("⚠️ Too many requests. Retrying in 10 seconds...")
                time.sleep(10)

            else:
                logging.error(f"❌ Failed to fetch markets (Status {response.status_code}): {response.text}")
                return None

        except requests.exceptions.RequestException as e:
            logging.error(f"❌ Exception while fetching markets: {e}")

        logging.warning(f"⚠️ Retry {attempt + 1}/{retries} failed. Retrying in {delay} seconds...")
        time.sleep(delay)

    logging.error("❌ Max retries reached. Could not fetch markets.")
    return None

# Fetch Market Data with caching
def get_market_data(symbol, resolution="MINUTE_5"):
    cache_key = f"market_data_{symbol}_{resolution}"
    
    # Check if we have valid cached data
    if cache_key in api_cache and time.time() < api_cache[cache_key]["expiry"]:
        return api_cache[cache_key]["data"]
    
    cst, x_security = authenticate()
    if not cst or not x_security:
        return None

    url = f"{CAPITAL_API_URL}/prices/{symbol}?resolution={resolution}&max=100"
    headers = {"X-CAP-API-KEY": get_api_key(), "CST": cst, "X-SECURITY-TOKEN": x_security, "Content-Type": "application/json"}
    
    try:
        session = create_session()
        api_logger.debug(f"Market data request for {symbol}")
        time.sleep(1)  # ✅ Add delay to prevent rate limits
        response = session.get(url, headers=headers)
        response.raise_for_status()  # ✅ Raise exception for bad status codes
        data = response.json()
        
        # Cache the data
        api_cache[cache_key] = {
            "data": data,
            "expiry": time.time() + API_CACHE_TTL
        }
        
        return data
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ API Request Failed: {e}")
        return None

# Check for high impact news
def check_high_impact_news():
    """
    Placeholder function to check for high impact news.
    Returns True if high impact news is detected, otherwise False.
    """
    # Implement actual logic to check for high impact news
    return False

# Analyze Market Trends with improved error handling
def analyze_market(symbol):
    """Analyzes market conditions & blocks trades in extreme conditions."""
    data = get_market_data(symbol)
    if not data or "prices" not in data:
        return "HOLD", None, None

    df = pd.DataFrame(data["prices"])
    try:
        df["high"] = df["highPrice"].apply(lambda x: x.get("bid", 0))
        df["low"] = df["lowPrice"].apply(lambda x: x.get("bid", 0))
        df["close"] = df["closePrice"].apply(lambda x: x.get("bid", 0))
        df.dropna(inplace=True)
        df["ATR"] = talib.ATR(df["high"], df["low"], df["close"], timeperiod=14)
    except KeyError as e:
        logging.error(f"❌ Missing required price columns for {symbol}: {e}")
        return "HOLD", None, None

    latest_price = df["close"].iloc[-1]
    atr_value = df["ATR"].iloc[-1]

    if atr_value > df["ATR"].mean() * 2:
        logging.warning(f"⚠️ High volatility detected on {symbol}. Proceeding with caution.")

    if check_high_impact_news():
        logging.warning(f"⚠️ High-impact news detected, but proceeding with trade.")

    return "BUY" if latest_price > df["close"].mean() else "SELL", latest_price, "SCALP"

def get_position_details(deal_id, cst, x_security):
    """Get full details of an open position including TP/SL levels"""
    # First get all positions to find the one with matching dealId
    url = f"{CAPITAL_API_URL}/positions"
    headers = {
        "X-CAP-API-KEY": get_api_key(),
        "CST": cst,
        "X-SECURITY-TOKEN": x_security,
        "Content-Type": "application/json"
    }
    
    try:
        session = create_session()
        response = session.get(url, headers=headers)
        
        if response.status_code == 200:
            positions = response.json().get("positions", [])
            
            # Find the position with matching dealId
            for position in positions:
                if position.get("dealId") == deal_id:
                    return position
                
            # If we get here, we didn't find the position
            logging.warning(f"⚠️ Position with dealId {deal_id} not found")
            return None
        else:
            logging.error(f"❌ Failed to get positions: {response.text}")
            return None
    except Exception as e:
        logging.error(f"❌ Position details exception: {str(e)}")
        return None

# Get the latest price for a given symbol
def get_latest_price(symbol):
    """
    Fetch the latest price for a given symbol.
    """
    data = get_market_data(symbol, resolution="MINUTE_1")
    if not data or "prices" not in data:
        return 0

    df = pd.DataFrame(data["prices"])
    df["close"] = df["closePrice"].apply(lambda x: x.get("bid", 0))
    return df["close"].iloc[-1]

def monitor_trades():
    while True:
        cst, x_security = authenticate()
        if not cst or not x_security:
            time.sleep(TRADE_INTERVAL)
            continue

        url = f"{CAPITAL_API_URL}/positions"
        headers = {"X-CAP-API-KEY": get_api_key(), "CST": cst, "X-SECURITY-TOKEN": x_security, "Content-Type": "application/json"}
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            for trade in response.json()["positions"]:
                symbol = trade["epic"]
                entry_price = float(trade["level"])
                current_price = get_latest_price(symbol)

                if not current_price:
                    continue

                # Dynamic TP update
                new_tp = round(entry_price * (1 + TP_MOVE_PERCENT), 2)
                if new_tp > float(trade["profitLevel"]):
                    logging.info(f"🔄 Updating TP for {symbol}: {new_tp}")
                    update_tp(symbol, new_tp)

                # Move SL to breakeven if profit exceeds threshold
                if current_price > entry_price * (1 + BREAKEVEN_TRIGGER):
                    new_sl = entry_price
                    logging.info(f"🔄 Moving SL to breakeven for {symbol}: {new_sl}")
                    set_stop_loss(symbol, new_sl)

        time.sleep(TRADE_INTERVAL)

def get_open_positions(cst=None, x_security=None):
    """Fetch all open positions with authentication handling."""
    if not cst or not x_security:
        cst, x_security = authenticate()
        if not cst or not x_security:
            logging.error("❌ Authentication failed. Cannot fetch open positions.")
            return []

    url = f"{CAPITAL_API_URL}/positions"
    headers = {
        "X-CAP-API-KEY": get_api_key(),
        "CST": cst,
        "X-SECURITY-TOKEN": x_security,
        "Content-Type": "application/json"
    }

    try:
        session = create_session()
        response = session.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get("positions", [])
        else:
            logging.error(f"❌ Failed to fetch open positions: {response.json()}")
            return []
    except Exception as e:
        logging.error(f"❌ Get open positions exception: {str(e)}", exc_info=True)
        return []

# Fetch available markets dynamically
SYMBOLS = check_available_markets()

# Ensure SYMBOLS contains actual assets; otherwise, use fallback
if not SYMBOLS or len(SYMBOLS) == 0:
    logging.warning("⚠️ No available symbols retrieved from API. Using predefined list.")
    SYMBOLS = [
        "BTCUSD", "ETHUSD", "XRPUSD", "LTCUSD", "ADAUSD", "SOLUSD", "DOGEUSD", "DOTUSD", "MATICUSD", "BNBUSD",
        "XAUUSD", "XAGUSD", "OIL", "NATGAS", "GER40"
    ]  # ✅ Fallback: Full Market List

# Run market check immediately for debugging
available_markets = check_available_markets()
if available_markets:
    logging.info(f"Available markets: {available_markets}")
else:
    logging.error("Failed to fetch available markets.")

# Main Trading Loop
def main():
    # Fix any missing take profits on startup
    fix_missing_take_profits()
    
    # Start the monitoring thread
    threading.Thread(target=monitor_trades, daemon=True).start()
    
    while True:
        try:
            logging.info("📊 Starting market analysis cycle...")
            for symbol in SYMBOLS:
                trend, latest_price, mode = analyze_market(symbol)
                if trend in ["BUY", "SELL"] and latest_price:
                    cst, x_security = authenticate()
                    open_positions = get_open_positions(cst, x_security)
                    for pos in open_positions:
                        epic = pos.get("epic")
                        if epic and epic == symbol and pos["direction"] != trend:
                            logging.warning(f"⚠️ Existing position in opposite direction for {symbol}. Closing old position and opening a new one.")
                            close_trade(pos["dealId"], cst, x_security)  # ✅ Close old position
                    trade_action(symbol, trend, latest_price, mode)

            time.sleep(TRADE_INTERVAL)
        except Exception as e:
            logging.error(f"❌ Main loop exception: {str(e)}", exc_info=True)
# Start Flask Webhook & Trading Bot
if __name__ == "__main__":
    from waitress import serve
    logging.info("🚀 Starting production server with Waitress...")
    serve(app, host="0.0.0.0", port=5000)

def close_trade(deal_id, cst, x_security):
    """Close an open trade by deal ID"""
    url = f"{CAPITAL_API_URL}/positions/otc/{deal_id}"
    headers = {
        "X-CAP-API-KEY": get_api_key(),
        "CST": cst,
        "X-SECURITY-TOKEN": x_security,
        "Content-Type": "application/json"
    }
    
    payload = {
        "dealId": deal_id,
        "direction": "SELL"  # Assuming closing a BUY position, adjust as needed
    }
    
    try:
        session = create_session()
        response = session.delete(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            logging.info(f"✅ Trade closed successfully: {deal_id}")
        else:
            error_data = "Unknown error"
            try:
                error_data = response.json()
            except:
                error_data = response.text
                
            logging.error(f"❌ Failed to close trade: {error_data}")
    except Exception as e:
        logging.error(f"❌ Close trade exception: {str(e)}", exc_info=True)

def update_tp(deal_id, new_tp):
    """Update TP for an existing position"""
    cst, x_security = authenticate()
    if not cst or not x_security:
        return

    url = f"{CAPITAL_API_URL}/positions/{deal_id}"
    headers = {
        "X-CAP-API-KEY": get_api_key(),
        "CST": cst,
        "X-SECURITY-TOKEN": x_security,
        "Content-Type": "application/json"
    }

    payload = {"limitLevel": new_tp}

    try:
        session = create_session()
        response = session.put(url, headers=headers, json=payload)

        if response.status_code == 200:
            logging.info(f"✅ Take Profit updated for {deal_id}: {new_tp}")
        else:
            logging.error(f"❌ Failed to update Take Profit: {response.text}")
    except Exception as e:
        logging.error(f"❌ Update TP exception: {str(e)}", exc_info=True)

def calculate_indicators(df):
    """
    Compute VWAP, Bollinger Bands, and Stochastic RSI.
    """
    df["VWAP"] = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()

    # Bollinger Bands
    rolling_mean = df["close"].rolling(window=20).mean()
    rolling_std = df["close"].rolling(window=20).std()
    df["BB_upper"] = rolling_mean + (2 * rolling_std)
    df["BB_lower"] = rolling_mean - (2 * rolling_std)

    # Stochastic RSI using talib
    df["stoch_rsi"] = talib.STOCHRSI(df["close"], timeperiod=14)

    return df

def get_random_symbol():
    """
    Get a random symbol from the SYMBOLS list.
    """
    return random.choice(SYMBOLS)

def normalize_data(df):
    """
    Normalize the data using numpy.
    """
    df["normalized_close"] = (df["close"] - np.mean(df["close"])) / np.std(df["close"])
    return df

def get_dynamic_lot_size(symbol):
    """
    Adjust lot size dynamically based on ATR & balance.
    """
    atr = get_atr(symbol)
    balance = get_account_balance()
    
    def get_account_balance():
        """
        Fetch the current account balance from the Capital.com API.
        """
        cst, x_security = authenticate()
        if not cst or not x_security:
            return 0
    
        url = f"{CAPITAL_API_URL}/accounts"
        headers = {
            "X-CAP-API-KEY": get_api_key(),
            "CST": cst,
            "X-SECURITY-TOKEN": x_security,
            "Content-Type": "application/json"
        }
    
        try:
            session = create_session()
            response = session.get(url, headers=headers)
            if response.status_code == 200:
                account_data = response.json()
                return float(account_data.get("balance", 0))
            else:
                logging.error(f"❌ Failed to fetch account balance: {response.json()}")
                return 0
        except Exception as e:
            logging.error(f"❌ Get account balance exception: {str(e)}", exc_info=True)
            return 0
    risk_factor = 0.001 if balance > 5000 else 0.0005  # Risk smaller if balance <5000

    return round(risk_factor * atr, 3)

def auto_mode_switch(symbol):
    """
    Automatically switch between Scalping & Swing Mode based on market conditions.
    """
    atr = get_atr(symbol)
    
    if atr < 50:
        return "SCALP"
    elif atr > 200:
        return "SWING"
    else:
        return "BALANCED"

def hedge_trade(symbol, direction, trade_id):
    """Places a hedge order in case of trend reversal to avoid losses."""
    cst, x_security = authenticate()
    if not cst or not x_security:
        return

    lot_size = LOT_SIZES.get(symbol, DEFAULT_LOT_SIZE)

    # Open opposite position
    new_direction = "BUY" if direction == "SELL" else "SELL"
    url = f"{CAPITAL_API_URL}/positions"
    payload = {
        "epic": symbol,
        "direction": new_direction,
        "size": lot_size,
        "forceOpen": True
    }

    headers = {"X-CAP-API-KEY": get_api_key(), "CST": cst, "X-SECURITY-TOKEN": x_security, "Content-Type": "application/json"}
    response = requests.post(url, headers=headers, json=payload)

    if response.status_code == 200:
        logging.info(f"🔄 Hedging {symbol} {new_direction} against {direction} due to trend reversal.")
    else:
        logging.error(f"❌ Hedging Failed for {symbol}: {response.json()}")
repr("")

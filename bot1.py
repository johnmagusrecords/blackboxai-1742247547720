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
CAPITAL_API_URL = "https://demo-api-capital.backend-capital.com/api/v1"

# Trading Settings
TRADE_INTERVAL = 300  # 5 minutes
TP_MOVE_PERCENT = 0.5 / 100  # Move TP by 0.5% when price moves
BREAKEVEN_TRIGGER = 1 / 100  # Move SL to breakeven at 1% profit

# Symbols & Lot Sizes
SYMBOLS = ["BTCUSD", "ETHUSD", "XRPUSD", "LTCUSD", "ADAUSD", "SOLUSD", "DOGEUSD", "DOTUSD", "MATICUSD", "BNBUSD"]
LOT_SIZES = {
    "BTCUSD": 0.001, "ETHUSD": 0.01, "ADAUSD": 0.5, "XRPUSD": 100, "LTCUSD": 1,
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
        "X-CAP-API-KEY": CAPITAL_API_KEY,
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
    """Verify the position was created and check for associated take profit orders"""
    position_response = verify_position(deal_reference, cst, x_security)
    if position_response and "affectedDeals" in position_response:
        deal_id = position_response["affectedDeals"][0]["dealId"]
        
        # Now check for working orders related to this position
        working_orders = get_working_orders()
        
        # Look for take profit orders associated with this position
        tp_order_found = False
        for order in working_orders.get("workingOrders", []):
            if order.get("dealId") == deal_id or order.get("parentDealId") == deal_id:
                if order.get("orderType") == "LIMIT":
                    tp_order_found = True
                    logging.info(f"✅ Take Profit order found for position {deal_id}")
                    break
        
        # If no take profit order found, create one
        if not tp_order_found:
            logging.warning(f"⚠️ No Take Profit order found for position {deal_id}, creating one...")
            create_take_profit_order(deal_id, position_response)

def get_working_orders():
    """Fetch all working orders"""
    cst, x_security = authenticate()
    if not cst or not x_security:
        return {}

    url = f"{CAPITAL_API_URL}/workingorders"
    headers = {
        "X-CAP-API-KEY": CAPITAL_API_KEY,
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
        "X-CAP-API-KEY": CAPITAL_API_KEY,
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

# Execute Trades
def verify_tp(deal_id, tp_price):
    """Checks if TP exists and creates one if missing"""
    cst, x_security = authenticate()
    if not cst or not x_security:
        return

    url = f"{CAPITAL_API_URL}/positions/{deal_id}"
    headers = {
        "X-CAP-API-KEY": CAPITAL_API_KEY,
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
                logging.warning(f"⚠️ No Take Profit found for {deal_id}, creating one...")
                update_tp(deal_id, tp_price)
        else:
            error_data = "Unknown error"
            try:
                error_data = response.json()
            except:
                error_data = response.text
                
            logging.error(f"❌ Failed to verify TP: {error_data}")
    except Exception as e:
        logging.error(f"❌ Verify TP exception: {str(e)}", exc_info=True)

def trade_action(symbol, action, price, mode):
    """Execute or modify a trade"""
    cst, x_security = authenticate()
    if not cst or not x_security:
        logging.error("❌ Authentication failed. Cannot execute trade.")
        return

    # Handle special actions like UPDATE_TP
    if action == "UPDATE_TP":
        update_tp(symbol, price, cst, x_security)
        return

    lot_size = LOT_SIZES.get(symbol, DEFAULT_LOT_SIZE)

    # Get min required distance from broker API
    min_distance = get_min_distance(symbol)
    if min_distance is None:
        logging.error(f"❌ Failed to get minimum TP/SL distance for {symbol}. Skipping trade.")
        return

    # Calculate TP & SL with min distance check
    tp = round(price * (1.005 if action == "BUY" else 0.995), 2)
    sl = round(price * (0.995 if action == "BUY" else 1.005), 2)

    # Ensure TP & SL meet minimum distance
    if abs(tp - price) < min_distance:
        tp = round(price + (min_distance if action == "BUY" else -min_distance), 2)

    if abs(sl - price) < min_distance:
        sl = round(price - (min_distance if action == "BUY" else -min_distance), 2)

    # Updated payload structure for Capital.com API
    payload = {
        "epic": symbol,
        "direction": action,
        "size": lot_size,
        "stopLevel": sl,
        "profitLevel": tp,  # 🔥 Add TP here
        "guaranteedStop": False,
        "trailingStop": False,
        "forceOpen": True  # This ensures a new position is created
    }

    logging.info(f"🚀 Sending trade request: {json.dumps(payload)}")

    url = f"{CAPITAL_API_URL}/positions"
    headers = {
        "X-CAP-API-KEY": CAPITAL_API_KEY,
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
            verify_tp(deal_id, tp)
        else:
            error_data = "Unknown error"
            try:
                error_data = response.json()
            except:
                error_data = response.text
                
            logging.error(f"❌ Trade Execution Failed for {symbol}: {error_data}")
    except Exception as e:
        logging.error(f"❌ Trade execution exception: {str(e)}", exc_info=True)

def update_tp(deal_id, new_tp):
    """Updates the Take Profit level for an open position"""
    cst, x_security = authenticate()
    if not cst or not x_security:
        return

    url = f"{CAPITAL_API_URL}/positions/{deal_id}"
    headers = {
        "X-CAP-API-KEY": CAPITAL_API_KEY,
        "CST": cst,
        "X-SECURITY-TOKEN": x_security,
        "Content-Type": "application/json"
    }
    
    payload = {
        "profitLevel": new_tp,  # New TP price
        "profitAmount": None,  # Optional, auto-calculated if None
    }

    try:
        session = create_session()
        response = session.put(url, headers=headers, json=payload)

        if response.status_code == 200:
            logging.info(f"✅ Take Profit updated for {deal_id}: {new_tp}")
        else:
            error_data = "Unknown error"
            try:
                error_data = response.json()
            except:
                error_data = response.text
                
            logging.error(f"❌ Failed to update Take Profit: {error_data}")
    except Exception as e:
        logging.error(f"❌ Update TP exception: {str(e)}", exc_info=True)

# Update take profit for an existing position
def update_take_profit(symbol, new_tp, cst, x_security):
    """Update the take profit level for an existing position"""
    # First get all positions to find the one we want to update
    url = f"{CAPITAL_API_URL}/positions"
    headers = {
        "X-CAP-API-KEY": CAPITAL_API_KEY,
        "CST": cst,
        "X-SECURITY-TOKEN": x_security,
        "Content-Type": "application/json"
    }
    
    try:
        session = create_session()
        response = session.get(url, headers=headers)
        
        if response.status_code == 200:
            positions = response.json().get("positions", [])
            
            # Find the position for this symbol
            for position in positions:
                if position.get("epic") == symbol:
                    position_id = position.get("dealId")
                    
                    # Update the take profit
                    update_url = f"{CAPITAL_API_URL}/positions/{position_id}"
                    update_payload = {"limitLevel": new_tp}
                    
                    update_response = session.put(update_url, headers=headers, json=update_payload)
                    
                    if update_response.status_code == 200:
                        logging.info(f"✅ Updated TP for {symbol} to {new_tp}")
                    else:
                        error_data = "Unknown error"
                        try:
                            error_data = update_response.json()
                        except:
                            error_data = update_response.text
                            
                        logging.error(f"❌ Failed to update TP: {error_data}")
                    
                    break
            else:
                logging.warning(f"⚠️ No open position found for {symbol}")
        else:
            error_data = "Unknown error"
            try:
                error_data = response.json()
            except:
                error_data = response.text
                
            logging.error(f"❌ Failed to fetch positions: {error_data}")
    except Exception as e:
        logging.error(f"❌ Update TP exception: {str(e)}", exc_info=True)

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
        "X-CAP-API-KEY": CAPITAL_API_KEY,
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
        "X-CAP-API-KEY": CAPITAL_API_KEY,
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
        "X-CAP-API-KEY": CAPITAL_API_KEY,
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
        symbol = data.get("symbol")
        action = data.get("action")
        
        if not symbol or not action:
            return jsonify({"status": "error", "message": "Missing required fields"}), 400
            
        try:
            price = float(data.get("price", 0))
        except (ValueError, TypeError):
            return jsonify({"status": "error", "message": "Invalid price value"}), 400
            
        logging.info(f"🌐 Webhook received: {json.dumps(data)}")
        
        # Execute trade in a separate thread to avoid blocking the webhook response
        threading.Thread(target=trade_action, args=(symbol, action, price, "SCALP")).start()
        
        return jsonify({
            "status": "success", 
            "message": f"✅ Trade request received: {action} {symbol} at {price}"
        }), 200
    except Exception as e:
        logging.error(f"❌ Webhook error: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"Internal server error: {str(e)}"}), 500

# Authenticate with Capital.com API with rate limiting and caching
def authenticate():
    cache_key = "auth_tokens"
    
    # Check if we have valid cached tokens
    if cache_key in api_cache and time.time() < api_cache[cache_key]["expiry"]:
        return api_cache[cache_key]["cst"], api_cache[cache_key]["x_security"]
    
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
            
            return cst, x_security
        else:
            error_data = "Unknown error"
            try:
                error_data = response.json()
            except:
                error_data = response.text
                
            logging.error(f"❌ Authentication Failed: {error_data}")
            
            # If rate limited, wait longer before next attempt
            if response.status_code == 429:
                logging.warning("⚠️ Rate limited. Waiting before next authentication attempt.")
                time.sleep(5)
                
            return None, None
    except Exception as e:
        logging.error(f"❌ Authentication Exception: {str(e)}", exc_info=True)
        return None, None

# Fetch Market Data with caching
def get_market_data(symbol):
    cache_key = f"market_data_{symbol}"
    
    # Check if we have valid cached data
    if cache_key in api_cache and time.time() < api_cache[cache_key]["expiry"]:
        return api_cache[cache_key]["data"]
    
    cst, x_security = authenticate()
    if not cst or not x_security:
        return None

    url = f"{CAPITAL_API_URL}/prices/{symbol}?resolution=MINUTE_5&max=100"
    headers = {"X-CAP-API-KEY": CAPITAL_API_KEY, "CST": cst, "X-SECURITY-TOKEN": x_security, "Content-Type": "application/json"}
    
    try:
        session = create_session()
        api_logger.debug(f"Market data request for {symbol}")
        response = session.get(url, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            
            # Cache the data
            api_cache[cache_key] = {
                "data": data,
                "expiry": time.time() + API_CACHE_TTL
            }
            
            return data
        else:
            error_data = "Unknown error"
            try:
                error_data = response.json()
            except:
                error_data = response.text
                
            logging.error(f"❌ Failed to fetch market data for {symbol}: {error_data}")
            return None
    except Exception as e:
        logging.error(f"❌ Market data exception for {symbol}: {str(e)}", exc_info=True)
        return None

# Analyze Market Trends with improved error handling
def analyze_market(symbol):
    data = get_market_data(symbol)
    if not data:
        logging.warning(f"⚠️ No market data available for {symbol}")
        return "HOLD", None, None
        
    if "prices" not in data or not data["prices"]:
        logging.warning(f"⚠️ Empty price data for {symbol}")
        return "HOLD", None, None

    try:
        df = pd.DataFrame(data["prices"])  
        
        # Validate required columns exist
        required_columns = ["highPrice", "lowPrice", "closePrice"]
        for col in required_columns:
            if col not in df.columns:
                logging.error(f"❌ Missing column {col} in market data for {symbol}")
                return "HOLD", None, None
        
        # Extract price data safely
        df["high"] = df["highPrice"].apply(lambda x: x.get("bid", 0) if isinstance(x, dict) else 0)
        df["low"] = df["lowPrice"].apply(lambda x: x.get("bid", 0) if isinstance(x, dict) else 0)
        df["close"] = df["closePrice"].apply(lambda x: x.get("bid", 0) if isinstance(x, dict) else 0)
        
        # Check for valid data
        if df["high"].max() <= 0 or df["low"].min() <= 0 or df["close"].max() <= 0:
            logging.error(f"❌ Invalid price values for {symbol}")
            return "HOLD", None, None
            
        df.dropna(inplace=True)
        
        if len(df) < 14:  # Need at least 14 periods for ATR
            logging.warning(f"⚠️ Insufficient data points for {symbol} ATR calculation")
            return "HOLD", None, None
            
        df["ATR"] = talib.ATR(df["high"], df["low"], df["close"], timeperiod=14)
        
        latest_price = df["close"].iloc[-1]
        atr_value = df["ATR"].iloc[-1]
        
        logging.info(f"📊 {symbol} ATR: {atr_value}, Latest Price: {latest_price}")
        
        # Simple trend determination
        price_mean = df["close"].mean()
        trend = "BUY" if latest_price > price_mean else "SELL"
        
        return trend, latest_price, "SCALP"
        
    except Exception as e:
        logging.error(f"❌ Analysis error for {symbol}: {str(e)}", exc_info=True)
        return "HOLD", None, None

# Get minimum distance with caching
def get_min_distance(symbol):
    """Fetches the minimum TP/SL distance from the broker for a given symbol"""
    cache_key = f"min_distance_{symbol}"
    
    # Check if we have valid cached data
    if cache_key in api_cache and time.time() < api_cache[cache_key]["expiry"]:
        return api_cache[cache_key]["distance"]
    
    cst, x_security = authenticate()
    if not cst or not x_security:
        return None

    url = f"{CAPITAL_API_URL}/markets/{symbol}"
    headers = {
        "X-CAP-API-KEY": CAPITAL_API_KEY,
        "CST": cst,
        "X-SECURITY-TOKEN": x_security,
        "Content-Type": "application/json"
    }

    try:
        session = create_session()
        api_logger.debug(f"Min distance request for {symbol}")
        response = session.get(url, headers=headers)
        
        if response.status_code == 200:
            market_data = response.json()
            min_distance = float(market_data.get("minNormalStopOrLimitDistance", market_data.get("minStopDistance", 1)))
            
            # Cache the distance
            api_cache[cache_key] = {
                "distance": min_distance,
                "expiry": time.time() + 3600  # Cache for 1 hour
            }
            
            return min_distance
        else:
            error_data = "Unknown error"
            try:
                error_data = response.json()
            except:
                error_data = response.text
                
            logging.error(f"❌ Failed to fetch min distance for {symbol}: {error_data}")
            return None
    except Exception as e:
        logging.error(f"❌ Min distance exception for {symbol}: {str(e)}", exc_info=True)
        return None

def get_position_details(deal_id, cst, x_security):
    """Get full details of an open position including TP/SL levels"""
    # First get all positions to find the one with matching dealId
    url = f"{CAPITAL_API_URL}/positions"
    headers = {
        "X-CAP-API-KEY": CAPITAL_API_KEY,
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

# Monitor & Adjust TP/SL
def monitor_trades():
    while True:
        try:
            cst, x_security = authenticate()
            if not cst or not x_security:
                time.sleep(TRADE_INTERVAL)
                continue

            url = f"{CAPITAL_API_URL}/positions"
            headers = {
                "X-CAP-API-KEY": CAPITAL_API_KEY, 
                "CST": cst, 
                "X-SECURITY-TOKEN": x_security, 
                "Content-Type": "application/json"
            }
            
            session = create_session()
            response = session.get(url, headers=headers)

            if response.status_code == 200:
                positions_data = response.json()
                
                if "positions" in positions_data:
                    for trade in positions_data["positions"]:
                        try:
                            symbol = trade["epic"]
                            entry_price = float(trade["level"])
                            current_tp = float(trade.get("limitLevel", 0))
                            
                            # Calculate new TP based on direction
                            direction = trade.get("direction")
                            if direction == "BUY":
                                new_tp = round(entry_price * (1 + TP_MOVE_PERCENT), 2)
                                if new_tp > current_tp:
                                    logging.info(f"🔄 Updating TP for {symbol}: {new_tp}")
                                    trade_action(symbol, "UPDATE_TP", new_tp, "")
                            elif direction == "SELL":
                                new_tp = round(entry_price * (1 - TP_MOVE_PERCENT), 2)
                                if new_tp < current_tp:
                                    logging.info(f"🔄 Updating TP for {symbol}: {new_tp}")
                                    trade_action(symbol, "UPDATE_TP", new_tp, "")
                        except Exception as e:
                            logging.error(f"❌ Error processing position {trade.get('dealId')}: {str(e)}")
                else:
                    logging.info("No open positions found")
            else:
                error_data = "Unknown error"
                try:
                    error_data = response.json()
                except:
                    error_data = response.text
                    
                logging.error(f"❌ Failed to fetch positions: {error_data}")
                
        except Exception as e:
            logging.error(f"❌ Monitor trades exception: {str(e)}", exc_info=True)
            
        time.sleep(TRADE_INTERVAL)

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
                    trade_action(symbol, trend, latest_price, mode)
                time.sleep(1)  # Small delay between symbols to avoid rate limiting
        except Exception as e:
            logging.error(f"❌ Main loop exception: {str(e)}", exc_info=True)
            
        time.sleep(TRADE_INTERVAL)

# Start Flask Webhook & Trading Bot
if __name__ == "__main__":
    try:
        logging.info("🚀 Starting Capital.com Trading Bot")
        webhook_thread = threading.Thread(target=app.run, kwargs={"host": "0.0.0.0", "port": 5000, "threaded": True})
        webhook_thread.daemon = True
        webhook_thread.start()
        logging.info("✅ Webhook server started on port 5000")
        main()
    except Exception as e:
        logging.critical(f"❌ Critical error: {str(e)}", exc_info=True)

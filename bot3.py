import os
import time
import threading
import logging
import pandas as pd
import json
import numpy as np
from datetime import datetime
from .technical_indicators import calculate_atr
from .api_client import CapitalComClient
from .credentials import CredentialsManager
from .strategies import TrendFollowingStrategy

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("trading_bot.log"),
        logging.StreamHandler()
    ]
)

# Trading Settings
TRADE_INTERVAL = 300  # 5 minutes
# Capital.com uses specific symbol format
SYMBOLS = [
    "CRYPTO:BTC/USD", "CRYPTO:ETH/USD", "CRYPTO:XRP/USD", 
    "CRYPTO:LTC/USD", "CRYPTO:ADA/USD", "CRYPTO:SOL/USD",
    "CRYPTO:DOGE/USD", "CRYPTO:DOT/USD", "CRYPTO:MATIC/USD",
    "CRYPTO:BNB/USD"
]

class TradingBot:
    def __init__(self):
        try:
            # Initialize credentials and API client
            logging.info("Initializing TradingBot...")
            self.creds = CredentialsManager()
            credentials = self.creds.get_credentials()
            
            logging.info("Setting up API client...")
            logging.info(f"Using credentials - Identifier: {credentials['IDENTIFIER']}")
            
            self.api_client = CapitalComClient(
                None,  # API key not used in new auth flow
                credentials['API_SECRET'],
                credentials['IDENTIFIER']
            )
            
            # Initialize strategy
            logging.info("Initializing trading strategy...")
            self.strategy = TrendFollowingStrategy()
            
            # Initialize price history
            self.price_history = {symbol: [] for symbol in SYMBOLS}
            self.account_balance = self._get_account_balance()
            logging.info(f"Initial account balance: {self.account_balance}")
            
            # Initialize trade state
            self.last_trade_time = {}
            self.active_positions = {}
            
        except Exception as e:
            logging.error(f"Error initializing TradingBot: {str(e)}")
            raise
            
    def _get_account_balance(self):
        """Get account balance from API"""
        try:
            # For testing, using a fixed balance
            # In production, this would fetch from the API
            return 10000.0
        except Exception as e:
            logging.error(f"Error getting account balance: {str(e)}")
            return 0.0
            
    def execute_trade(self, symbol, signal):
        """Execute trade based on strategy signal"""
        try:
            if not signal:
                return
                
            # Check if we've traded this symbol recently
            current_time = time.time()
            if symbol in self.last_trade_time:
                time_since_last_trade = current_time - self.last_trade_time[symbol]
                if time_since_last_trade < TRADE_INTERVAL:
                    logging.info(f"Skipping trade for {symbol}, too soon since last trade")
                    return
                    
            logging.info(f"Executing trade: {symbol} - {signal['action']}")
            logging.info(f"Trade details: {json.dumps(signal)}")
            
            # Place order
            if signal['action'] == 'BUY':
                result = self.api_client.place_market_order(
                    symbol, 
                    'BUY', 
                    signal['quantity']
                )
            else:  # SELL
                result = self.api_client.place_market_order(
                    symbol, 
                    'SELL', 
                    signal['quantity']
                )
                
            if result:
                logging.info(f"Trade executed successfully: {result}")
                self.strategy.update_position(symbol, signal['action'], signal['quantity'])
                self.last_trade_time[symbol] = current_time
                
                # Update active positions
                if signal['action'] == 'BUY':
                    self.active_positions[symbol] = {
                        'direction': 'BUY',
                        'quantity': signal['quantity'],
                        'entry_price': signal['price']
                    }
                else:
                    if symbol in self.active_positions:
                        del self.active_positions[symbol]
                
                # Log trade details
                trade_details = {
                    "symbol": symbol,
                    "action": signal['action'],
                    "quantity": signal['quantity'],
                    "price": signal['price'],
                    "reason": signal['reason'],
                    "timestamp": datetime.now().isoformat()
                }
                with open("trades.log", "a") as f:
                    f.write(json.dumps(trade_details) + "\n")
            else:
                logging.error("Trade execution failed")
                
        except Exception as e:
            logging.error(f"Error executing trade: {str(e)}")
            
    def update_price_history(self, symbol, price):
        """Update price history for symbol"""
        if price is not None:  # Only update if we got a valid price
            self.price_history[symbol].append(price)
            # Keep last 100 prices
            if len(self.price_history[symbol]) > 100:
                self.price_history[symbol] = self.price_history[symbol][-100:]
            
    def monitor_trades(self):
        """Monitor markets and execute trades"""
        logging.info("Starting trade monitoring...")
        
        while True:
            try:
                for symbol in SYMBOLS:
                    logging.info(f"Fetching price for {symbol}...")
                    # Get current price from API
                    current_price = self.api_client.get_market_price(symbol)
                    
                    if current_price:
                        logging.info(f"Got price for {symbol}: ${current_price:.2f}")
                        # Update price history
                        self.update_price_history(symbol, current_price)
                        
                        # Get trading signal
                        if len(self.price_history[symbol]) >= 20:  # Need minimum history
                            signal = self.strategy.get_signal(
                                symbol,
                                current_price,
                                self.price_history[symbol],
                                self.account_balance
                            )
                            
                            if signal:
                                signal['price'] = current_price
                                self.execute_trade(symbol, signal)
                    else:
                        logging.warning(f"Failed to get price for {symbol}")
                
                logging.info("Sleeping for trade interval...")
                time.sleep(TRADE_INTERVAL)
                
            except Exception as e:
                logging.error(f"Monitor error: {str(e)}")
                time.sleep(60)  # Wait a minute before retrying

if __name__ == "__main__":
    try:
        # Initialize and start the trading bot
        bot = TradingBot()
        
        # Start monitoring in a separate thread
        monitor_thread = threading.Thread(target=bot.monitor_trades, daemon=True)
        monitor_thread.start()
        
        logging.info("Trading bot started. Press Ctrl+C to exit.")
        while True:
            time.sleep(1)
            
    except Exception as e:
        logging.error(f"Bot initialization error: {str(e)}")
    except KeyboardInterrupt:
        logging.info("Shutting down...")

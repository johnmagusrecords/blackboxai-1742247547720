import os
import json
import logging
from flask import Flask, jsonify
from dotenv import load_dotenv
from bot1 import authenticate, get_market_data, analyze_market, trade_action, get_position_details
from strategies import TrendFollowingStrategy

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Initialize strategy
strategy = TrendFollowingStrategy()

@app.route('/api/dashboard/positions', methods=['GET'])
def get_positions():
    """Get all open positions with their details"""
    try:
        cst, x_security = authenticate()
        if not cst or not x_security:
            return jsonify({"error": "Authentication failed"}), 401

        url = f"{os.getenv('CAPITAL_API_URL')}/positions"
        headers = {
            "X-CAP-API-KEY": os.getenv("CAPITAL_API_KEY"),
            "CST": cst,
            "X-SECURITY-TOKEN": x_security,
            "Content-Type": "application/json"
        }
        
        positions = []
        for position in positions_data.get("positions", []):
            symbol = position.get("epic")
            direction = position.get("direction")
            entry_price = float(position.get("level", 0))
            current_price = float(position.get("marketPrice", 0))
            profit_loss = float(position.get("profit", 0))
            
            # Get market data for signal analysis
            market_data = get_market_data(symbol)
            _, _, mode = analyze_market(symbol)
            
            positions.append({
                "symbol": symbol,
                "direction": direction,
                "entry_price": entry_price,
                "current_price": current_price,
                "profit_loss": profit_loss,
                "trading_mode": mode,
                "take_profit": position.get("limitLevel"),
                "stop_loss": position.get("stopLevel")
            })
            
        return jsonify({"positions": positions})
    except Exception as e:
        logging.error(f"Error fetching positions: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/dashboard/signals', methods=['GET'])
def get_signals():
    """Get current trading signals for all symbols"""
    try:
        signals = []
        for symbol in ["BTCUSD", "ETHUSD", "XRPUSD", "LTCUSD", "ADAUSD"]:
            market_data = get_market_data(symbol)
            if market_data:
                trend, price, mode = analyze_market(symbol)
                signal = strategy.get_signal(symbol, price, market_data, 10000)  # Example account balance
                
                if signal:
                    signals.append({
                        "symbol": symbol,
                        "action": signal["action"],
                        "price": price,
                        "reason": signal["reason"],
                        "mode": mode
                    })
                    
        return jsonify({"signals": signals})
    except Exception as e:
        logging.error(f"Error getting signals: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/dashboard/market_news', methods=['GET'])
def get_market_news():
    """Get relevant market news for traded assets"""
    try:
        # This would be replaced with actual news API integration
        news = [
            {
                "title": "Bitcoin Breaks Above $45,000",
                "content": "Bitcoin surges past $45,000 as institutional adoption grows",
                "sentiment": "positive",
                "symbol": "BTCUSD",
                "timestamp": "2024-03-17T10:30:00Z"
            }
        ]
        return jsonify({"news": news})
    except Exception as e:
        logging.error(f"Error fetching news: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(port=5001)

import json
import logging
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS

# Serve static files
@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

@app.route('/api/dashboard/positions', methods=['GET'])
def get_positions():
    """Get all open positions with their details"""
    try:
        # Mock data for testing
        positions = [
            {
                "symbol": "BTCUSD",
                "direction": "BUY",
                "entry_price": 45000.00,
                "current_price": 45500.00,
                "profit_loss": 500.00,
                "trading_mode": "SCALP",
                "take_profit": 46000.00,
                "stop_loss": 44000.00
            },
            {
                "symbol": "ETHUSD",
                "direction": "SELL",
                "entry_price": 3200.00,
                "current_price": 3150.00,
                "profit_loss": 50.00,
                "trading_mode": "SWING",
                "take_profit": 3100.00,
                "stop_loss": 3300.00
            }
        ]
            
        return jsonify({"positions": positions})
    except Exception as e:
        logging.error(f"Error fetching positions: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/dashboard/signals', methods=['GET'])
def get_signals():
    """Get current trading signals for all symbols"""
    try:
        # Mock signals for testing
        signals = [
            {
                "symbol": "BTCUSD",
                "action": "BUY",
                "price": 45000.00,
                "reason": "RSI oversold + SMA crossover",
                "mode": "SCALP"
            },
            {
                "symbol": "ETHUSD",
                "action": "SELL",
                "price": 3200.00,
                "reason": "RSI overbought + resistance level",
                "mode": "SWING"
            }
        ]
                    
        return jsonify({"signals": signals})
    except Exception as e:
        logging.error(f"Error getting signals: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/dashboard/market_news', methods=['GET'])
def get_market_news():
    """Get relevant market news for traded assets"""
    try:
        # Mock news data for testing
        news = [
            {
                "title": "Bitcoin Breaks Above $45,000",
                "content": "Bitcoin surges past $45,000 as institutional adoption grows. Major financial institutions announce new crypto investment products.",
                "sentiment": "positive",
                "symbol": "BTCUSD",
                "timestamp": "2024-03-17T10:30:00Z"
            },
            {
                "title": "Ethereum Network Upgrade Announced",
                "content": "Ethereum developers confirm date for next major network upgrade, promising improved scalability and lower gas fees.",
                "sentiment": "positive",
                "symbol": "ETHUSD",
                "timestamp": "2024-03-17T09:15:00Z"
            },
            {
                "title": "Market Volatility Warning",
                "content": "Analysts warn of potential market volatility ahead of key economic data releases this week.",
                "sentiment": "negative",
                "symbol": "GENERAL",
                "timestamp": "2024-03-17T08:45:00Z"
            }
        ]
        return jsonify({"news": news})
    except Exception as e:
        logging.error(f"Error fetching news: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(port=5001)

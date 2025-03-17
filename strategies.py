import numpy as np
from .technical_indicators import calculate_atr, calculate_moving_averages, calculate_rsi
import logging

class TrendFollowingStrategy:
    def __init__(self):
        self.positions = {}  # Track open positions
        self.atr_period = 14
        self.rsi_period = 14
        self.sma_short = 10
        self.sma_long = 20
        self.rsi_oversold = 30
        self.rsi_overbought = 70

    def update_position(self, symbol, action, quantity):
        """Update position tracking"""
        if action == 'BUY':
            self.positions[symbol] = quantity
        elif action == 'SELL':
            if symbol in self.positions:
                del self.positions[symbol]

    def get_signal(self, symbol, current_price, price_history, account_balance):
        """Generate trading signal based on strategy rules"""
        try:
            # Convert price history to numpy arrays
            prices = np.array(price_history)
            highs = prices * 1.001  # Simulate high prices
            lows = prices * 0.999   # Simulate low prices
            
            # Calculate indicators
            atr = calculate_atr(highs, lows, prices)
            sma_short, sma_long = calculate_moving_averages(prices)
            rsi = calculate_rsi(prices)
            
            # Skip if not enough data
            if len(atr) < 2 or len(sma_short) < 2 or len(sma_long) < 2 or len(rsi) < 2:
                return None
                
            # Get latest values
            current_atr = atr[-1]
            current_rsi = rsi[-1]
            
            # Check if we already have a position
            has_position = symbol in self.positions
            
            # Trading logic
            if not has_position:  # Look for buy signals
                if (sma_short[-1] > sma_long[-1] and  # Uptrend
                    sma_short[-2] <= sma_long[-2] and  # Crossover just occurred
                    current_rsi < self.rsi_overbought):  # Not overbought
                    
                    # Calculate position size based on ATR
                    risk_amount = account_balance * 0.02  # Risk 2% per trade
                    stop_loss = current_price - (current_atr * 2)  # 2 ATR stop loss
                    position_size = risk_amount / (current_price - stop_loss)
                    
                    return {
                        'action': 'BUY',
                        'quantity': position_size,
                        'reason': 'SMA crossover with RSI confirmation'
                    }
                    
            else:  # Look for sell signals
                if (sma_short[-1] < sma_long[-1] and  # Downtrend
                    sma_short[-2] >= sma_long[-2] or  # Crossover just occurred
                    current_rsi > self.rsi_overbought):  # Overbought
                    
                    return {
                        'action': 'SELL',
                        'quantity': self.positions[symbol],
                        'reason': 'Exit signal: trend reversal or overbought'
                    }
                    
            return None
            
        except Exception as e:
            logging.error(f"Error generating signal: {str(e)}")
            return None

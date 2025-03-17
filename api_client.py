import os
import requests
import logging
import json
import time
import hmac
import hashlib
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

class CapitalComClient:
    def __init__(self, api_key, api_secret, identifier):
        self.identifier = identifier
        self.password = api_secret
        self.base_url = "https://api-capital.backend-capital.com/api/v1"
        self.session = requests.Session()
        
        # Set up logging
        logging.info("Initializing Capital.com API client...")
        
        # Set up session headers
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'X-CAP-API-KEY': identifier
        })
        
        # Perform initial authentication
        self._authenticate()
        
    def _generate_signature(self, timestamp, method, endpoint, body=None):
        """Generate HMAC signature for API request"""
        try:
            # Create signature base string
            signature_base = f"{timestamp}{method.upper()}{endpoint}"
            if body:
                signature_base += json.dumps(body, separators=(',', ':'))
                
            # Create signature using HMAC-SHA256
            signature = hmac.new(
                self.password.encode(),
                signature_base.encode(),
                hashlib.sha256
            ).hexdigest()
            
            return signature
            
        except Exception as e:
            logging.error(f"Error generating signature: {str(e)}")
            return None

    def _authenticate(self):
        """Authenticate with the Capital.com API"""
        try:
            # Generate timestamp
            timestamp = str(int(time.time() * 1000))
            
            # Prepare authentication data
            auth_data = {
                "identifier": self.identifier,
                "password": self.password,
                "encryptedPassword": False
            }
            
            # Generate signature
            signature = self._generate_signature(timestamp, 'POST', '/session', auth_data)
            
            if not signature:
                logging.error("Failed to generate signature")
                return
                
            # Update headers for authentication
            self.session.headers.update({
                'X-TIMESTAMP': timestamp,
                'X-SIGNATURE': signature
            })
            
            # Make authentication request
            auth_endpoint = f"{self.base_url}/session"
            logging.info(f"Attempting authentication to {auth_endpoint}")
            logging.info(f"Auth headers: {json.dumps(dict(self.session.headers))}")
            logging.info(f"Auth data: {json.dumps(auth_data)}")
            
            response = self.session.post(auth_endpoint, json=auth_data)
            
            logging.info(f"Auth response status: {response.status_code}")
            logging.info(f"Auth response headers: {dict(response.headers)}")
            logging.info(f"Auth response body: {response.text}")
            
            if response.status_code == 200:
                # Get security tokens
                cst = response.headers.get('CST')
                security_token = response.headers.get('X-SECURITY-TOKEN')
                
                if not cst or not security_token:
                    logging.error("Security tokens not found in response")
                    return
                    
                # Update session headers
                self.session.headers.update({
                    'CST': cst,
                    'X-SECURITY-TOKEN': security_token
                })
                
                # Get account details
                accounts_response = self.session.get(f"{self.base_url}/accounts")
                
                if accounts_response.status_code == 200:
                    accounts_data = accounts_response.json()
                    logging.info(f"Accounts data: {accounts_data}")
                    
                    if 'accounts' in accounts_data and accounts_data['accounts']:
                        demo_account = next(
                            (acc for acc in accounts_data['accounts'] if acc.get('accountType') == 'DEMO'),
                            accounts_data['accounts'][0]
                        )
                        
                        self.account_id = demo_account['accountId']
                        logging.info(f"Using account ID: {self.account_id}")
                        
                        # Switch to demo account
                        switch_response = self.session.put(
                            f"{self.base_url}/session",
                            json={'accountId': self.account_id}
                        )
                        
                        if switch_response.status_code == 200:
                            logging.info("Successfully switched to demo account")
                        else:
                            logging.error(f"Failed to switch account: {switch_response.text}")
                    else:
                        logging.error("No accounts found")
                else:
                    logging.error(f"Failed to get accounts: {accounts_response.text}")
                    
                logging.info("Authentication completed")
                logging.info(f"Final headers: {dict(self.session.headers)}")
            else:
                logging.error(f"Authentication failed: {response.text}")
                
        except Exception as e:
            logging.error(f"Authentication error: {str(e)}")

    def _make_request(self, method, endpoint, data=None):
        """Make an authenticated request to the API"""
        try:
            # Generate new timestamp and signature
            timestamp = str(int(time.time() * 1000))
            signature = self._generate_signature(timestamp, method, endpoint, data)
            
            # Update headers
            self.session.headers.update({
                'X-TIMESTAMP': timestamp,
                'X-SIGNATURE': signature
            })
            
            # Make request
            url = f"{self.base_url}{endpoint}"
            if method == 'GET':
                response = self.session.get(url)
            elif method == 'POST':
                response = self.session.post(url, json=data)
            elif method == 'PUT':
                response = self.session.put(url, json=data)
            elif method == 'DELETE':
                response = self.session.delete(url)
                
            # Check if we need to refresh authentication
            if response.status_code == 401:
                logging.info("Token expired, refreshing authentication...")
                self._authenticate()
                return self._make_request(method, endpoint, data)
                
            return response
            
        except Exception as e:
            logging.error(f"Request error: {str(e)}")
            return None

    def get_market_price(self, symbol):
        """Get current market price for a symbol"""
        try:
            response = self._make_request('GET', f"/prices/{symbol}")
            
            if response and response.status_code == 200:
                price_data = response.json()
                if 'prices' in price_data and price_data['prices']:
                    latest_price = price_data['prices'][0]
                    bid = float(latest_price['bid'])
                    ask = float(latest_price['ask'])
                    return (bid + ask) / 2
                    
                logging.error(f"No price data found for {symbol}")
                return None
            else:
                logging.error(f"Failed to get price: {response.text if response else 'No response'}")
                return None
                
        except Exception as e:
            logging.error(f"Error getting market price for {symbol}: {str(e)}")
            return None

    def place_market_order(self, symbol, direction, quantity):
        """Place a market order"""
        try:
            payload = {
                'epic': symbol,
                'direction': direction,
                'size': str(quantity),
                'orderType': 'MARKET',
                'guaranteedStop': False,
                'forceOpen': True
            }
            
            response = self._make_request('POST', '/positions', payload)
            
            if response and response.status_code == 200:
                data = response.json()
                logging.info(f"Order placed successfully: {data}")
                return data
            else:
                logging.error(f"Failed to place order: {response.text if response else 'No response'}")
                return None
                
        except Exception as e:
            logging.error(f"Error placing market order: {str(e)}")
            return None

    def get_positions(self):
        """Get current open positions"""
        try:
            response = self._make_request('GET', '/positions')
            
            if response and response.status_code == 200:
                return response.json()
            else:
                logging.error(f"Failed to get positions: {response.text if response else 'No response'}")
                return []
                
        except Exception as e:
            logging.error(f"Error getting positions: {str(e)}")
            return []

    def close_position(self, position_id):
        """Close a specific position"""
        try:
            response = self._make_request('DELETE', f'/positions/{position_id}')
            
            if response and response.status_code == 200:
                logging.info(f"Position {position_id} closed successfully")
                return True
            else:
                logging.error(f"Failed to close position: {response.text if response else 'No response'}")
                return False
                
        except Exception as e:
            logging.error(f"Error closing position: {str(e)}")
            return False

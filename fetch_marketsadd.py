"""Module for fetching market data using the Capital API."""

import os
import requests
import json
from dotenv import load_dotenv

# Load API Credentials from .env
load_dotenv()
CAPITAL_API_KEY = os.getenv("CAPITAL_API_KEY")
CAPITAL_API_URL = os.getenv("CAPITAL_API_URL")
CAPITAL_API_PASSWORD = os.getenv("CAPITAL_API_PASSWORD")
CAPITAL_API_IDENTIFIER = os.getenv("CAPITAL_IDENTIFIER")  # Updated to match .env file

# Check if any of the environment variables are missing
if not all([CAPITAL_API_KEY, CAPITAL_API_URL, CAPITAL_API_PASSWORD, CAPITAL_API_IDENTIFIER]):
    raise ValueError("One or more environment variables are missing. Please check your .env file.")

# Strip whitespace from environment variables
CAPITAL_API_KEY = CAPITAL_API_KEY.strip()
CAPITAL_API_URL = CAPITAL_API_URL.strip()
CAPITAL_API_PASSWORD = CAPITAL_API_PASSWORD.strip()
CAPITAL_API_IDENTIFIER = CAPITAL_API_IDENTIFIER.strip()

def create_session():
    """Create a session with the Capital API.

    Returns:
        dict: A dictionary containing session tokens and account ID.
              Returns None if the session creation fails.
    """
    url = f"{CAPITAL_API_URL}/session"
    payload = {
        "identifier": CAPITAL_API_IDENTIFIER,
        "password": CAPITAL_API_PASSWORD
    }
    
    headers = {
        "X-CAP-API-KEY": CAPITAL_API_KEY,
        "Content-Type": "application/json"
    }

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code == 200:
        session_data = response.json()
        print("Session created successfully.")
        
        # Get security tokens from headers, not from JSON body
        security_token = response.headers.get('X-SECURITY-TOKEN')
        cst_token = response.headers.get('CST')
        
        print(f"Security Token: {security_token}")
        print(f"CST Token: {cst_token}")
        
        return {
            'security_token': security_token,
            'cst_token': cst_token,
            'account_id': session_data.get('currentAccountId')
        }

    print(f"❌ Failed to create session. Response: {response.status_code}, {response.text}")
    return None

def refresh_session_tokens():
    """Refresh the session tokens by creating a new session."""
    session_tokens = create_session()
    if session_tokens:
        print("🔄 Session tokens refreshed.")
    else:
        print("❌ Failed to refresh session tokens.")
    return session_tokens

def fetch_all_markets(session_tokens):
    """Fetch all available markets using the provided session tokens.

    Args:
        session_tokens (dict): A dictionary containing session tokens.

    Returns:
        dict: A dictionary containing the fetched market data.
              Returns None if the request fails.
    """
    url = f"{CAPITAL_API_URL}/marketnavigation"
    
    # Use both security tokens in headers
    headers = {
        "X-SECURITY-TOKEN": session_tokens['security_token'],
        "CST": session_tokens['cst_token'],
        "Content-Type": "application/json"
    }

    print(f"Headers: {headers}")

    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        data = response.json()
        with open("all_markets.json", "w") as file:
            json.dump(data, file, indent=4)
        print(f"✅ Successfully fetched markets! Total items: {len(data.get('nodes', []))}")
        return data
    elif response.status_code == 401 and response.json().get('errorCode') == 'error.invalid.session.token':
        print("⚠️ Invalid session token. Refreshing tokens.")
        session_tokens = refresh_session_tokens()
        return fetch_all_markets(session_tokens)  # Retry with new tokens
    else:
        print(f"❌ Failed to fetch markets. Response: {response.status_code}, {response.text}")
        return None

if __name__ == "__main__":
    session_tokens = create_session()
    if session_tokens:
        fetch_all_markets(session_tokens)

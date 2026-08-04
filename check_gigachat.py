"""Script to check GigaChat API availability and send a test request.

Usage:
    uv run python check_gigachat.py
"""

import sys
import base64

from app.core.config import (
    GIGACHAT_CLIENT_ID,
    GIGACHAT_CLIENT_SECRET,
    GIGACHAT_CREDENTIALS,
    GIGACHAT_SCOPE,
    GIGACHAT_MODEL,
    GIGACHAT_AUTH_URL,
    GIGACHAT_API_URL,
)

# --- 1. Show config (without full secrets) ---
print("=" * 60)
print("GIGACHAT CONFIGURATION CHECK")
print("=" * 60)

client_id = GIGACHAT_CLIENT_ID
client_secret = GIGACHAT_CLIENT_SECRET
credentials = GIGACHAT_CREDENTIALS
scope = GIGACHAT_SCOPE
model = GIGACHAT_MODEL
auth_url = GIGACHAT_AUTH_URL
api_url = GIGACHAT_API_URL

print(f"  GIGACHAT_CLIENT_ID:     {'[SET]' if client_id else '[MISSING]'} ({client_id[:8] if client_id else ''}...)")
print(f"  GIGACHAT_CLIENT_SECRET: {'[SET]' if client_secret else '[MISSING]'}")
print(f"  GIGACHAT_CREDENTIALS:   {'[SET]' if credentials else '[MISSING]'}")
print(f"  GIGACHAT_SCOPE:         {scope}")
print(f"  GIGACHAT_MODEL:         {model}")
print(f"  GIGACHAT_AUTH_URL:      {auth_url}")
print(f"  GIGACHAT_API_URL:       {api_url}")

# --- 2. Check that we have some credentials ---
if not client_secret and not credentials:
    print("\n[ERROR] GIGACHAT_CLIENT_SECRET or GIGACHAT_CREDENTIALS not set in .env")
    print("   Add one of these to .env:")
    print('   GIGACHAT_CLIENT_SECRET=your-secret')
    print('   # or a ready Authorization Key:')
    print('   GIGACHAT_CREDENTIALS=your-base64-key')
    sys.exit(1)

# --- 3. Build credentials (same logic as config.py) ---
if credentials:
    final_credentials = credentials
    print("\n  Using GIGACHAT_CREDENTIALS directly")
else:
    try:
        base64.b64decode(client_secret, validate=True)
        final_credentials = client_secret
        print("\n  GIGACHAT_CLIENT_SECRET is a ready Authorization Key (Base64)")
    except Exception:
        raw = f"{client_id}|{client_secret}"
        final_credentials = base64.b64encode(raw.encode()).decode()
        print("\n  GIGACHAT_CLIENT_SECRET is raw secret, building Base64 from client_id|secret")

print(f"  Final credentials (first 20 chars): {final_credentials[:20]}...")

# --- 4. Try to create client and make a request ---
print("\n" + "=" * 60)
print("TEST REQUEST TO GigaChat API")
print("=" * 60)

try:
    from langchain_gigachat.chat_models import GigaChat

    print("\n  [..] Creating GigaChat client...")
    client = GigaChat(
        credentials=final_credentials,
        model=model,
        temperature=0.7,
        max_tokens=100,
        verify_ssl_certs=False,
        timeout=30,
    )
    print("  [OK] Client created successfully")

    print("\n  [..] Sending test request: 'Say only the word: OK'...")
    response = client.invoke([
        {"role": "system", "content": "You are a helpful assistant. Reply briefly."},
        {"role": "user", "content": "Say only the word: OK"}
    ])
    print("  [OK] Response received!")
    print(f"\n  Content: {response.content}")

    if hasattr(response, 'response_metadata'):
        print(f"\n  Metadata:")
        for k, v in response.response_metadata.items():
            print(f"     {k}: {v}")

    print("\n" + "=" * 60)
    print("GigaChat IS AVAILABLE AND WORKING")
    print("=" * 60)

except ImportError as e:
    print(f"\n[ERROR] Import failed: {e}")
    print("   Install: uv add langchain-gigachat")
    sys.exit(1)
except Exception as e:
    print(f"\n[ERROR] GigaChat request failed:")
    print(f"   {type(e).__name__}: {e}")

    error_str = str(e).lower()
    if "auth" in error_str or "unauthorized" in error_str or "401" in error_str:
        print("\n  Possible causes:")
        print("     - Invalid GIGACHAT_CLIENT_ID or GIGACHAT_CLIENT_SECRET")
        print("     - Credentials expired")
        print("     - Wrong scope (try GIGACHAT_API_PERS or GIGACHAT_API_CORP)")
    elif "connect" in error_str or "timeout" in error_str or "dns" in error_str:
        print("\n  Possible causes:")
        print("     - No internet access")
        print("     - Blocked by corporate proxy/firewall")
        print("     - Wrong GIGACHAT_AUTH_URL or GIGACHAT_API_URL")
    elif "model" in error_str or "not found" in error_str:
        print(f"\n  Possible causes:")
        print(f"     - Model '{model}' not available on this API gateway")
        print("     - Try: GigaChat, GigaChat-2, GigaChat-2-Max, GigaChat-2-Pro")
    else:
        print("\n  Check:")
        print("     - Credentials in .env are correct")
        print("     - API is accessible (not blocked by corporate network)")
        print("     - Rate limits not exceeded")

    sys.exit(1)
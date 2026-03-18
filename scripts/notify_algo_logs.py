#!/usr/bin/env python3
"""
notify_algo_logs.py - Send message to Algo Logs topic via OpenClaw gateway REST API
Target: chat_id=-1003676205983, thread_id=4
Method: POST to Mac OpenClaw gateway via Tailscale (port 18789)
"""
import sys, json
import urllib.request
import urllib.error

GATEWAY_URL = 'http://pearl-macbook.tailf340bb.ts.net:18789'
AUTH_TOKEN = 'b258f99a8f1eeb1a34d1bb098563111c22be97eca5060d523792e5be60144754'
TARGET = '-1003676205983'
THREAD_ID = '4'
ACCOUNT = 'pearlalgo'

def send_algo_log(message: str) -> bool:
    # Try different route patterns
    routes = [
        '/api/channels/telegram/send',
        '/api/message/send', 
        '/send',
    ]
    payload = json.dumps({
        'account': ACCOUNT,
        'target': TARGET,
        'threadId': THREAD_ID,
        'message': message,
        'channel': 'telegram'
    }).encode()
    
    for route in routes:
        try:
            req = urllib.request.Request(
                GATEWAY_URL + route,
                data=payload,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {AUTH_TOKEN}'
                },
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode()
                print(f'[notify_algo_logs] OK via {route}: {body[:80]}', file=sys.stderr)
                return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            print(f'[notify_algo_logs] HTTP {e.code} on {route}: {e.read().decode()[:100]}', file=sys.stderr)
        except Exception as ex:
            print(f'[notify_algo_logs] Error on {route}: {ex}', file=sys.stderr)
    return False

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: notify_algo_logs.py <message>', file=sys.stderr)
        sys.exit(1)
    ok = send_algo_log(sys.argv[1])
    sys.exit(0 if ok else 1)

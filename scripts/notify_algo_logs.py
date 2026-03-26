#!/usr/bin/env python3
"""
notify_algo_logs.py - Send message to Algo Logs topic via Telegram Bot API
Target: chat_id=-1003676205983, thread_id=4 (Algo Logs)
"""
import sys, json, os
import urllib.request, urllib.error

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
CHAT_ID = '-1003676205983'
THREAD_ID = 4

def send_algo_log(message: str) -> bool:
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    payload = json.dumps({
        'chat_id': CHAT_ID,
        'message_thread_id': THREAD_ID,
        'text': message,
        'parse_mode': 'HTML'
    }).encode()
    try:
        req = urllib.request.Request(url, data=payload,
            headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
            if body.get('ok'):
                print('[notify_algo_logs] OK', file=sys.stderr)
                return True
            else:
                print(f'[notify_algo_logs] API error: {body}', file=sys.stderr)
                return False
    except Exception as ex:
        print(f'[notify_algo_logs] Error: {ex}', file=sys.stderr)
        return False

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: notify_algo_logs.py <message>', file=sys.stderr)
        sys.exit(1)
    ok = send_algo_log(' '.join(sys.argv[1:]))
    sys.exit(0 if ok else 1)

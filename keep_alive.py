"""稼働確認とDiscordの接続準備確認用のHTTPサーバーを別スレッドで起動する。"""

from flask import Flask
from threading import Thread
import os

app = Flask('')
app.config['BOT_READINESS'] = lambda: False

@app.route('/')
def home():
    return "I'm alive"


@app.route('/ready')
def ready():
    # HTTPの起動とDiscordへの接続完了は別。Renderには後者を確認させる。
    if app.config['BOT_READINESS']():
        return 'Ready', 200
    return 'Discord connection not ready', 503

def run():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '8080')))

def keep_alive(is_ready):
    app.config['BOT_READINESS'] = is_ready
    # Discord側の終了後、HTTPスレッドだけが残って停止を妨げないようにする。
    t = Thread(target=run, daemon=True)
    t.start()

"""稼働確認用のHTTPサーバーを別スレッドで起動する。"""

from flask import Flask
from threading import Thread
import os

app = Flask('')

@app.route('/')
def home():
    return "I'm alive"


def run():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '8080')))

def keep_alive():
    # Discord側の終了後、HTTPスレッドだけが残って停止を妨げないようにする。
    t = Thread(target=run, daemon=True)
    t.start()

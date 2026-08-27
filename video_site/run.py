#!/usr/bin/env python3
import sys
import os
import webbrowser
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app

def open_browser():
    """延迟打开浏览器"""
    threading.Timer(1.5, lambda: webbrowser.open('http://127.0.0.1:3090')).start()

if __name__ == '__main__':
    # 确保数据目录存在
    from config import BASE_DIR
    data_dir = os.path.join(BASE_DIR, 'data')
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    print("=" * 50)
    print("  视频管理系统启动中...")
    print("  访问地址: http://127.0.0.1:3090")
    print("  默认账号: admin / password")
    print("=" * 50)

    # EXE 模式下关闭 debug 并自动打开浏览器
    is_frozen = getattr(sys, 'frozen', False)
    if is_frozen:
        open_browser()
        app.run(debug=False, host='0.0.0.0', port=3090)
    else:
        app.run(debug=True, host='0.0.0.0', port=3090)

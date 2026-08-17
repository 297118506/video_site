#!/usr/bin/env python3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app

if __name__ == '__main__':
    print("=" * 50)
    print("  视频管理系统启动中...")
    print("  访问地址: http://0.0.0.0:3090")
    print("  默认账号: admin / password")
    print("=" * 50)
    app.run(debug=True, host='0.0.0.0', port=3090)

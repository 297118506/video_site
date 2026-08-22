import os
import sys


def _get_base_dir():
    """获取基础目录：EXE 打包后为 EXE 同级目录，开发时为本文件目录"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后，用户数据放在 EXE 同级目录
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _get_resource_dir():
    """获取资源目录：EXE 打包后为 _MEIPASS 临时解压目录（模板/静态文件）"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _get_base_dir()
RESOURCE_DIR = _get_resource_dir()


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'video_site_secret_key_2024'
    DATABASE = os.path.join(BASE_DIR, 'data', 'videos.db')
    OPENLIST_CONFIG_FILE = os.path.join(BASE_DIR, 'data', 'openlist_config.json')
    USER_CONFIG_FILE = os.path.join(BASE_DIR, 'data', 'user_config.json')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    VIDEO_EXTENSIONS = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.m3u8', '.asf', '.m4v', '.rm', '.asx', '.rmvb', '.webm', '.ts', '.mts', '.m2ts', '.vob', '.3gp']
    PLAYER_SUPPORTED_FORMATS = {
        'hls': ['.m3u8'],
        'flv': ['.flv'],
        'native': ['.mp4', '.webm', '.ogg', '.mov', '.m4v']
    }
    DEFAULT_USERS = {
        "admin": {
            "password": "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8",
            "role": "admin",
            "created_at": "2024-01-01"
        }
    }

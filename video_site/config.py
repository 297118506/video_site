import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'video_site_secret_key_2024'
    DATABASE = os.path.join(os.path.dirname(__file__), 'data', 'videos.db')
    OPENLIST_CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'data', 'openlist_config.json')
    USER_CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'data', 'user_config.json')
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

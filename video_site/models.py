import sqlite3
import os
import json
import hashlib
from config import Config

def get_db():
    conn = sqlite3.connect(Config.DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(os.path.dirname(Config.DATABASE), exist_ok=True)
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        slug TEXT UNIQUE,
        parent_id INTEGER DEFAULT 0,
        sort_order INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        cover TEXT,
        category_id INTEGER DEFAULT 0,
        description TEXT,
        series_id INTEGER,
        episode_number INTEGER DEFAULT 0,
        duration TEXT,
        source TEXT DEFAULT 'openlist',
        video_url TEXT,
        video_type TEXT,
        is_series INTEGER DEFAULT 0,
        views INTEGER DEFAULT 0,
        sort_order INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        genre TEXT,
        rating TEXT,
        year TEXT,
        actors TEXT,
        is_short_video INTEGER DEFAULT 0
    )''')
    
    # 迁移：为现有videos表添加新字段
    _migrate_videos_table(c)

    # 迁移：为现有users表添加新字段（合集权限开关）
    _migrate_users_table(c)

    c.execute('''CREATE TABLE IF NOT EXISTS series (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        cover TEXT,
        category_id INTEGER DEFAULT 0,
        description TEXT,
        total_episodes INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS openlist_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        server_url TEXT NOT NULL,
        username TEXT NOT NULL,
        password TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS short_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        slug TEXT UNIQUE,
        parent_id INTEGER DEFAULT 0,
        sort_order INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT DEFAULT 'admin',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        can_access_series INTEGER DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS user_category_permissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        category_id INTEGER NOT NULL,
        category_type TEXT NOT NULL DEFAULT 'normal',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, category_id, category_type)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        video_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, video_id)
    )''')

    # 用户短视频播放标记（按用户维度，需求1修复）
    c.execute('''CREATE TABLE IF NOT EXISTS user_short_played (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        video_id INTEGER NOT NULL,
        played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, video_id)
    )''')

    _init_default_users(c)
    conn.commit()
    conn.close()

def _migrate_videos_table(cursor):
    """迁移现有videos表，添加新字段"""
    new_columns = [
        ('genre', 'TEXT'),
        ('rating', 'TEXT'),
        ('year', 'TEXT'),
        ('actors', 'TEXT'),
        ('is_short_video', 'INTEGER DEFAULT 0'),
        ('is_played', 'INTEGER DEFAULT 0'),
        # 本地视频导入：保存原始本地文件绝对路径，video_url/cover 存流式播放URL
        ('local_file_path', 'TEXT'),
        ('local_cover_path', 'TEXT'),
    ]
    for col_name, col_type in new_columns:
        try:
            cursor.execute(f'ALTER TABLE videos ADD COLUMN {col_name} {col_type}')
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略错误

def _migrate_users_table(cursor):
    """迁移现有 users 表，添加新字段（合集权限开关）"""
    new_columns = [
        ('can_access_series', 'INTEGER DEFAULT 1'),
    ]
    for col_name, col_type in new_columns:
        try:
            cursor.execute(f'ALTER TABLE users ADD COLUMN {col_name} {col_type}')
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略错误

def _init_default_users(cursor):
    cursor.execute('SELECT COUNT(*) FROM users')
    count = cursor.fetchone()[0]
    if count == 0:
        default_hash = hashlib.sha256('password'.encode()).hexdigest()
        cursor.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
                      ('admin', default_hash, 'admin'))

def load_users():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, username, password, role FROM users')
    users = {}
    for row in c.fetchall():
        users[row['username']] = {
            'id': row['id'],
            'password': row['password'],
            'role': row['role']
        }
    conn.close()
    return users

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, hashed):
    return hash_password(password) == hashed

def create_user(username, password, role='user'):
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
                  (username, hash_password(password), role))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def delete_user(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM users WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()

def update_password(user_id, new_password):
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE users SET password = ? WHERE id = ?', (hash_password(new_password), user_id))
    conn.commit()
    conn.close()

def get_all_categories():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM categories ORDER BY sort_order, id')
    categories = [dict(row) for row in c.fetchall()]
    conn.close()
    return categories

def create_category(name, parent_id=0, sort_order=0):
    conn = get_db()
    c = conn.cursor()
    slug = name.lower().replace(' ', '-')
    try:
        c.execute('INSERT INTO categories (name, slug, parent_id, sort_order) VALUES (?, ?, ?, ?)',
                  (name, slug, parent_id, sort_order))
        conn.commit()
        return True, c.lastrowid
    except sqlite3.IntegrityError:
        return False, None
    finally:
        conn.close()

def _collect_child_category_ids(cursor, parent_ids):
    """递归收集所有子孙分类ID"""
    all_ids = list(parent_ids)
    current = list(parent_ids)
    while current:
        placeholders = ','.join(['?' for _ in current])
        cursor.execute(f'SELECT id FROM categories WHERE parent_id IN ({placeholders})', current)
        children = [row['id'] for row in cursor.fetchall()]
        if not children:
            break
        all_ids.extend(children)
        current = children
    return list(set(all_ids))


def delete_category(category_id):
    conn = get_db()
    c = conn.cursor()
    # 收集所有子孙分类ID
    all_cat_ids = _collect_child_category_ids(c, [category_id])
    placeholders = ','.join(['?' for _ in all_cat_ids])
    # 1. 删除这些分类下的所有系列（同时会删除系列的视频，下面单独处理避免依赖顺序）
    # 先删除分类下所有系列中的视频
    c.execute(f'SELECT id FROM series WHERE category_id IN ({placeholders})', all_cat_ids)
    series_ids = [row['id'] for row in c.fetchall()]
    if series_ids:
        series_ph = ','.join(['?' for _ in series_ids])
        c.execute(f'DELETE FROM videos WHERE series_id IN ({series_ph})', series_ids)
    # 2. 删除分类（含子孙）下的所有独立视频（非系列单集或直接属于该分类）
    c.execute(f'DELETE FROM videos WHERE category_id IN ({placeholders})', all_cat_ids)
    # 3. 删除这些分类下的系列
    c.execute(f'DELETE FROM series WHERE category_id IN ({placeholders})', all_cat_ids)
    # 4. 删除分类（含子孙分类）
    c.execute(f'DELETE FROM categories WHERE id IN ({placeholders})', all_cat_ids)
    conn.commit()
    conn.close()


def batch_delete_categories(category_ids):
    conn = get_db()
    c = conn.cursor()
    # 收集所有子孙分类ID
    all_cat_ids = _collect_child_category_ids(c, list(category_ids))
    placeholders = ','.join(['?' for _ in all_cat_ids])
    # 删除这些分类下系列中的视频
    c.execute(f'SELECT id FROM series WHERE category_id IN ({placeholders})', all_cat_ids)
    series_ids = [row['id'] for row in c.fetchall()]
    deleted_videos = 0
    if series_ids:
        series_ph = ','.join(['?' for _ in series_ids])
        c.execute(f'DELETE FROM videos WHERE series_id IN ({series_ph})', series_ids)
        deleted_videos += c.rowcount
    # 删除分类下的所有视频
    c.execute(f'DELETE FROM videos WHERE category_id IN ({placeholders})', all_cat_ids)
    deleted_videos += c.rowcount
    # 删除系列
    c.execute(f'DELETE FROM series WHERE category_id IN ({placeholders})', all_cat_ids)
    # 删除分类
    c.execute(f'DELETE FROM categories WHERE id IN ({placeholders})', all_cat_ids)
    conn.commit()
    affected = c.rowcount
    conn.close()
    return affected

def batch_delete_all_categories():
    """删除全部分类及其下的视频和系列"""
    conn = get_db()
    c = conn.cursor()
    # 删除所有系列中的视频
    c.execute('DELETE FROM videos WHERE series_id IN (SELECT id FROM series WHERE category_id IN (SELECT id FROM categories))')
    # 删除分类下的视频
    c.execute('DELETE FROM videos WHERE category_id IN (SELECT id FROM categories)')
    # 删除分类下的系列
    c.execute('DELETE FROM series WHERE category_id IN (SELECT id FROM categories)')
    # 删除所有分类
    c.execute('DELETE FROM categories')
    conn.commit()
    affected = c.rowcount
    conn.close()
    return affected

def get_category_tree():
    categories = get_all_categories()
    tree = {}
    for cat in categories:
        parent_id = cat.get('parent_id', 0)
        if parent_id not in tree:
            tree[parent_id] = []
        tree[parent_id].append(cat)
    return tree

# ================= 短视频分类 short_categories =================

def get_all_short_categories():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM short_categories ORDER BY sort_order, id')
    categories = [dict(row) for row in c.fetchall()]
    conn.close()
    return categories

def create_short_category(name, parent_id=0, sort_order=0):
    conn = get_db()
    c = conn.cursor()
    slug = name.lower().replace(' ', '-')
    try:
        c.execute('INSERT INTO short_categories (name, slug, parent_id, sort_order) VALUES (?, ?, ?, ?)',
                  (name, slug, parent_id, sort_order))
        conn.commit()
        return True, c.lastrowid
    except sqlite3.IntegrityError:
        return False, None
    finally:
        conn.close()

def _collect_child_short_category_ids(cursor, parent_ids):
    all_ids = list(parent_ids)
    current = list(parent_ids)
    while current:
        placeholders = ','.join(['?' for _ in current])
        cursor.execute(f'SELECT id FROM short_categories WHERE parent_id IN ({placeholders})', current)
        children = [row['id'] for row in cursor.fetchall()]
        if not children:
            break
        all_ids.extend(children)
        current = children
    return list(set(all_ids))

def delete_short_category(category_id):
    conn = get_db()
    c = conn.cursor()
    all_cat_ids = _collect_child_short_category_ids(c, [category_id])
    placeholders = ','.join(['?' for _ in all_cat_ids])
    c.execute(f'DELETE FROM videos WHERE category_id IN ({placeholders}) AND is_short_video = 1', all_cat_ids)
    c.execute(f'DELETE FROM short_categories WHERE id IN ({placeholders})', all_cat_ids)
    conn.commit()
    conn.close()

def batch_delete_short_categories(category_ids):
    conn = get_db()
    c = conn.cursor()
    all_cat_ids = _collect_child_short_category_ids(c, list(category_ids))
    placeholders = ','.join(['?' for _ in all_cat_ids])
    c.execute(f'DELETE FROM videos WHERE category_id IN ({placeholders}) AND is_short_video = 1', all_cat_ids)
    deleted_videos = c.rowcount
    c.execute(f'DELETE FROM short_categories WHERE id IN ({placeholders})', all_cat_ids)
    conn.commit()
    conn.close()
    return deleted_videos

def batch_delete_all_short_categories():
    """删除全部短视频分类及其下的短视频"""
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM videos WHERE category_id IN (SELECT id FROM short_categories) AND is_short_video = 1')
    deleted_videos = c.rowcount
    c.execute('DELETE FROM short_categories')
    conn.commit()
    conn.close()
    return deleted_videos

def get_short_category_tree():
    categories = get_all_short_categories()
    tree = {}
    for cat in categories:
        parent_id = cat.get('parent_id', 0)
        if parent_id not in tree:
            tree[parent_id] = []
        tree[parent_id].append(cat)
    return tree

def get_all_videos(category_id=None, keyword=None, is_series=None, page=1, per_page=20, exclude_series_episodes=False, is_short_video=None, category_ids=None):
    conn = get_db()
    c = conn.cursor()
    query = 'SELECT * FROM videos WHERE 1=1'
    count_query = 'SELECT COUNT(*) as total FROM videos WHERE 1=1'
    params = []
    count_params = []

    if category_id:
        query += ' AND category_id = ?'
        count_query += ' AND category_id = ?'
        params.append(category_id)
        count_params.append(category_id)
    elif category_ids is not None and len(category_ids) > 0:
        # 复数分类过滤（用于按用户权限范围查询"全部"短视频）
        placeholders = ','.join(['?' for _ in category_ids])
        query += f' AND category_id IN ({placeholders})'
        count_query += f' AND category_id IN ({placeholders})'
        params.extend(category_ids)
        count_params.extend(category_ids)
    if keyword:
        query += ' AND (title LIKE ? OR description LIKE ?)'
        count_query += ' AND (title LIKE ? OR description LIKE ?)'
        params.extend([f'%{keyword}%', f'%{keyword}%'])
        count_params.extend([f'%{keyword}%', f'%{keyword}%'])
    if is_series is not None:
        query += ' AND is_series = ?'
        count_query += ' AND is_series = ?'
        params.append(is_series)
        count_params.append(is_series)
    if exclude_series_episodes:
        query += ' AND (series_id IS NULL OR series_id = 0)'
        count_query += ' AND (series_id IS NULL OR series_id = 0)'
    if is_short_video is not None:
        query += ' AND is_short_video = ?'
        count_query += ' AND is_short_video = ?'
        params.append(1 if is_short_video else 0)
        count_params.append(1 if is_short_video else 0)
    
    query += ' ORDER BY sort_order, id DESC'
    
    offset = (page - 1) * per_page
    query += ' LIMIT ? OFFSET ?'
    params.extend([per_page, offset])
    
    c.execute(count_query, count_params)
    total = c.fetchone()['total']
    
    c.execute(query, params)
    videos = [dict(row) for row in c.fetchall()]
    
    total_pages = (total + per_page - 1) // per_page
    
    conn.close()
    return {
        'videos': videos,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages
    }

def get_video(video_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM videos WHERE id = ?', (video_id,))
    video = c.fetchone()
    conn.close()
    return dict(video) if video else None

def get_video_by_url(video_url):
    """根据 video_url 查询是否已存在"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM videos WHERE video_url = ?', (video_url,))
    video = c.fetchone()
    conn.close()
    return dict(video) if video else None

def get_video_by_local_path(file_path):
    """根据本地文件绝对路径查询是否已导入（用于本地导入去重）"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, title FROM videos WHERE local_file_path = ?', (file_path,))
    video = c.fetchone()
    conn.close()
    return dict(video) if video else None

def create_video(data):
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO videos
                 (title, cover, category_id, description, series_id, episode_number,
                  duration, source, video_url, video_type, is_series, sort_order,
                  genre, rating, year, actors, is_short_video,
                  local_file_path, local_cover_path)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (data.get('title'), data.get('cover'), data.get('category_id', 0),
               data.get('description'), data.get('series_id'),
               data.get('episode_number', 0), data.get('duration'),
               data.get('source', 'openlist'), data.get('video_url'),
               data.get('video_type'), data.get('is_series', 0),
               data.get('sort_order', 0),
               data.get('genre'), data.get('rating'),
               data.get('year'), data.get('actors'),
               data.get('is_short_video', 0),
               data.get('local_file_path'), data.get('local_cover_path')))
    conn.commit()
    video_id = c.lastrowid
    conn.close()
    return video_id


def update_video(video_id, data):
    conn = get_db()
    c = conn.cursor()
    fields = []
    values = []
    for key in ['title', 'cover', 'category_id', 'description', 'series_id',
                'episode_number', 'duration', 'video_url', 'video_type',
                'is_series', 'sort_order', 'genre', 'rating', 'year', 'actors',
                'is_short_video', 'local_file_path', 'local_cover_path']:
        if key in data:
            fields.append(f'{key} = ?')
            values.append(data[key])
    if fields:
        values.append(video_id)
        fields.append('updated_at = CURRENT_TIMESTAMP')
        c.execute(f'UPDATE videos SET {", ".join(fields)} WHERE id = ?', values)
        conn.commit()
    conn.close()

def delete_video(video_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM videos WHERE id = ?', (video_id,))
    conn.commit()
    conn.close()

def batch_delete_videos(video_ids):
    conn = get_db()
    c = conn.cursor()
    placeholders = ','.join(['?' for _ in video_ids])
    c.execute(f'DELETE FROM videos WHERE id IN ({placeholders})', video_ids)
    conn.commit()
    affected = c.rowcount
    conn.close()
    return affected

def batch_delete_all_videos(is_short_video=False):
    """删除全部视频（is_short_video=True 时仅删除短视频）"""
    conn = get_db()
    c = conn.cursor()
    if is_short_video:
        c.execute('DELETE FROM videos WHERE is_short_video = 1')
    else:
        c.execute('DELETE FROM videos WHERE is_short_video = 0 OR is_short_video IS NULL')
    conn.commit()
    affected = c.rowcount
    conn.close()
    return affected

def increment_views(video_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE videos SET views = views + 1 WHERE id = ?', (video_id,))
    conn.commit()
    conn.close()

# ================= 短视频播放标记（需求1） =================

def mark_short_played(video_id, user_id=None):
    """标记短视频为已播放（按用户维度），若该用户可访问的短视频都已播放则自动清空。

    user_id: 传入用户ID则按用户维度记录；None则回退全局标记（兼容旧逻辑）。
    返回: (marked: bool, reset: bool, played_count: int, total_count: int)
    """
    conn = get_db()
    c = conn.cursor()
    # 先确认是短视频
    c.execute('SELECT id, is_short_video FROM videos WHERE id = ?', (video_id,))
    row = c.fetchone()
    if not row or not row['is_short_video']:
        conn.close()
        return False, False, 0, 0

    if user_id is None:
        # 回退：全局标记（兼容旧逻辑/未登录场景）
        c.execute('UPDATE videos SET is_played = 1 WHERE id = ? AND (is_played IS NULL OR is_played = 0)', (video_id,))
        conn.commit()
        c.execute('SELECT COUNT(*) FROM videos WHERE is_short_video = 1')
        total_count = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM videos WHERE is_short_video = 1 AND is_played = 1')
        played_count = c.fetchone()[0]
        reset = False
        if total_count > 0 and played_count >= total_count:
            c.execute('UPDATE videos SET is_played = 0 WHERE is_short_video = 1')
            conn.commit()
            played_count = 0
            reset = True
        conn.close()
        return True, reset, played_count, total_count

    # 按用户维度标记
    try:
        c.execute('INSERT INTO user_short_played (user_id, video_id) VALUES (?, ?)', (user_id, video_id))
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # 已标记过

    # 获取用户的短视频分类权限
    c.execute('SELECT category_id FROM user_category_permissions WHERE user_id = ? AND category_type = ?', (user_id, 'short'))
    allowed_ids = [r['category_id'] for r in c.fetchall()]

    if not allowed_ids:
        # 无限制：全部短视频
        c.execute('SELECT COUNT(*) FROM videos WHERE is_short_video = 1')
        total_count = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM user_short_played WHERE user_id = ?', (user_id,))
        played_count = c.fetchone()[0]
    else:
        # 有分类限制：仅统计可访问的短视频
        placeholders = ','.join(['?' for _ in allowed_ids])
        c.execute(f'SELECT COUNT(*) FROM videos WHERE is_short_video = 1 AND category_id IN ({placeholders})', allowed_ids)
        total_count = c.fetchone()[0]
        c.execute(f'''SELECT COUNT(*) FROM user_short_played up
                      JOIN videos v ON up.video_id = v.id
                      WHERE up.user_id = ? AND v.is_short_video = 1 AND v.category_id IN ({placeholders})''',
                  [user_id] + allowed_ids)
        played_count = c.fetchone()[0]

    reset = False
    if total_count > 0 and played_count >= total_count:
        # 该用户可访问的短视频全部播完 → 清空该用户的标记
        c.execute('DELETE FROM user_short_played WHERE user_id = ?', (user_id,))
        conn.commit()
        played_count = 0
        reset = True
    conn.close()
    return True, reset, played_count, total_count

def get_short_played_status(category_id=None, user_id=None, allowed_category_ids=None):
    """获取短视频播放状态（按用户维度）：已播放ID列表、已播放数、总数、未播放ID列表。

    category_id: None=全部, 0=未分类, 其它=指定短分类ID（含子孙分类）
    user_id: 传入则按用户维度查询；None则回退全局 is_played 字段
    allowed_category_ids: 用户可访问的短视频分类ID列表。
        - None: 不做权限过滤（全部可见）
        - 非空列表: 仅统计这些分类内的视频（仅在 category_id 为 None 即"全部"时生效）
    """
    conn = get_db()
    c = conn.cursor()
    cat_filter = ''
    params = []
    if category_id is None:
        # 全部：若用户有分类权限限制，按权限过滤
        if allowed_category_ids is not None and len(allowed_category_ids) > 0:
            placeholders = ','.join(['?' for _ in allowed_category_ids])
            cat_filter = f' AND category_id IN ({placeholders})'
            params = list(allowed_category_ids)
        else:
            cat_filter = ''
    elif category_id == 0:
        cat_filter = ' AND (category_id IS NULL OR category_id = 0)'
    else:
        # 收集子孙分类
        all_ids = _collect_child_short_category_ids(c, [category_id])
        placeholders = ','.join(['?' for _ in all_ids])
        cat_filter = f' AND category_id IN ({placeholders})'
        params = all_ids

    if user_id is not None:
        # 按用户维度：从 user_short_played 表查询
        c.execute(f'''SELECT v.id FROM videos v
                      WHERE v.is_short_video = 1{cat_filter}''', params)
        all_rows = c.fetchall()
        total_count = len(all_rows)
        all_ids_set = {r['id'] for r in all_rows}
        c.execute('SELECT video_id FROM user_short_played WHERE user_id = ?', (user_id,))
        played_set = {r['video_id'] for r in c.fetchall()}
        played_ids = [vid for vid in all_ids_set if vid in played_set]
        unplayed_ids = [vid for vid in all_ids_set if vid not in played_set]
    else:
        # 回退：全局 is_played 字段
        c.execute(f'SELECT id, is_played FROM videos WHERE is_short_video = 1{cat_filter}', params)
        rows = c.fetchall()
        total_count = len(rows)
        played_ids = [r['id'] for r in rows if r['is_played']]
        unplayed_ids = [r['id'] for r in rows if not r['is_played']]
    conn.close()
    return {
        'played_ids': played_ids,
        'unplayed_ids': unplayed_ids,
        'played_count': len(played_ids),
        'unplayed_count': len(unplayed_ids),
        'total_count': total_count,
    }

def reset_all_short_played(user_id=None):
    """手动清空短视频播放标记。

    user_id: 传入则仅清空该用户的标记；None则清空全部（含全局 is_played 字段）。
    """
    conn = get_db()
    c = conn.cursor()
    if user_id is not None:
        c.execute('DELETE FROM user_short_played WHERE user_id = ?', (user_id,))
    else:
        c.execute('DELETE FROM user_short_played')
        c.execute('UPDATE videos SET is_played = 0 WHERE is_short_video = 1')
    conn.commit()
    affected = c.rowcount
    conn.close()
    return affected

def get_all_users_short_played_stats():
    """获取所有用户的短视频播放进度统计（用于仪表盘展示）。

    返回: list of {user_id, username, played_count, total_count, pct}
    """
    conn = get_db()
    c = conn.cursor()
    # 获取所有用户
    c.execute('SELECT id, username FROM users ORDER BY id')
    users = [{'id': r['id'], 'username': r['username']} for r in c.fetchall()]
    # 全部短视频总数
    c.execute('SELECT COUNT(*) FROM videos WHERE is_short_video = 1')
    total_shorts = c.fetchone()[0]
    # 每个用户的播放数
    result = []
    for u in users:
        # 获取该用户可访问的短视频总数
        c.execute('SELECT category_id FROM user_category_permissions WHERE user_id = ? AND category_type = ?', (u['id'], 'short'))
        allowed_ids = [r['category_id'] for r in c.fetchall()]
        if not allowed_ids:
            user_total = total_shorts
            c.execute('SELECT COUNT(*) FROM user_short_played WHERE user_id = ?', (u['id'],))
            played = c.fetchone()[0]
        else:
            placeholders = ','.join(['?' for _ in allowed_ids])
            # 先获取该用户可访问的短视频总数
            c.execute(f'SELECT COUNT(*) FROM videos WHERE is_short_video = 1 AND category_id IN ({placeholders})', allowed_ids)
            user_total = c.fetchone()[0]
            # 再获取已播放数
            c.execute(f'''SELECT COUNT(*) FROM user_short_played up
                          JOIN videos v ON up.video_id = v.id
                          WHERE up.user_id = ? AND v.is_short_video = 1 AND v.category_id IN ({placeholders})''',
                      [u['id']] + allowed_ids)
            played = c.fetchone()[0]
        pct = (played / user_total * 100) if user_total > 0 else 0
        result.append({
            'user_id': u['id'],
            'username': u['username'],
            'played_count': played,
            'total_count': user_total,
            'pct': round(pct, 1),
        })
    conn.close()
    return result

def _fetch_random_videos(c, base_filter, filter_params, limit):
    """抽取随机视频：子查询先抽随机 id，外层主键 IN 查询完整记录。

    避免对全表 SELECT * ORDER BY RANDOM() 生成大量随机键并搬运整行数据，
    子查询只对 id 列做随机排序，外层按主键取行，性能更优。
    base_filter 中的条件不能带 v. 别名前缀（子查询表为 videos 本表）。
    """
    if not limit or limit <= 0:
        return []
    ids_query = f'SELECT id FROM videos WHERE is_short_video = 1{base_filter} ORDER BY RANDOM() LIMIT ?'
    c.execute(ids_query, list(filter_params) + [limit])
    ids = [r[0] for r in c.fetchall()]
    if not ids:
        return []
    placeholders = ','.join(['?' for _ in ids])
    c.execute(f'SELECT * FROM videos WHERE id IN ({placeholders})', ids)
    return [dict(r) for r in c.fetchall()]

def get_shorts_for_random(category_id=None, exclude_played=False, limit=500, user_id=None, allowed_category_ids=None):
    """获取短视频列表（用于随机播放，支持排除已播放，按用户维度）。

    规则: exclude_played=True 时优先返回未播放；若未播放为空则自动回退到全部。
    返回: (videos_list, used_fallback: bool, played_count, total_count)
    allowed_category_ids: 用户可访问的短视频分类ID列表。
        - None: 不做权限过滤（全部可见）
        - 非空列表: 仅查询这些分类内的视频（仅在 category_id 为 None 即"全部"时生效）
    """
    conn = get_db()
    c = conn.cursor()
    cat_filter = ''
    params = []
    if category_id:
        all_ids = _collect_child_short_category_ids(c, [category_id])
        placeholders = ','.join(['?' for _ in all_ids])
        cat_filter = f' AND category_id IN ({placeholders})'
        params = all_ids
    elif allowed_category_ids is not None and len(allowed_category_ids) > 0:
        # 全部请求 + 用户有分类权限限制 → 按权限过滤
        placeholders = ','.join(['?' for _ in allowed_category_ids])
        cat_filter = f' AND category_id IN ({placeholders})'
        params = list(allowed_category_ids)

    # 统计
    c.execute(f'SELECT COUNT(*) FROM videos WHERE is_short_video = 1{cat_filter}', params)
    total_count = c.fetchone()[0]

    if user_id is not None:
        # 按用户维度统计已播放数
        c.execute(f'''SELECT COUNT(*) FROM user_short_played up
                      JOIN videos v ON up.video_id = v.id
                      WHERE up.user_id = ? AND v.is_short_video = 1{cat_filter}''',
                  [user_id] + params)
        played_count = c.fetchone()[0]
        # 子查询版本（不带 v. 前缀，用于随机抽 id 的内层查询）
        played_filter_inner = f''' AND id NOT IN (
            SELECT video_id FROM user_short_played WHERE user_id = ?
        )'''
        played_params = [user_id] + params
    else:
        # 回退：全局 is_played
        c.execute(f"SELECT COUNT(*) FROM videos WHERE is_short_video = 1 AND COALESCE(is_played, 0) = 1{cat_filter}", params)
        played_count = c.fetchone()[0]
        # 子查询版本（不带 v. 前缀，用于随机抽 id 的内层查询）
        played_filter_inner = ' AND COALESCE(is_played, 0) = 0'
        played_params = list(params)

    used_fallback = False
    if exclude_played:
        videos = _fetch_random_videos(c, played_filter_inner + cat_filter, played_params, limit)
    else:
        videos = _fetch_random_videos(c, cat_filter, params, limit)

    if exclude_played and not videos:
        used_fallback = True
        videos = _fetch_random_videos(c, cat_filter, params, limit)
    conn.close()
    return videos, used_fallback, played_count, total_count

def get_all_series(category_id=None, keyword=None, page=1, per_page=20):
    conn = get_db()
    c = conn.cursor()
    base_query = 'FROM series s WHERE 1=1'
    params = []
    if category_id:
        base_query += ' AND s.category_id = ?'
        params.append(category_id)
    if keyword:
        base_query += ' AND (s.title LIKE ? OR s.description LIKE ?)'
        params.extend([f'%{keyword}%', f'%{keyword}%'])
    
    c.execute(f'SELECT COUNT(*) {base_query}', params)
    total = c.fetchone()[0]
    
    query = f'SELECT s.*, (SELECT COUNT(*) FROM videos v WHERE v.series_id = s.id) as episode_count {base_query} ORDER BY s.id DESC LIMIT ? OFFSET ?'
    c.execute(query, params + [per_page, (page - 1) * per_page])
    series_list = [dict(row) for row in c.fetchall()]
    conn.close()
    return {
        'series_list': series_list,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page if per_page > 0 else 0
    }

def get_series(series_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM series WHERE id = ?', (series_id,))
    series = c.fetchone()
    conn.close()
    return dict(series) if series else None

def create_series(data):
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO series (title, cover, category_id, description, total_episodes) VALUES (?, ?, ?, ?, ?)',
              (data.get('title'), data.get('cover'), data.get('category_id', 0),
               data.get('description'), data.get('total_episodes', 0)))
    conn.commit()
    series_id = c.lastrowid
    conn.close()
    return series_id

def update_series(series_id, data):
    conn = get_db()
    c = conn.cursor()
    fields = []
    values = []
    for key in ['title', 'cover', 'category_id', 'description', 'total_episodes']:
        if key in data:
            fields.append(f'{key} = ?')
            values.append(data[key])
    if fields:
        values.append(series_id)
        c.execute(f'UPDATE series SET {", ".join(fields)} WHERE id = ?', values)
        conn.commit()
    conn.close()

def delete_series(series_id):
    conn = get_db()
    c = conn.cursor()
    # 删除该系列下的所有单集视频
    c.execute('DELETE FROM videos WHERE series_id = ?', (series_id,))
    # 删除系列本身
    c.execute('DELETE FROM series WHERE id = ?', (series_id,))
    conn.commit()
    conn.close()

def batch_delete_series(series_ids):
    conn = get_db()
    c = conn.cursor()
    placeholders = ','.join(['?' for _ in series_ids])
    # 删除所有系列中的单集视频
    c.execute(f'DELETE FROM videos WHERE series_id IN ({placeholders})', series_ids)
    # 删除系列本身
    c.execute(f'DELETE FROM series WHERE id IN ({placeholders})', series_ids)
    conn.commit()
    affected = c.rowcount
    conn.close()
    return affected

def batch_delete_all_series():
    """删除全部系列（视频保留，仅解除关联）"""
    conn = get_db()
    c = conn.cursor()
    # 解除所有视频与系列的关联
    c.execute('UPDATE videos SET series_id = NULL, is_series = 0 WHERE series_id IS NOT NULL')
    updated = c.rowcount
    # 删除所有系列
    c.execute('DELETE FROM series')
    conn.commit()
    affected = c.rowcount
    conn.close()
    return affected

def get_episodes_by_series(series_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM videos WHERE series_id = ? ORDER BY episode_number, id', (series_id,))
    episodes = [dict(row) for row in c.fetchall()]
    conn.close()
    return episodes

def get_all_openlist_accounts():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM openlist_accounts ORDER BY id')
    accounts = [dict(row) for row in c.fetchall()]
    conn.close()
    return accounts

def create_openlist_account(data):
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO openlist_accounts (name, server_url, username, password) VALUES (?, ?, ?, ?)',
              (data.get('name'), data.get('server_url'), data.get('username'), data.get('password')))
    conn.commit()
    account_id = c.lastrowid
    conn.close()
    return account_id

def delete_openlist_account(account_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM openlist_accounts WHERE id = ?', (account_id,))
    conn.commit()
    conn.close()

def get_video_stats():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) as total, COALESCE(SUM(views), 0) as total_views FROM videos')
    stats = dict(c.fetchone())
    c.execute('SELECT COUNT(*) as total FROM series')
    stats['total_series'] = c.fetchone()['total']
    c.execute('SELECT COUNT(*) as total FROM categories')
    stats['total_categories'] = c.fetchone()['total']
    c.execute('SELECT COUNT(*) as total FROM openlist_accounts')
    stats['total_accounts'] = c.fetchone()['total']
    # ===== 短视频指标（需求2） =====
    c.execute("SELECT COUNT(*) as total, COALESCE(SUM(views), 0) as total_views FROM videos WHERE is_short_video = 1")
    row = c.fetchone()
    stats['total_short_videos'] = row['total'] or 0
    stats['short_views'] = row['total_views'] or 0
    c.execute('SELECT COUNT(*) as total FROM short_categories')
    stats['total_short_categories'] = c.fetchone()['total'] or 0
    c.execute("SELECT COUNT(DISTINCT video_id) FROM user_short_played")
    stats['played_short_count'] = c.fetchone()[0] or 0
    # 普通视频数 = 总数 - 短视频数
    stats['total_normal_videos'] = max((stats.get('total') or 0) - stats['total_short_videos'], 0)
    conn.close()
    return stats


# ================= 用户分类权限（需求1） =================

def set_user_permissions(user_id, category_ids, category_type='normal'):
    """设置用户可查看的分类权限（覆盖式）。

    category_ids: list[int]，为空列表表示清除该类型的所有限制（=全部可见）。
    category_type: 'normal' 或 'short'。
    """
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM user_category_permissions WHERE user_id = ? AND category_type = ?',
              (user_id, category_type))
    for cid in category_ids:
        c.execute('INSERT OR IGNORE INTO user_category_permissions (user_id, category_id, category_type) VALUES (?, ?, ?)',
                  (user_id, cid, category_type))
    conn.commit()
    conn.close()

def get_user_permissions(user_id):
    """获取用户的分类权限列表。

    返回: {'normal': [id...], 'short': [id...], 'series': bool}
    若 normal/short 为空列表，表示该类型全部可见。
    series 为布尔值，True=可访问合集，False=不可访问。
    """
    conn = get_db()
    c = conn.cursor()
    result = {'normal': [], 'short': [], 'series': True}
    for ctype in ('normal', 'short'):
        c.execute('SELECT category_id FROM user_category_permissions WHERE user_id = ? AND category_type = ? ORDER BY category_id',
                  (user_id, ctype))
        result[ctype] = [row['category_id'] for row in c.fetchall()]
    c.execute('SELECT can_access_series FROM users WHERE id = ?', (user_id,))
    row = c.fetchone()
    result['series'] = bool(row['can_access_series']) if row and row['can_access_series'] is not None else True
    conn.close()
    return result

def get_user_series_access(user_id):
    """获取用户是否有合集访问权限。默认 True（向后兼容）。"""
    if not user_id:
        return True
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT can_access_series FROM users WHERE id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    if row and row['can_access_series'] is not None:
        return bool(row['can_access_series'])
    return True

def set_user_series_access(user_id, can_access):
    """设置用户的合集访问权限。can_access: bool"""
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE users SET can_access_series = ? WHERE id = ?',
              (1 if can_access else 0, user_id))
    conn.commit()
    conn.close()

def get_user_allowed_category_ids(user_id, category_type='normal'):
    """获取用户某类型可查看的分类ID列表。

    返回 None 表示全部可见（无限制）。
    """
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT category_id FROM user_category_permissions WHERE user_id = ? AND category_type = ? ORDER BY category_id',
              (user_id, category_type))
    ids = [row['category_id'] for row in c.fetchall()]
    conn.close()
    return ids if ids else None


# ================= 收藏功能（需求2） =================

def add_favorite(user_id, video_id):
    """添加收藏，返回 (success, already_exists)"""
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute('INSERT INTO favorites (user_id, video_id) VALUES (?, ?)', (user_id, video_id))
        conn.commit()
        return True, False
    except sqlite3.IntegrityError:
        return False, True
    finally:
        conn.close()

def remove_favorite(user_id, video_id):
    """取消收藏"""
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM favorites WHERE user_id = ? AND video_id = ?', (user_id, video_id))
    conn.commit()
    affected = c.rowcount
    conn.close()
    return affected > 0

def is_favorited(user_id, video_id):
    """检查是否已收藏"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT 1 FROM favorites WHERE user_id = ? AND video_id = ?', (user_id, video_id))
    result = c.fetchone() is not None
    conn.close()
    return result

def get_user_favorite_ids(user_id):
    """获取用户已收藏的 video_id 集合"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT video_id FROM favorites WHERE user_id = ?', (user_id,))
    ids = [row['video_id'] for row in c.fetchall()]
    conn.close()
    return ids

def get_user_favorite_videos(user_id):
    """获取用户收藏的完整视频记录，单次 JOIN 查询，按收藏时间倒序（最新收藏在前）。"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT v.* FROM videos v
        JOIN favorites f ON v.id = f.video_id
        WHERE f.user_id = ?
        ORDER BY f.created_at DESC, f.id DESC
    ''', (user_id,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_all_favorites(page=1, per_page=20, keyword=''):
    """后台管理：获取所有收藏列表（含分页）"""
    conn = get_db()
    c = conn.cursor()
    base_query = 'FROM favorites f JOIN users u ON f.user_id = u.id JOIN videos v ON f.video_id = v.id WHERE 1=1'
    params = []
    if keyword:
        base_query += ' AND (v.title LIKE ? OR u.username LIKE ?)'
        params.extend([f'%{keyword}%', f'%{keyword}%'])

    c.execute(f'SELECT COUNT(*) {base_query}', params)
    total = c.fetchone()[0]

    query = f'''SELECT f.id, f.user_id, u.username, f.video_id, v.title, v.cover,
                       v.is_short_video, f.created_at
                {base_query}
                ORDER BY f.id DESC LIMIT ? OFFSET ?'''
    c.execute(query, params + [per_page, (page - 1) * per_page])
    favorites = [dict(row) for row in c.fetchall()]
    conn.close()
    return {
        'favorites': favorites,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page if per_page > 0 else 0
    }

def delete_favorite(favorite_id):
    """删除收藏记录"""
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM favorites WHERE id = ?', (favorite_id,))
    conn.commit()
    conn.close()

def batch_delete_favorites(favorite_ids):
    """批量删除收藏记录"""
    if not favorite_ids:
        return 0
    conn = get_db()
    c = conn.cursor()
    placeholders = ','.join(['?' for _ in favorite_ids])
    c.execute(f'DELETE FROM favorites WHERE id IN ({placeholders})', favorite_ids)
    conn.commit()
    affected = c.rowcount
    conn.close()
    return affected

def batch_delete_all_favorites():
    """删除全部收藏记录"""
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM favorites')
    conn.commit()
    affected = c.rowcount
    conn.close()
    return affected

def get_db_stats():
    """获取数据库统计信息：文件大小 + 各表行数（用于数据库管理页面展示）"""
    stats = {
        'file_size': 0,
        'tables': {}
    }
    try:
        stats['file_size'] = os.path.getsize(Config.DATABASE)
    except OSError:
        pass
    table_names = [
        'videos', 'series', 'categories', 'short_categories',
        'users', 'openlist_accounts', 'user_category_permissions',
        'favorites', 'user_short_played'
    ]
    try:
        conn = get_db()
        c = conn.cursor()
        for t in table_names:
            try:
                c.execute(f'SELECT COUNT(*) FROM {t}')
                stats['tables'][t] = c.fetchone()[0]
            except sqlite3.Error:
                stats['tables'][t] = 0
        conn.close()
    except sqlite3.Error:
        pass
    return stats

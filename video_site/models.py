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
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        ('is_played', 'INTEGER DEFAULT 0')
    ]
    for col_name, col_type in new_columns:
        try:
            cursor.execute(f'ALTER TABLE videos ADD COLUMN {col_name} {col_type}')
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

def get_short_category_tree():
    categories = get_all_short_categories()
    tree = {}
    for cat in categories:
        parent_id = cat.get('parent_id', 0)
        if parent_id not in tree:
            tree[parent_id] = []
        tree[parent_id].append(cat)
    return tree

def get_all_videos(category_id=None, keyword=None, is_series=None, page=1, per_page=20, exclude_series_episodes=False, is_short_video=None):
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

def create_video(data):
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO videos 
                 (title, cover, category_id, description, series_id, episode_number, 
                  duration, source, video_url, video_type, is_series, sort_order,
                  genre, rating, year, actors, is_short_video)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (data.get('title'), data.get('cover'), data.get('category_id', 0),
               data.get('description'), data.get('series_id'), 
               data.get('episode_number', 0), data.get('duration'),
               data.get('source', 'openlist'), data.get('video_url'),
               data.get('video_type'), data.get('is_series', 0),
               data.get('sort_order', 0),
               data.get('genre'), data.get('rating'),
               data.get('year'), data.get('actors'),
               data.get('is_short_video', 0)))
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
                'is_short_video']:
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

def increment_views(video_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE videos SET views = views + 1 WHERE id = ?', (video_id,))
    conn.commit()
    conn.close()

# ================= 短视频播放标记（需求1） =================

def mark_short_played(video_id):
    """标记短视频为已播放，若所有短视频都已播放则自动清空标记。

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
    # 标记为已播放
    c.execute('UPDATE videos SET is_played = 1 WHERE id = ? AND (is_played IS NULL OR is_played = 0)', (video_id,))
    conn.commit()
    # 统计所有短视频的播放情况
    c.execute('SELECT COUNT(*) FROM videos WHERE is_short_video = 1')
    total_count = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM videos WHERE is_short_video = 1 AND is_played = 1')
    played_count = c.fetchone()[0]
    reset = False
    if total_count > 0 and played_count >= total_count:
        # 全部播完 → 自动清空标记
        c.execute('UPDATE videos SET is_played = 0 WHERE is_short_video = 1')
        conn.commit()
        played_count = 0
        reset = True
    conn.close()
    return True, reset, played_count, total_count

def get_short_played_status(category_id=None):
    """获取短视频播放状态：已播放ID列表、已播放数、总数、未播放ID列表。

    category_id: None=全部, 0=未分类, 其它=指定短分类ID（含子孙分类）
    """
    conn = get_db()
    c = conn.cursor()
    cat_filter = ''
    params = []
    if category_id is None:
        cat_filter = ''
    elif category_id == 0:
        cat_filter = ' AND (category_id IS NULL OR category_id = 0)'
    else:
        # 收集子孙分类
        all_ids = _collect_child_short_category_ids(c, [category_id])
        placeholders = ','.join(['?' for _ in all_ids])
        cat_filter = f' AND category_id IN ({placeholders})'
        params = all_ids
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

def reset_all_short_played():
    """手动清空所有短视频播放标记。"""
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE videos SET is_played = 0 WHERE is_short_video = 1')
    conn.commit()
    affected = c.rowcount
    conn.close()
    return affected

# ================= 短视频列表查询（支持排除已播放） =================

def get_shorts_for_random(category_id=None, exclude_played=False, limit=500):
    """获取短视频列表（用于随机播放，支持排除已播放）。

    规则: exclude_played=True 时优先返回未播放；若未播放为空则自动回退到全部。
    返回: (videos_list, used_fallback: bool, played_count, total_count)
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
    # 统计（用于返回状态）
    c.execute(f'SELECT COUNT(*) FROM videos WHERE is_short_video = 1{cat_filter}', params)
    total_count = c.fetchone()[0]
    c.execute(f"SELECT COUNT(*) FROM videos WHERE is_short_video = 1 AND COALESCE(is_played, 0) = 1{cat_filter}", params)
    played_count = c.fetchone()[0]
    used_fallback = False
    query = 'SELECT * FROM videos WHERE is_short_video = 1'
    q_params = list(params)
    if exclude_played:
        query += ' AND COALESCE(is_played, 0) = 0'
    query += cat_filter + ' ORDER BY id DESC LIMIT ?'
    q_params.append(limit)
    c.execute(query, q_params)
    videos = [dict(r) for r in c.fetchall()]
    if exclude_played and not videos:
        # 未播放为空 → 自动回退到全部（此时外部可提示已重置，或由 mark_short_played 触发重置）
        used_fallback = True
        fb_query = 'SELECT * FROM videos WHERE is_short_video = 1' + cat_filter + ' ORDER BY id DESC LIMIT ?'
        c.execute(fb_query, list(params) + [limit])
        videos = [dict(r) for r in c.fetchall()]
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
    c.execute("SELECT COUNT(*) FROM videos WHERE is_short_video = 1 AND COALESCE(is_played, 0) = 1")
    stats['played_short_count'] = c.fetchone()[0] or 0
    # 普通视频数 = 总数 - 短视频数
    stats['total_normal_videos'] = max((stats.get('total') or 0) - stats['total_short_videos'], 0)
    conn.close()
    return stats

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, abort, send_file, after_this_request
import os
import sys
import json
import re
import sqlite3
import shutil
import tempfile
import mimetypes
from datetime import datetime
from functools import wraps
import requests
from urllib.parse import unquote, urlparse
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config, RESOURCE_DIR, BASE_DIR
from models import (
    init_db, get_db, load_users, hash_password, verify_password,
    create_user, delete_user, update_password, get_all_categories, create_category,
    delete_category, batch_delete_categories, batch_delete_all_categories, get_category_tree,
    get_all_short_categories, create_short_category,
    delete_short_category, batch_delete_short_categories, batch_delete_all_short_categories, get_short_category_tree,
    get_all_videos, get_video, get_video_by_url, get_video_by_local_path, create_video, update_video, delete_video, increment_views,
    batch_delete_videos, batch_delete_all_videos,
    get_all_series, get_series, create_series, update_series, delete_series, batch_delete_series, batch_delete_all_series, get_episodes_by_series,
    get_all_openlist_accounts, create_openlist_account, delete_openlist_account,
    get_video_stats,
    mark_short_played, get_short_played_status, reset_all_short_played, get_shorts_for_random,
    get_all_users_short_played_stats,
    set_user_permissions, get_user_permissions, get_user_allowed_category_ids,
    get_user_series_access, set_user_series_access,
    add_favorite, remove_favorite, is_favorited, get_user_favorite_ids,
    get_user_favorite_videos,
    get_all_favorites, delete_favorite, batch_delete_favorites, batch_delete_all_favorites,
    get_db_stats,
    # 图集模块
    get_all_album_categories, get_album_category, create_album_category, update_album_category,
    delete_album_category, batch_delete_album_categories, batch_delete_all_album_categories, get_album_category_tree,
    get_all_albums, get_album, create_album, update_album, delete_album,
    batch_delete_albums, batch_delete_all_albums, increment_album_views,
    get_album_images, add_album_images, delete_album_image, batch_delete_album_images,
    update_album_images_order, get_album_stats,
)
from alist_api import OpenListApi
from nfo_parser import parse_nfo_content, get_nfo_file_for_video, extract_nfo_metadata

app = Flask(__name__,
            template_folder=os.path.join(RESOURCE_DIR, 'templates'),
            static_folder=os.path.join(RESOURCE_DIR, 'static'))
app.config['SECRET_KEY'] = Config.SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = 86400
# 数据库管理：允许导入较大的数据库备份文件（上限 512MB）
app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024
# 启用 ProxyFix：信任反向代理转发的 X-Forwarded-* 头，
# 使 request.host_url / scheme 反映客户端真实访问地址（公网域名+协议）。
# 局域网直连（无 X-Forwarded 头）时自动回退为原始行为，不影响本地使用。
# 反向代理需配合设置：proxy_set_header Host $host; X-Forwarded-Proto $scheme;
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

init_db()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def api_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'error': '未登录或会话已过期，请重新登录'}), 401
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login', next=request.url))
        if session.get('user_role') != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

def _get_current_user_id():
    """从 session 或 Basic Auth 获取当前用户ID（用于按用户维度的短视频播放标记）"""
    if session.get('logged_in'):
        return session.get('user_id')
    auth = request.authorization
    if auth and auth.username and auth.password:
        users = load_users()
        user = users.get(auth.username)
        if user and verify_password(auth.password, user['password']):
            return user['id']
    return None

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if not username or not password:
            return render_template('login.html', error='请输入用户名和密码')
        users = load_users()
        user = users.get(username)
        if user and verify_password(password, user['password']):
            session['logged_in'] = True
            session['username'] = username
            session['user_id'] = user['id']
            session['user_role'] = user['role']
            session.permanent = True
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('index'))
        return render_template('login.html', error='用户名或密码错误')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    categories = get_all_categories()
    # 排序：有子分类的父分类排在无子分类的父分类前，子分类紧跟各自父分类后
    parent_ids = {c['id'] for c in categories if c.get('parent_id', 0) == 0}
    sub_parent_set = {c.get('parent_id', 0) for c in categories if c.get('parent_id', 0) in parent_ids}
    categories = sorted(categories, key=lambda c: (
        c.get('parent_id', 0),                          # 先按父级分组，父分类(parent=0)在最前，然后各子分类跟随其父
        0 if (c.get('parent_id', 0) == 0 and c['id'] in sub_parent_set) else 1,  # 父分类：有子分类的排前面
        c.get('sort_order', 0),
        c.get('id', 0)
    ))
    keyword = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    if keyword:
        result = get_all_videos(keyword=keyword, page=page, per_page=per_page, is_short_video=False)
    else:
        result = get_all_videos(page=page, per_page=per_page, exclude_series_episodes=True, is_short_video=False)
    
    videos = result['videos']
    total = result['total']
    total_pages = result['total_pages']
    
    series_list = (get_all_series(keyword=keyword, per_page=50) if keyword else get_all_series(per_page=50))['series_list']
    recent_videos = sorted(videos, key=lambda x: x.get('id', 0), reverse=True)
    
    return render_template('index.html',
                         categories=categories,
                         recent_videos=recent_videos,
                         series_list=series_list[:8],
                         keyword=keyword,
                         page=page,
                         total_pages=total_pages,
                         total=total,
                         active_tab='home')

@app.route('/category/<int:category_id>')
@login_required
def category_videos(category_id):
    categories = get_all_categories()
    # 排序：有子分类的父分类排在无子分类的父分类前，子分类紧跟各自父分类后
    parent_ids = {c['id'] for c in categories if c.get('parent_id', 0) == 0}
    sub_parent_set = {c.get('parent_id', 0) for c in categories if c.get('parent_id', 0) in parent_ids}
    categories = sorted(categories, key=lambda c: (
        c.get('parent_id', 0),
        0 if (c.get('parent_id', 0) == 0 and c['id'] in sub_parent_set) else 1,
        c.get('sort_order', 0),
        c.get('id', 0)
    ))
    page = request.args.get('page', 1, type=int)
    per_page = 20
    result = get_all_videos(category_id=category_id, page=page, per_page=per_page, exclude_series_episodes=True, is_short_video=False)
    videos = result['videos']
    series_list = get_all_series(category_id=category_id, per_page=50)['series_list']
    current_category = next((c for c in categories if c['id'] == category_id), None)
    return render_template('index.html',
                         categories=categories,
                         recent_videos=videos,
                         series_list=series_list,
                         current_category=current_category,
                         page=page,
                         total_pages=result['total_pages'],
                         total=result['total'],
                         active_tab='home')

@app.route('/play/<int:video_id>')
@login_required
def play_video(video_id):
    video = get_video(video_id)
    if not video:
        abort(404)
    increment_views(video_id)
    related_result = get_all_videos(category_id=video.get('category_id'), per_page=50, exclude_series_episodes=True, is_short_video=False)
    related_videos = related_result['videos'][:12]
    episodes = []
    if video.get('series_id'):
        episodes = get_episodes_by_series(video['series_id'])
    return render_template('player.html',
                         video=video,
                         related_videos=related_videos,
                         episodes=episodes,
                         active_tab='player')

@app.route('/video/<int:video_id>')
@login_required
def video_detail(video_id):
    """视频详情页：展示视频元数据（含 NFO 信息），点击播放按钮再跳转到播放页"""
    video = get_video(video_id)
    if not video:
        abort(404)
    related_result = get_all_videos(category_id=video.get('category_id'), per_page=50, exclude_series_episodes=True, is_short_video=False)
    related_videos = [v for v in related_result['videos'] if v.get('id') != video_id][:8]
    episodes = []
    if video.get('series_id'):
        episodes = get_episodes_by_series(video['series_id'])
    return render_template('video_detail.html',
                         video=video,
                         related_videos=related_videos,
                         episodes=episodes,
                         active_tab='home')

@app.route('/series/<int:series_id>')
@login_required
def series_detail(series_id):
    # 合集权限校验（admin 角色不受限）
    uid = session.get('user_id')
    user_role = session.get('role', 'user')
    if user_role != 'admin' and not get_user_series_access(uid):
        abort(403)
    series = get_series(series_id)
    if not series:
        abort(404)
    episodes = get_episodes_by_series(series_id)
    categories = get_all_categories()
    return render_template('player.html',
                         video=None,
                         series=series,
                         episodes=episodes,
                         categories=categories,
                         active_tab='player')


@app.route('/shorts')
@login_required
def shorts_index():
    """短视频分类列表页：点击分类后进入播放页"""
    short_categories = get_all_short_categories()
    # 获取当前用户的短视频分类权限
    uid = session.get('user_id')
    allowed_ids = get_user_allowed_category_ids(uid, 'short') if uid else None
    # 过滤分类列表
    if allowed_ids is not None:
        short_categories = [c for c in short_categories if c['id'] in allowed_ids]
    # 统计每个分类的视频数量
    conn = get_db()
    c = conn.cursor()
    cat_counts = {}
    if allowed_ids is not None and len(allowed_ids) > 0:
        placeholders = ','.join(['?' for _ in allowed_ids])
        c.execute(f'SELECT category_id, COUNT(*) FROM videos WHERE is_short_video = 1 AND category_id IN ({placeholders}) GROUP BY category_id', allowed_ids)
        for row in c.fetchall():
            cat_counts[row[0] or 0] = row[1]
        c.execute(f'SELECT COUNT(*) FROM videos WHERE is_short_video = 1 AND category_id IN ({placeholders})', allowed_ids)
    else:
        c.execute('SELECT category_id, COUNT(*) FROM videos WHERE is_short_video = 1 GROUP BY category_id')
        for row in c.fetchall():
            cat_counts[row[0] or 0] = row[1]
        c.execute('SELECT COUNT(*) FROM videos WHERE is_short_video = 1')
    total_shorts = c.fetchone()[0]
    conn.close()
    return render_template('shorts_index.html',
                         categories=short_categories,
                         cat_counts=cat_counts,
                         total_shorts=total_shorts,
                         active_tab='shorts')

@app.route('/shorts/play')
@app.route('/shorts/play/<int:category_id>')
@login_required
def shorts_play(category_id=0):
    """抖音式短视频播放页：上下滑动切换视频

    category_id: 0=全部, 其它=指定短分类ID

    需求1：开启随机播放时，前端会调用 shuffleFeed，但这里先根据是否
          自动优先未播放（exclude_played_by_default 配置）来加载列表；
          前端开启随机播放后再根据本地逻辑决定是否请求 exclude_played 接口。
    """
    per_page = 500
    short_categories = get_all_short_categories()
    valid_ids = {c['id'] for c in short_categories}
    if category_id != 0 and category_id not in valid_ids:
        return redirect(url_for('shorts_play', category_id=0))

    # 获取当前用户的短视频分类权限
    uid = session.get('user_id')
    allowed_ids = get_user_allowed_category_ids(uid, 'short') if uid else None

    # 权限校验：如果用户有分类限制，且请求的分类不在权限范围内，重定向
    if allowed_ids is not None and category_id != 0 and category_id not in allowed_ids:
        return redirect(url_for('shorts_play', category_id=0))

    # 如果用户有分类限制且请求全部，仅查询权限范围内分类的视频
    if allowed_ids is not None and category_id == 0 and len(allowed_ids) > 0:
        conn = get_db()
        c = conn.cursor()
        placeholders = ','.join(['?' for _ in allowed_ids])
        c.execute(f'SELECT * FROM videos WHERE is_short_video = 1 AND category_id IN ({placeholders}) ORDER BY id DESC LIMIT ?',
                  list(allowed_ids) + [per_page])
        videos = [dict(r) for r in c.fetchall()]
        c.execute(f'SELECT COUNT(*) FROM videos WHERE is_short_video = 1 AND category_id IN ({placeholders})', allowed_ids)
        total = c.fetchone()[0]
        conn.close()
        # 播放状态（按用户维度 + 按权限范围过滤）
        played_status = get_short_played_status(None, user_id=uid, allowed_category_ids=allowed_ids)
    else:
        cat_kwarg = category_id if category_id else None
        result = get_all_videos(page=1, per_page=per_page, is_short_video=True,
                                category_id=cat_kwarg)
        videos = result['videos']
        total = result['total']
        played_status = get_short_played_status(cat_kwarg if cat_kwarg != 0 else None, user_id=uid)
    current_category = None
    for c in short_categories:
        if c['id'] == category_id:
            current_category = c
            break
    return render_template('shorts.html',
                         videos=videos,
                         category_id=category_id,
                         current_category=current_category,
                         categories=short_categories,
                         total=total,
                         played_ids=played_status['played_ids'],
                         played_count=played_status['played_count'],
                         unplayed_count=played_status['unplayed_count'],
                         active_tab='shorts')

@app.route('/admin')
@admin_required
def admin_dashboard():
    stats = get_video_stats()
    album_stats = get_album_stats()
    stats.update(album_stats)
    categories = get_all_categories()
    user_played_stats = get_all_users_short_played_stats()
    return render_template('admin/dashboard.html',
                         stats=stats,
                         categories=categories,
                         user_played_stats=user_played_stats,
                         active_tab='dashboard')

@app.route('/admin/videos')
@admin_required
def admin_videos():
    keyword = request.args.get('keyword', '').strip()
    category_id = request.args.get('category_id', type=int)
    page = request.args.get('page', 1, type=int)
    per_page = 20

    result = get_all_videos(category_id=category_id, keyword=keyword, page=page, per_page=per_page, is_short_video=False)
    videos = result['videos']
    total = result['total']
    total_pages = result['total_pages']

    categories = get_all_categories()
    return render_template('admin/videos.html',
                         videos=videos,
                         categories=categories,
                         keyword=keyword,
                         selected_category=category_id,
                         page=page,
                         total_pages=total_pages,
                         total=total,
                         active_tab='videos')

@app.route('/admin/videos/add', methods=['GET', 'POST'])
@admin_required
def admin_video_add():
    categories = get_all_categories()
    openlist_accounts = get_all_openlist_accounts()
    series_list = get_all_series(per_page=50)['series_list']
    if request.method == 'POST':
        data = {
            'title': request.form.get('title', '').strip(),
            'cover': request.form.get('cover', '').strip(),
            'category_id': request.form.get('category_id', 0, type=int),
            'description': request.form.get('description', '').strip(),
            'video_url': request.form.get('video_url', '').strip(),
            'video_type': request.form.get('video_type', '').strip(),
            'source': request.form.get('source', 'openlist').strip(),
            'sort_order': request.form.get('sort_order', 0, type=int),
            'is_series': request.form.get('is_series', 0, type=int),
            'series_id': request.form.get('series_id', type=int),
            'episode_number': request.form.get('episode_number', 0, type=int),
            'duration': request.form.get('duration', '').strip(),
            'is_short_video': 1 if request.form.get('is_short_video') else 0
        }
        if not data['title'] or not data['video_url']:
            return render_template('admin/video_form.html',
                                 video=data, categories=categories,
                                 openlist_accounts=openlist_accounts,
                                 series_list=series_list,
                                 error='标题和视频链接为必填项',
                                 active_tab='videos')
        video_id = create_video(data)
        return redirect(url_for('admin_videos'))
    return render_template('admin/video_form.html',
                         video={},
                         categories=categories,
                         openlist_accounts=openlist_accounts,
                         series_list=series_list,
                         active_tab='videos')

@app.route('/admin/videos/edit/<int:video_id>', methods=['GET', 'POST'])
@admin_required
def admin_video_edit(video_id):
    video = get_video(video_id)
    if not video:
        abort(404)
    categories = get_all_categories()
    openlist_accounts = get_all_openlist_accounts()
    series_list = get_all_series(per_page=50)['series_list']
    if request.method == 'POST':
        data = {
            'title': request.form.get('title', '').strip(),
            'cover': request.form.get('cover', '').strip(),
            'category_id': request.form.get('category_id', 0, type=int),
            'description': request.form.get('description', '').strip(),
            'video_url': request.form.get('video_url', '').strip(),
            'video_type': request.form.get('video_type', '').strip(),
            'sort_order': request.form.get('sort_order', 0, type=int),
            'is_series': request.form.get('is_series', 0, type=int),
            'series_id': request.form.get('series_id', type=int),
            'episode_number': request.form.get('episode_number', 0, type=int),
            'duration': request.form.get('duration', '').strip(),
            'is_short_video': 1 if request.form.get('is_short_video') else 0
        }
        update_video(video_id, data)
        return redirect(url_for('admin_videos'))
    return render_template('admin/video_form.html',
                         video=video,
                         categories=categories,
                         openlist_accounts=openlist_accounts,
                         series_list=series_list,
                         active_tab='videos')

@app.route('/admin/shorts')
@admin_required
def admin_shorts():
    """短视频管理列表（与视频管理功能相同，仅显示 is_short_video=1 的视频）"""
    keyword = request.args.get('keyword', '').strip()
    category_id = request.args.get('category_id', type=int)
    page = request.args.get('page', 1, type=int)
    per_page = 20

    result = get_all_videos(category_id=category_id, keyword=keyword, page=page, per_page=per_page, is_short_video=True)
    videos = result['videos']
    total = result['total']
    total_pages = result['total_pages']

    categories = get_all_short_categories()
    return render_template('admin/videos.html',
                         videos=videos,
                         categories=categories,
                         keyword=keyword,
                         selected_category=category_id,
                         page=page,
                         total_pages=total_pages,
                         total=total,
                         is_shorts_admin=True,
                         active_tab='shorts_admin')

@app.route('/admin/shorts/add', methods=['GET', 'POST'])
@admin_required
def admin_shorts_add():
    """添加短视频"""
    categories = get_all_short_categories()
    openlist_accounts = get_all_openlist_accounts()
    series_list = get_all_series(per_page=50)['series_list']
    if request.method == 'POST':
        data = {
            'title': request.form.get('title', '').strip(),
            'cover': request.form.get('cover', '').strip(),
            'category_id': request.form.get('category_id', 0, type=int),
            'description': request.form.get('description', '').strip(),
            'video_url': request.form.get('video_url', '').strip(),
            'video_type': request.form.get('video_type', '').strip(),
            'source': request.form.get('source', 'openlist').strip(),
            'sort_order': request.form.get('sort_order', 0, type=int),
            'is_series': request.form.get('is_series', 0, type=int),
            'series_id': request.form.get('series_id', type=int),
            'episode_number': request.form.get('episode_number', 0, type=int),
            'duration': request.form.get('duration', '').strip(),
            'is_short_video': 1
        }
        if not data['title'] or not data['video_url']:
            return render_template('admin/video_form.html',
                                 video=data, categories=categories,
                                 openlist_accounts=openlist_accounts,
                                 series_list=series_list,
                                 is_shorts_admin=True,
                                 error='标题和视频链接为必填项',
                                 active_tab='shorts_admin')
        video_id = create_video(data)
        return redirect(url_for('admin_shorts'))
    return render_template('admin/video_form.html',
                         video={'is_short_video': 1},
                         categories=categories,
                         openlist_accounts=openlist_accounts,
                         series_list=series_list,
                         is_shorts_admin=True,
                         active_tab='shorts_admin')

@app.route('/admin/shorts/edit/<int:video_id>', methods=['GET', 'POST'])
@admin_required
def admin_shorts_edit(video_id):
    """编辑短视频"""
    video = get_video(video_id)
    if not video:
        abort(404)
    categories = get_all_short_categories()
    openlist_accounts = get_all_openlist_accounts()
    series_list = get_all_series(per_page=50)['series_list']
    if request.method == 'POST':
        data = {
            'title': request.form.get('title', '').strip(),
            'cover': request.form.get('cover', '').strip(),
            'category_id': request.form.get('category_id', 0, type=int),
            'description': request.form.get('description', '').strip(),
            'video_url': request.form.get('video_url', '').strip(),
            'video_type': request.form.get('video_type', '').strip(),
            'sort_order': request.form.get('sort_order', 0, type=int),
            'is_series': request.form.get('is_series', 0, type=int),
            'series_id': request.form.get('series_id', type=int),
            'episode_number': request.form.get('episode_number', 0, type=int),
            'duration': request.form.get('duration', '').strip(),
            'is_short_video': 1
        }
        update_video(video_id, data)
        return redirect(url_for('admin_shorts'))
    return render_template('admin/video_form.html',
                         video=video,
                         categories=categories,
                         openlist_accounts=openlist_accounts,
                         series_list=series_list,
                         is_shorts_admin=True,
                         active_tab='shorts_admin')

@app.route('/admin/categories')
@admin_required
def admin_categories():
    categories = get_all_categories()
    # 层级排序：父分类后跟其子分类，按层级顺序排列
    cat_map = {c['id']: c for c in categories}
    children_map = {}
    for c in categories:
        pid = c.get('parent_id', 0)
        if pid not in children_map:
            children_map[pid] = []
        children_map[pid].append(c['id'])

    ordered = []
    visited = set()

    def _walk(cat_id):
        if cat_id in visited:
            return
        visited.add(cat_id)
        ordered.append(cat_map[cat_id])
        # 按 sort_order, id 排序子分类
        kids = sorted(children_map.get(cat_id, []),
                      key=lambda kid_id: (cat_map[kid_id].get('sort_order', 0), cat_map[kid_id].get('id', 0)))
        for kid_id in kids:
            _walk(kid_id)

    # 先排顶级分类，按 sort_order, id
    top_level = sorted([c['id'] for c in categories if c.get('parent_id', 0) == 0],
                       key=lambda tid: (cat_map[tid].get('sort_order', 0), cat_map[tid].get('id', 0)))
    for tid in top_level:
        _walk(tid)

    # 收集未被访问的（如有孤儿节点，parent_id 指向不存在的分类）
    for c in categories:
        if c['id'] not in visited:
            ordered.append(c)
            visited.add(c['id'])

    tree = get_category_tree()
    page = request.args.get('page', 1, type=int)
    per_page = 20
    total = len(ordered)
    total_pages = (total + per_page - 1) // per_page if per_page > 0 else 0
    start = (page - 1) * per_page
    paginated_categories = ordered[start:start + per_page]
    return render_template('admin/categories.html',
                         categories=ordered,
                         paginated_categories=paginated_categories,
                         tree=tree,
                         page=page,
                         total=total,
                         total_pages=total_pages,
                         active_tab='categories')

@app.route('/admin/short_categories')
@admin_required
def admin_short_categories():
    categories = get_all_short_categories()
    cat_map = {c['id']: c for c in categories}
    children_map = {}
    for c in categories:
        pid = c.get('parent_id', 0)
        if pid not in children_map:
            children_map[pid] = []
        children_map[pid].append(c['id'])

    ordered = []
    visited = set()
    def _walk(cat_id):
        if cat_id in visited:
            return
        visited.add(cat_id)
        ordered.append(cat_map[cat_id])
        kids = sorted(children_map.get(cat_id, []),
                      key=lambda kid_id: (cat_map[kid_id].get('sort_order', 0), cat_map[kid_id].get('id', 0)))
        for kid_id in kids:
            _walk(kid_id)
    top_level = sorted([c['id'] for c in categories if c.get('parent_id', 0) == 0],
                       key=lambda tid: (cat_map[tid].get('sort_order', 0), cat_map[tid].get('id', 0)))
    for tid in top_level:
        _walk(tid)
    for c in categories:
        if c['id'] not in visited:
            ordered.append(c)
            visited.add(c['id'])

    tree = get_short_category_tree()
    page = request.args.get('page', 1, type=int)
    per_page = 20
    total = len(ordered)
    total_pages = (total + per_page - 1) // per_page if per_page > 0 else 0
    start = (page - 1) * per_page
    paginated_categories = ordered[start:start + per_page]
    return render_template('admin/short_categories.html',
                         categories=ordered,
                         paginated_categories=paginated_categories,
                         tree=tree,
                         page=page,
                         total=total,
                         total_pages=total_pages,
                         active_tab='short_categories')

@app.route('/admin/series')
@admin_required
def admin_series():
    keyword = request.args.get('keyword', '').strip()
    category_id = request.args.get('category_id', type=int)
    page = request.args.get('page', 1, type=int)
    per_page = 20
    result = get_all_series(category_id=category_id, keyword=keyword, page=page, per_page=per_page)
    series_list = result['series_list']
    categories = get_all_categories()
    return render_template('admin/series.html',
                         series_list=series_list,
                         categories=categories,
                         keyword=keyword,
                         selected_category=category_id,
                         page=page,
                         total=result['total'],
                         total_pages=result['total_pages'],
                         active_tab='series')

@app.route('/admin/series/add', methods=['GET', 'POST'])
@admin_required
def admin_series_add():
    categories = get_all_categories()
    if request.method == 'POST':
        data = {
            'title': request.form.get('title', '').strip(),
            'cover': request.form.get('cover', '').strip(),
            'category_id': request.form.get('category_id', 0, type=int),
            'description': request.form.get('description', '').strip(),
            'total_episodes': request.form.get('total_episodes', 0, type=int)
        }
        series_id = create_series(data)
        return redirect(url_for('admin_series'))
    return render_template('admin/series_form.html',
                         series={},
                         categories=categories,
                         active_tab='series')

@app.route('/admin/openlist')
@admin_required
def admin_openlist():
    accounts = get_all_openlist_accounts()
    categories = get_all_categories()
    short_categories = get_all_short_categories()
    return render_template('admin/openlist.html',
                         accounts=accounts,
                         categories=categories,
                         short_categories=short_categories,
                         active_tab='openlist')

@app.route('/admin/local_import')
@admin_required
def admin_local_import():
    """本地视频导入：浏览运行程序设备本地文件系统，导入本地视频文件。"""
    categories = get_all_categories()
    short_categories = get_all_short_categories()
    return render_template('admin/local_import.html',
                         categories=categories,
                         short_categories=short_categories,
                         active_tab='local_import')

@app.route('/admin/users')
@admin_required
def admin_users():
    users = load_users()
    all_categories = get_all_categories()
    all_short_categories = get_all_short_categories()
    all_album_categories = get_all_album_categories()
    return render_template('admin/users.html',
                         users=users,
                         all_categories=all_categories,
                         all_short_categories=all_short_categories,
                         all_album_categories=all_album_categories,
                         active_tab='users')

@app.route('/admin/favorites')
@admin_required
def admin_favorites():
    page = request.args.get('page', 1, type=int)
    keyword = request.args.get('q', '').strip()
    result = get_all_favorites(page=page, per_page=20, keyword=keyword)
    return render_template('admin/favorites.html',
                         favorites=result['favorites'],
                         page=result['page'],
                         total=result['total'],
                         total_pages=result['total_pages'],
                         keyword=keyword,
                         active_tab='favorites')

# ==================== 数据库管理 ====================

@app.route('/admin/db')
@admin_required
def admin_db_management():
    """数据库管理页面：导出备份 / 导入恢复"""
    db_stats = get_db_stats()
    return render_template('admin/db_management.html',
                         db_stats=db_stats,
                         active_tab='db')

@app.route('/admin/db/export')
@admin_required
def admin_db_export():
    """导出数据库备份：使用 sqlite3 backup API 生成一致性快照后下载"""
    fd, tmp_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        src = sqlite3.connect(Config.DATABASE)
        dst = sqlite3.connect(tmp_path)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return jsonify({'success': False, 'message': '导出数据库失败，请检查 data 目录是否可写'}), 500

    filename = f"videos_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"

    @after_this_request
    def _cleanup_export(response):
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return response

    return send_file(tmp_path, as_attachment=True, download_name=filename)

# 导入恢复时的内容表（与用户无关的业务数据）
DB_CONTENT_TABLES = ['categories', 'short_categories', 'series', 'videos', 'openlist_accounts',
                   'album_categories', 'albums', 'album_images']
# 导入恢复时的用户相关表（选择"不导入用户信息"时保留本机数据）
DB_USER_TABLES = ['users', 'user_category_permissions', 'favorites', 'user_short_played']

def _make_safety_backup():
    """导入前对当前数据库做安全备份，返回备份文件路径（失败返回 None）"""
    try:
        backup_dir = os.path.join(os.path.dirname(Config.DATABASE), 'import_backups')
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(
            backup_dir,
            f"pre_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        )
        src = sqlite3.connect(Config.DATABASE)
        dst = sqlite3.connect(backup_path)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        return backup_path
    except Exception:
        return None

def _validate_backup_db(db_path):
    """校验上传文件是否为本系统的有效 SQLite 备份，返回 (ok, 表名集合, 错误信息)"""
    try:
        with open(db_path, 'rb') as f:
            header = f.read(16)
        if header != b'SQLite format 3\x00':
            return False, set(), '不是有效的 SQLite 数据库文件'
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            tables = {r[0] for r in rows}
        finally:
            conn.close()
        # 导出的备份必然包含这些核心表
        required = {'videos', 'categories', 'users'}
        missing = required - tables
        if missing:
            return False, tables, f'数据库缺少核心表: {", ".join(sorted(missing))}，不是本系统的备份文件'
        return True, tables, ''
    except sqlite3.Error as e:
        return False, set(), f'无法读取数据库文件: {e}'

def _restore_full(tmp_path):
    """完整恢复：用备份数据库整体覆盖当前数据库（含用户信息）"""
    # 先确保当前库结构为最新，再做整体覆盖
    init_db()
    dst = sqlite3.connect(Config.DATABASE)
    src = sqlite3.connect(tmp_path)
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()
    # 覆盖后重新执行迁移，兼容旧版本备份
    init_db()

def _restore_without_users(tmp_path, src_tables):
    """仅恢复内容数据：导入内容表，保留本机用户/权限/收藏/播放标记"""
    init_db()  # 确保本机表结构为最新
    dst_conn = sqlite3.connect(Config.DATABASE)
    src_conn = sqlite3.connect(tmp_path)
    try:
        cur = dst_conn.cursor()
        cur.execute('BEGIN IMMEDIATE')
        imported = {}
        for table in DB_CONTENT_TABLES:
            if table not in src_tables:
                imported[table] = 0
                continue
            # 源表与目标表取列交集，兼容新旧版本字段差异
            src_cols = [r[1] for r in src_conn.execute(f'PRAGMA table_info({table})')]
            dst_cols = [r[1] for r in cur.execute(f'PRAGMA table_info({table})')]
            cols = [c for c in src_cols if c in dst_cols]
            if not cols:
                imported[table] = 0
                continue
            col_list = ','.join(cols)
            rows = src_conn.execute(f'SELECT {col_list} FROM {table}').fetchall()
            cur.execute(f'DELETE FROM {table}')
            if rows:
                placeholders = ','.join(['?'] * len(cols))
                cur.executemany(f'INSERT INTO {table} ({col_list}) VALUES ({placeholders})', rows)
            imported[table] = len(rows)
        dst_conn.commit()
        return imported
    except Exception:
        dst_conn.rollback()
        raise
    finally:
        src_conn.close()
        dst_conn.close()

@app.route('/api/db/import', methods=['POST'])
@admin_required
def api_db_import():
    """导入数据库备份恢复。include_users=1 时同时导入用户信息，否则保留本机用户数据"""
    file = request.files.get('db_file')
    if not file or not file.filename:
        return jsonify({'success': False, 'message': '请选择要导入的数据库备份文件'})
    if not file.filename.lower().endswith('.db'):
        return jsonify({'success': False, 'message': '请选择 .db 格式的数据库备份文件'})

    include_users = request.form.get('include_users') in ('1', 'true', 'on', 'yes')

    # 保存上传文件到临时位置
    fd, tmp_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        file.save(tmp_path)

        ok, src_tables, err = _validate_backup_db(tmp_path)
        if not ok:
            return jsonify({'success': False, 'message': f'备份文件校验失败：{err}'})

        # 导入前先对当前数据库做安全备份
        safety_backup = _make_safety_backup()

        if include_users:
            _restore_full(tmp_path)
            # 用户信息已被覆盖，当前会话可能已失效，强制重新登录
            session.clear()
            msg = '数据库已完整恢复（含用户信息），请使用备份中的账号重新登录'
            if safety_backup:
                msg += f'。导入前的安全备份已保存至: {safety_backup}'
            return jsonify({'success': True, 'message': msg, 'relogin': True})
        else:
            try:
                imported = _restore_without_users(tmp_path, src_tables)
            except Exception as e:
                return jsonify({'success': False,
                                'message': f'导入失败，本机数据未受影响：{e}'}), 500
            detail = '、'.join(f'{t} {n} 条' for t, n in imported.items() if n > 0) or '无数据'
            msg = f'数据库内容已恢复（保留本机用户信息）：{detail}'
            if safety_backup:
                msg += f'。导入前的安全备份已保存至: {safety_backup}'
            return jsonify({'success': True, 'message': msg, 'relogin': False})
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass

# ==================== 跨设备数据库同步（单向推送） ====================

import secrets as _secrets

SYNC_RECEIVE_CONFIG_FILE = os.path.join(os.path.dirname(Config.DATABASE), 'sync_receive_config.json')
SYNC_SEND_CONFIG_FILE = os.path.join(os.path.dirname(Config.DATABASE), 'sync_send_config.json')
SYNC_PUSH_HISTORY_FILE = os.path.join(os.path.dirname(Config.DATABASE), 'sync_push_history.json')

# 推送历史：每字段独立列表，最新在前
PUSH_HISTORY_FIELDS = ('target_url', 'target_api_key', 'url_find', 'url_replace')
PUSH_HISTORY_MAX = 20

# 同步始终覆盖的内容表（视频已在发送端过滤掉本地导入项）
SYNC_CONTENT_TABLES = ['categories', 'short_categories', 'series', 'videos', 'openlist_accounts',
                    'album_categories', 'albums', 'album_images']
# 用户相关表
SYNC_USERS_TABLES = ['users', 'user_category_permissions']
SYNC_FAVORITES_TABLE = 'favorites'
SYNC_PLAYED_TABLE = 'user_short_played'

def _load_json(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return dict(default)

def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _load_sync_receive_config():
    cfg = _load_json(SYNC_RECEIVE_CONFIG_FILE, {})
    return {
        'api_key': cfg.get('api_key', ''),
        'accept_users': bool(cfg.get('accept_users', False)),
        'accept_favorites': bool(cfg.get('accept_favorites', False)),
        'accept_played': bool(cfg.get('accept_played', False)),
    }

def _load_sync_send_config():
    cfg = _load_json(SYNC_SEND_CONFIG_FILE, {})
    return {
        'target_url': cfg.get('target_url', '').strip(),
        'target_api_key': cfg.get('target_api_key', ''),
        'url_find': cfg.get('url_find', ''),
        'url_replace': cfg.get('url_replace', ''),
    }

def _load_push_history():
    hist = _load_json(SYNC_PUSH_HISTORY_FILE, {})
    return {f: [v for v in hist.get(f, []) if isinstance(v, str)]
            for f in PUSH_HISTORY_FIELDS}

def _add_push_history(entry):
    """记录一次推送的输入历史：每字段去重、最新在前、上限 PUSH_HISTORY_MAX 条"""
    hist = _load_push_history()
    for field in PUSH_HISTORY_FIELDS:
        val = (entry.get(field) or '').strip()
        if not val:
            continue
        lst = [v for v in hist.get(field, []) if v != val]
        lst.insert(0, val)
        hist[field] = lst[:PUSH_HISTORY_MAX]
    _save_json(SYNC_PUSH_HISTORY_FILE, hist)

def _copy_table_full(src_conn, cur, table):
    """从源库整表复制到目标库（先删后插，按列交集），返回行数"""
    src_cols = [r[1] for r in src_conn.execute(f'PRAGMA table_info({table})')]
    dst_cols = [r[1] for r in cur.execute(f'PRAGMA table_info({table})')]
    cols = [c for c in src_cols if c in dst_cols]
    cur.execute(f'DELETE FROM {table}')
    if not cols:
        return 0
    col_list = ','.join(cols)
    rows = src_conn.execute(f'SELECT {col_list} FROM {table}').fetchall()
    if rows:
        placeholders = ','.join(['?'] * len(cols))
        cur.executemany(f'INSERT INTO {table} ({col_list}) VALUES ({placeholders})', rows)
    return len(rows)

def _remap_user_table(src_conn, cur, table, src_user_map, dst_user_map, valid_video_ids):
    """按用户名重映射 user_id 复制用户相关数据表（收藏/播放标记）。
    src_user_map: 源库 {user_id: username}；dst_user_map: 目标库 {username: user_id}。
    仅保留 user_id 能映射、且 video_id 在目标库存在的行。"""
    src_cols = [r[1] for r in src_conn.execute(f'PRAGMA table_info({table})')]
    dst_cols = [r[1] for r in cur.execute(f'PRAGMA table_info({table})')]
    cols = [c for c in src_cols if c in dst_cols]
    if 'user_id' not in cols or 'video_id' not in cols:
        return 0
    cur.execute(f'DELETE FROM {table}')
    rows = src_conn.execute(f'SELECT {",".join(cols)} FROM {table}').fetchall()
    uid_idx = cols.index('user_id')
    vid_idx = cols.index('video_id')
    inserted = 0
    batch = []
    for row in rows:
        src_uid = row[uid_idx]
        username = src_user_map.get(src_uid)
        if not username:
            continue
        dst_uid = dst_user_map.get(username)
        if dst_uid is None:
            continue
        vid = row[vid_idx]
        if vid not in valid_video_ids:
            continue
        new_row = list(row)
        new_row[uid_idx] = dst_uid
        batch.append(new_row)
        inserted += 1
    if batch:
        placeholders = ','.join(['?'] * len(cols))
        cur.executemany(
            f'INSERT OR IGNORE INTO {table} ({",".join(cols)}) VALUES ({placeholders})',
            batch
        )
    return inserted

def _apply_sync_snapshot(tmp_path, accept_users, accept_favorites, accept_played):
    """应用同步快照：内容表始终覆盖；用户/收藏/播放标记按接收方开关决定。
    接收端原有的本地导入视频（source='local'）在同步后自动恢复保留。"""
    init_db()  # 确保本机表结构最新
    src_conn = sqlite3.connect(tmp_path)
    src_conn.row_factory = sqlite3.Row
    dst_conn = sqlite3.connect(Config.DATABASE)
    try:
        cur = dst_conn.cursor()
        cur.execute('BEGIN IMMEDIATE')
        result = {'content': 0, 'users': 0, 'permissions': 0,
                  'favorites': 0, 'played': 0, 'local_preserved': 0}

        # 0) 备份接收端已有的本地导入视频（source='local'），同步后用新ID恢复
        local_videos = []
        try:
            local_cols = [r[1] for r in cur.execute('PRAGMA table_info(videos)')]
            local_rows = cur.execute(
                "SELECT * FROM videos WHERE source = 'local'"
            ).fetchall()
            local_videos = [dict(zip(local_cols, row)) for row in local_rows]
        except sqlite3.Error:
            pass

        # 1) 内容表始终覆盖（发送端已过滤掉其本地视频）
        for t in SYNC_CONTENT_TABLES:
            try:
                _copy_table_full(src_conn, cur, t)
            except sqlite3.Error:
                pass

        # 1.5) 恢复接收端的本地导入视频：用新自增ID插入，修正流式播放/封面URL
        old_to_new = {}  # old_id -> new_id
        if local_videos:
            dst_cols = [r[1] for r in cur.execute('PRAGMA table_info(videos)')]
            for lv in local_videos:
                old_id = lv.get('id')
                # 不含id列，让数据库自增分配
                insert_cols = [c for c in dst_cols if c != 'id' and c in lv]
                insert_vals = [lv[c] for c in insert_cols]
                placeholders = ','.join(['?'] * len(insert_cols))
                col_list = ','.join(insert_cols)
                cur.execute(
                    f'INSERT INTO videos ({col_list}) VALUES ({placeholders})',
                    insert_vals
                )
                new_id = cur.lastrowid
                if old_id is not None:
                    old_to_new[old_id] = new_id
                # 修正 /local_video/{old_id} -> /local_video/{new_id}
                url_updates = {}
                old_url = lv.get('video_url') or ''
                if old_url.startswith('/local_video/'):
                    url_updates['video_url'] = f'/local_video/{new_id}'
                old_cover = lv.get('cover') or ''
                if old_cover.startswith('/local_cover/'):
                    url_updates['cover'] = f'/local_cover/{new_id}'
                if url_updates:
                    set_clause = ', '.join(f'{k} = ?' for k in url_updates)
                    cur.execute(
                        f'UPDATE videos SET {set_clause} WHERE id = ?',
                        list(url_updates.values()) + [new_id]
                    )
            result['local_preserved'] = len(local_videos)

        cur.execute('SELECT COUNT(*) FROM videos')
        result['content'] = cur.fetchone()[0]

        # 用于收藏/播放标记的有效 video_id 集合（同步后的目标库）
        valid_video_ids = {r[0] for r in cur.execute('SELECT id FROM videos').fetchall()}

        # 2) 用户信息
        if accept_users:
            for t in SYNC_USERS_TABLES:
                try:
                    n = _copy_table_full(src_conn, cur, t)
                    if t == 'users':
                        result['users'] = n
                    else:
                        result['permissions'] = n
                except sqlite3.Error:
                    pass

        # 构建 user_id 映射（无论是否导入用户，收藏/播放标记都可能需要重映射）
        src_user_map = {}
        for r in src_conn.execute('SELECT id, username FROM users').fetchall():
            src_user_map[r[0]] = r[1]
        dst_user_map = {}
        for r in cur.execute('SELECT id, username FROM users').fetchall():
            dst_user_map[r[0]] = r[1]
        # username -> id
        dst_user_by_name = {v: k for k, v in dst_user_map.items()}

        # 3) 收藏
        if accept_favorites:
            try:
                result['favorites'] = _remap_user_table(
                    src_conn, cur, SYNC_FAVORITES_TABLE,
                    src_user_map, dst_user_by_name, valid_video_ids)
            except sqlite3.Error as e:
                result['favorites_error'] = str(e)
        else:
            # 接收端收藏不被覆盖：修正本地视频ID变化后的引用
            for old_id, new_id in old_to_new.items():
                cur.execute(
                    'UPDATE favorites SET video_id = ? WHERE video_id = ?',
                    (new_id, old_id)
                )

        # 4) 短视频播放标记
        if accept_played:
            try:
                result['played'] = _remap_user_table(
                    src_conn, cur, SYNC_PLAYED_TABLE,
                    src_user_map, dst_user_by_name, valid_video_ids)
            except sqlite3.Error as e:
                result['played_error'] = str(e)
        else:
            # 接收端播放标记不被覆盖：修正本地视频ID变化后的引用
            for old_id, new_id in old_to_new.items():
                cur.execute(
                    'UPDATE user_short_played SET video_id = ? WHERE video_id = ?',
                    (new_id, old_id)
                )

        dst_conn.commit()
        return result
    except Exception:
        dst_conn.rollback()
        raise
    finally:
        src_conn.close()
        dst_conn.close()

@app.route('/api/sync/receive_config', methods=['GET'])
@admin_required
def api_sync_receive_config_get():
    return jsonify({'success': True, 'config': _load_sync_receive_config()})

@app.route('/api/sync/receive_config', methods=['POST'])
@admin_required
def api_sync_receive_config_set():
    data = request.json or {}
    cfg = {
        'api_key': (data.get('api_key') or '').strip(),
        'accept_users': bool(data.get('accept_users', False)),
        'accept_favorites': bool(data.get('accept_favorites', False)),
        'accept_played': bool(data.get('accept_played', False)),
    }
    _save_json(SYNC_RECEIVE_CONFIG_FILE, cfg)
    return jsonify({'success': True, 'message': '同步接收设置已保存'})

@app.route('/api/sync/send_config', methods=['GET'])
@admin_required
def api_sync_send_config_get():
    return jsonify({'success': True, 'config': _load_sync_send_config()})

@app.route('/api/sync/send_config', methods=['POST'])
@admin_required
def api_sync_send_config_set():
    data = request.json or {}
    cfg = {
        'target_url': (data.get('target_url') or '').strip(),
        'target_api_key': data.get('target_api_key', ''),
        'url_find': data.get('url_find', ''),
        'url_replace': data.get('url_replace', ''),
    }
    _save_json(SYNC_SEND_CONFIG_FILE, cfg)
    return jsonify({'success': True, 'message': '推送设置已保存'})

@app.route('/api/sync/gen_key')
@admin_required
def api_sync_gen_key():
    """生成一个随机同步密钥"""
    return jsonify({'success': True, 'key': _secrets.token_urlsafe(24)})

@app.route('/api/sync/push_history', methods=['GET'])
@admin_required
def api_sync_push_history_get():
    """获取推送表单各字段的历史输入记录"""
    return jsonify({'success': True, 'history': _load_push_history()})

@app.route('/api/sync/push_history', methods=['DELETE'])
@admin_required
def api_sync_push_history_clear():
    """清空推送历史（可指定 field 只清空单个字段）"""
    field = (request.args.get('field') or '').strip()
    hist = _load_push_history()
    if field in PUSH_HISTORY_FIELDS:
        hist[field] = []
        msg = f'字段 {field} 的历史记录已清空'
    else:
        hist = {f: [] for f in PUSH_HISTORY_FIELDS}
        msg = '全部推送历史记录已清空'
    _save_json(SYNC_PUSH_HISTORY_FILE, hist)
    return jsonify({'success': True, 'message': msg})

@app.route('/api/sync/receive', methods=['POST'])
def api_sync_receive():
    """接收端：接收并应用来自发送端的同步快照（API 密钥鉴权，非登录态）"""
    rcfg = _load_sync_receive_config()
    key = rcfg['api_key']
    if not key:
        return jsonify({'success': False, 'message': '本机未设置同步接收密钥'}), 403
    if request.headers.get('X-Sync-Key', '') != key:
        return jsonify({'success': False, 'message': '同步密钥不正确'}), 401

    file = request.files.get('db')
    if not file or not file.filename:
        return jsonify({'success': False, 'message': '未收到数据库快照文件'})

    fd, tmp_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        file.save(tmp_path)
        ok, src_tables, err = _validate_backup_db(tmp_path)
        if not ok:
            return jsonify({'success': False, 'message': f'快照校验失败：{err}'})

        safety_backup = _make_safety_backup()
        try:
            result = _apply_sync_snapshot(
                tmp_path, rcfg['accept_users'],
                rcfg['accept_favorites'], rcfg['accept_played'])
        except Exception as e:
            return jsonify({'success': False,
                            'message': f'应用同步失败，本机数据已回滚：{e}'}), 500

        msg = (f"同步完成：内容 {result.get('content', 0)} 条视频"
               f"，用户 {result.get('users', 0)}，权限 {result.get('permissions', 0)}"
               f"，收藏 {result.get('favorites', 0)}，播放标记 {result.get('played', 0)}")
        if not rcfg['accept_users']:
            msg += '（保留本机用户，收藏/播放标记已按用户名重映射）'
        if safety_backup:
            msg += f'。同步前安全备份：{safety_backup}'
        return jsonify({'success': True, 'message': msg, 'result': result})
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass

@app.route('/api/sync/push', methods=['POST'])
@admin_required
def api_sync_push():
    """发送端：准备快照并推送到目标设备。"""
    data = request.json or {}
    target_url = (data.get('target_url') or '').strip()
    target_api_key = (data.get('target_api_key') or '').strip()
    url_find = data.get('url_find', '') or ''
    url_replace = data.get('url_replace', '') or ''

    if not target_url:
        return jsonify({'success': False, 'message': '请填写目标服务器地址'})
    if not target_api_key:
        return jsonify({'success': False, 'message': '请填写目标服务器的同步密钥'})
    if not target_url.startswith(('http://', 'https://')):
        return jsonify({'success': False, 'message': '目标地址需以 http:// 或 https:// 开头'})

    # 持久化本次推送配置 + 记录输入历史（用于下拉选择）
    _save_json(SYNC_SEND_CONFIG_FILE, {
        'target_url': target_url, 'target_api_key': target_api_key,
        'url_find': url_find, 'url_replace': url_replace,
    })
    _add_push_history({
        'target_url': target_url, 'target_api_key': target_api_key,
        'url_find': url_find, 'url_replace': url_replace,
    })

    # 1) 导出本机全库快照到临时文件
    fd, tmp_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        src = sqlite3.connect(Config.DATABASE)
        dst = sqlite3.connect(tmp_path)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()

        # 2) 在快照中过滤本地视频 + 对 openlist 链接做查找替换
        snap = sqlite3.connect(tmp_path)
        snap.row_factory = sqlite3.Row
        try:
            cur = snap.cursor()
            # 删除本地导入的视频（文件在发送端，接收端无法播放）
            cur.execute("DELETE FROM videos WHERE source = 'local'")
            removed_local = cur.rowcount
            # 链接批量替换（video_url 与 cover）
            if url_find:
                cur.execute(
                    "UPDATE videos SET video_url = REPLACE(video_url, ?, ?) "
                    "WHERE video_url IS NOT NULL AND video_url != ''",
                    (url_find, url_replace))
                cur.execute(
                    "UPDATE videos SET cover = REPLACE(cover, ?, ?) "
                    "WHERE cover IS NOT NULL AND cover != ''",
                    (url_find, url_replace))
            snap.commit()
        finally:
            snap.close()

        # 3) 上传到目标设备的 /api/sync/receive
        target = target_url.rstrip('/') + '/api/sync/receive'
        with open(tmp_path, 'rb') as f:
            resp = requests.post(
                target,
                files={'db': ('sync_snapshot.db', f, 'application/octet-stream')},
                headers={'X-Sync-Key': target_api_key},
                timeout=300,
            )
        try:
            remote = resp.json()
        except ValueError:
            remote = {'success': False, 'message': f'目标返回非JSON（HTTP {resp.status_code}）'}
        remote['_http_status'] = resp.status_code
        remote['_removed_local'] = removed_local
        return jsonify(remote)
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'message': f'无法连接目标服务器：{target_url}，请检查地址和网络/防火墙'})
    except requests.exceptions.Timeout:
        return jsonify({'success': False, 'message': '推送超时（数据量较大或网络较慢），请稍后重试'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'推送失败：{e}'}), 500
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass

@app.route('/api/videos', methods=['GET'])
@api_login_required
def api_get_videos():
    keyword = request.args.get('keyword', '').strip()
    category_id = request.args.get('category_id', type=int)
    is_series = request.args.get('is_series', type=int)
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    result = get_all_videos(category_id=category_id, keyword=keyword, is_series=is_series, page=page, per_page=per_page)
    return jsonify({'success': True, 'videos': result['videos'], 'total': result['total'], 'page': result['page'], 'total_pages': result['total_pages']})

@app.route('/api/videos/<int:video_id>', methods=['GET'])
@api_login_required
def api_get_video(video_id):
    video = get_video(video_id)
    if not video:
        return jsonify({'success': False, 'message': '视频不存在'}), 404
    return jsonify({'success': True, 'video': video})

@app.route('/api/videos', methods=['POST'])
@admin_required
def api_create_video():
    data = request.json
    video_id = create_video(data)
    return jsonify({'success': True, 'id': video_id})

@app.route('/api/videos/<int:video_id>', methods=['PUT'])
@admin_required
def api_update_video(video_id):
    data = request.json
    update_video(video_id, data)
    return jsonify({'success': True})

@app.route('/api/videos/<int:video_id>', methods=['DELETE'])
@admin_required
def api_delete_video(video_id):
    delete_video(video_id)
    return jsonify({'success': True})


@app.route('/api/videos/<int:video_id>/view', methods=['POST'])
def api_incr_view(video_id):
    video = get_video(video_id)
    if not video:
        return jsonify({'success': False, 'message': '视频不存在'}), 404
    increment_views(video_id)
    new_views = (video.get('views', 0) or 0) + 1
    # 需求1：短视频播放时同时标记为已播放（按用户维度）
    extra = {}
    if video.get('is_short_video'):
        uid = _get_current_user_id()
        marked, reset, played_cnt, total_cnt = mark_short_played(video_id, user_id=uid)
        extra['played'] = {
            'marked': marked,
            'reset': reset,
            'played_count': played_cnt,
            'total_count': total_cnt,
        }
    return jsonify({'success': True, 'views': new_views, **extra})

@app.route('/api/videos/batch_delete', methods=['POST'])
@admin_required
def api_batch_delete_videos():
    data = request.json
    video_ids = data.get('video_ids', [])
    if not video_ids:
        return jsonify({'success': False, 'message': '请选择要删除的视频'}), 400
    count = batch_delete_videos(video_ids)
    return jsonify({'success': True, 'deleted_count': count})

@app.route('/api/videos/batch_delete_all', methods=['POST'])
@admin_required
def api_batch_delete_all_videos():
    data = request.json or {}
    is_shorts = data.get('is_short_video', False)
    msg = '全部短视频' if is_shorts else '全部视频'
    count = batch_delete_all_videos(is_short_video=is_shorts)
    return jsonify({'success': True, 'deleted_count': count, 'message': f'已删除{msg}'})

@app.route('/api/series/batch_delete', methods=['POST'])
@admin_required
def api_batch_delete_series():
    data = request.json
    series_ids = data.get('series_ids', [])
    if not series_ids:
        return jsonify({'success': False, 'message': '请选择要删除的系列'}), 400
    count = batch_delete_series(series_ids)
    return jsonify({'success': True, 'deleted_count': count})

@app.route('/api/series/batch_delete_all', methods=['POST'])
@admin_required
def api_batch_delete_all_series():
    count = batch_delete_all_series()
    return jsonify({'success': True, 'deleted_count': count, 'message': '已删除全部系列'})

@app.route('/api/categories/batch_delete', methods=['POST'])
@admin_required
def api_batch_delete_categories():
    data = request.json
    category_ids = data.get('category_ids', [])
    if not category_ids:
        return jsonify({'success': False, 'message': '请选择要删除的分类'}), 400
    count = batch_delete_categories(category_ids)
    return jsonify({'success': True, 'deleted_count': count})

@app.route('/api/categories/batch_delete_all', methods=['POST'])
@admin_required
def api_batch_delete_all_categories():
    count = batch_delete_all_categories()
    return jsonify({'success': True, 'deleted_count': count, 'message': '已删除全部分类'})

@app.route('/api/categories', methods=['GET'])
@api_login_required
def api_get_categories():
    categories = get_all_categories()
    return jsonify({'success': True, 'categories': categories})

@app.route('/api/categories', methods=['POST'])
@admin_required
def api_create_category():
    data = request.json
    success, cat_id = create_category(data.get('name'), data.get('parent_id', 0), data.get('sort_order', 0))
    if success:
        return jsonify({'success': True, 'id': cat_id})
    return jsonify({'success': False, 'message': '创建失败，分类名可能已存在'}), 400

@app.route('/api/categories/<int:category_id>', methods=['DELETE'])
@admin_required
def api_delete_category(category_id):
    delete_category(category_id)
    return jsonify({'success': True})

@app.route('/api/short_categories/batch_delete', methods=['POST'])
@admin_required
def api_batch_delete_short_categories():
    data = request.json
    category_ids = data.get('category_ids', [])
    if not category_ids:
        return jsonify({'success': False, 'message': '请选择要删除的分类'}), 400
    count = batch_delete_short_categories(category_ids)
    return jsonify({'success': True, 'deleted_count': count})

@app.route('/api/short_categories/batch_delete_all', methods=['POST'])
@admin_required
def api_batch_delete_all_short_categories():
    count = batch_delete_all_short_categories()
    return jsonify({'success': True, 'deleted_count': count, 'message': '已删除全部短·分类'})

@app.route('/api/short_categories', methods=['GET'])
@api_login_required
def api_get_short_categories():
    categories = get_all_short_categories()
    return jsonify({'success': True, 'categories': categories})

@app.route('/api/short_categories', methods=['POST'])
@admin_required
def api_create_short_category():
    data = request.json
    success, cat_id = create_short_category(data.get('name'), data.get('parent_id', 0), data.get('sort_order', 0))
    if success:
        return jsonify({'success': True, 'id': cat_id})
    return jsonify({'success': False, 'message': '创建失败，分类名可能已存在'}), 400

@app.route('/api/short_categories/<int:category_id>', methods=['DELETE'])
@admin_required
def api_delete_short_category(category_id):
    delete_short_category(category_id)
    return jsonify({'success': True})

@app.route('/api/series', methods=['GET'])
@api_login_required
def api_get_series():
    keyword = request.args.get('keyword', '').strip()
    category_id = request.args.get('category_id', type=int)
    series_list = get_all_series(category_id=category_id, keyword=keyword, per_page=50)['series_list']
    return jsonify({'success': True, 'series': series_list})

@app.route('/api/series/<int:series_id>/episodes', methods=['GET'])
@api_login_required
def api_get_series_episodes(series_id):
    episodes = get_episodes_by_series(series_id)
    return jsonify({'success': True, 'episodes': episodes})

@app.route('/api/series', methods=['POST'])
@admin_required
def api_create_series():
    data = request.json
    series_id = create_series(data)
    return jsonify({'success': True, 'id': series_id})

@app.route('/api/series/<int:series_id>', methods=['DELETE'])
@admin_required
def api_delete_series(series_id):
    delete_series(series_id)
    return jsonify({'success': True})

@app.route('/api/openlist/accounts', methods=['GET'])
@api_login_required
def api_get_openlist_accounts():
    accounts = get_all_openlist_accounts()
    return jsonify({'success': True, 'accounts': accounts})

@app.route('/api/openlist/accounts', methods=['POST'])
@admin_required
def api_create_openlist_account():
    data = request.json
    account_id = create_openlist_account(data)
    return jsonify({'success': True, 'id': account_id})

@app.route('/api/openlist/accounts/<int:account_id>', methods=['DELETE'])
@admin_required
def api_delete_openlist_account(account_id):
    delete_openlist_account(account_id)
    return jsonify({'success': True})

@app.route('/api/openlist/test', methods=['POST'])
@api_login_required
def api_test_openlist():
    data = request.json
    try:
        api = OpenListApi(data['server_url'], data['username'], data['password'])
        token = api.login()
        return jsonify({'success': True, 'token': token})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/openlist/files', methods=['POST'])
@api_login_required
def api_get_openlist_files():
    data = request.json
    account = data.get('account')
    path = data.get('path', '/')
    
    api = OpenListApi(account['server_url'], account['username'], account['password'])
    try:
        if not account.get('token'):
            api.login()
        files = api.get_file_list(path)
        result_files = []
        for f in files:
            if not f.get('is_dir'):
                full_path = (path.rstrip('/') if path != '/' else '') + '/' + f.get('name', '')
                f['full_path'] = full_path
                f['direct_url'] = api.get_file_link(full_path)
            result_files.append(f)
        return jsonify({'success': True, 'files': result_files})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/openlist/direct_link', methods=['POST'])
@api_login_required
def api_get_openlist_direct_link():
    data = request.json
    account = data.get('account')
    file_path = data.get('path', '')
    
    api = OpenListApi(account['server_url'], account['username'], account['password'])
    try:
        if not account.get('token'):
            api.login()
        direct_url = api.get_file_link(file_path)
        return jsonify({'success': True, 'url': direct_url})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/openlist/nfo_content', methods=['POST'])
@api_login_required
def api_get_nfo_content():
    data = request.json
    account = data.get('account')
    file_path = data.get('path', '')
    
    api = OpenListApi(account['server_url'], account['username'], account['password'])
    try:
        if not account.get('token'):
            api.login()
        
        direct_url = api.get_file_link(file_path)
        
        # 下载 NFO 文件内容
        headers = {"Authorization": f"Bearer {account.get('token', '')}"}
        resp = requests.get(direct_url, headers=headers, timeout=10)
        resp.raise_for_status()
        
        content = resp.text
        nfo_data = parse_nfo_content(content)
        
        return jsonify({'success': True, 'data': nfo_data, 'url': direct_url})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/openlist/batch_import', methods=['POST'])
@admin_required
def api_batch_import():
    data = request.json
    account = data.get('account')
    path = data.get('path', '/')
    category_id = data.get('category_id', 0)
    auto_create_series = data.get('auto_create_series', False)
    series_name = data.get('series_name', '')
    cover_url = data.get('cover_url', '')
    use_nfo = data.get('use_nfo', True)
    is_short_video = int(data.get('is_short_video', 0) or 0)
    
    api = OpenListApi(account['server_url'], account['username'], account['password'])
    try:
        if not account.get('token'):
            api.login()
        
        all_files = api.get_all_files_flat(path)
        
        # 分离视频文件
        video_extensions = ['mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv', 'webm', 'm4v', '3gp', 'mpg', 'mpeg', 'ts', 'iso', 'rmvb', 'rm', 'dat', 'vob']
        
        videos = []
        for f in all_files:
            ext = f.get('name', '').rsplit('.', 1)[-1].lower() if '.' in f.get('name', '') else ''
            if ext in video_extensions:
                videos.append(f)

        # 初始化导入进度（前端轮询显示）
        _set_import_progress(total=len(videos), current=0, done=False, task='batch_import')
        
        imported = []
        nfo_used = 0
        series_id = None
        
        # 只有当auto_create_series为True且有series_name时才创建系列
        if auto_create_series and series_name:
            existing_series = get_all_series(per_page=500)['series_list']
            for s in existing_series:
                if s['title'] == series_name:
                    series_id = s['id']
                    break
            
            if not series_id:
                # 检查是否有可用的 NFO 作为系列封面
                series_cover = cover_url
                series_nfo = None
                # 从目录根查找 movie.nfo / tvshow.nfo 作为系列封面来源
                try:
                    root_files = api.get_file_list(path) or []
                    for nfo in root_files:
                        nfo_name = nfo.get('name', '').lower()
                        if nfo_name.endswith('.nfo') and nfo_name in ('movie.nfo', 'tvshow.nfo', 'serie.nfo'):
                            nfo_full_path = (nfo.get('path') or path).rstrip('/') + '/' + nfo.get('name', '')
                            nfo_direct_url = api.get_file_link(nfo_full_path)
                            headers = {"Authorization": f"Bearer {api.token}"}
                            resp = requests.get(nfo_direct_url, headers=headers, timeout=5)
                            if resp.status_code == 200:
                                nfo_data = parse_nfo_content(resp.text)
                                if nfo_data.get('poster'):
                                    series_cover = _resolve_nfo_cover(nfo_data['poster'], path, api)
                                elif nfo_data.get('thumbs'):
                                    series_cover = _resolve_nfo_cover(nfo_data['thumbs'][0], path, api)
                                if nfo_data.get('title') and not series_name:
                                    series_name = nfo_data['title']
                            break
                except:
                    pass
                
                series_id = create_series({
                    'title': series_name,
                    'cover': series_cover,
                    'category_id': category_id,
                    'total_episodes': len(videos)
                })
        
        for idx, video_info in enumerate(videos, 1):
            _set_import_progress(current=idx)
            name = video_info.get('name', '未知视频')
            direct_url = video_info.get('direct_url', '')
            video_type = name.rsplit('.', 1)[-1] if '.' in name else ''

            # 去重：如果 video_url 已存在则跳过
            if direct_url and get_video_by_url(direct_url):
                continue

            # 标题优先级：NFO标题 > 目录名（仅创建系列时） > 原文件名
            # 仅在真正创建合集时使用目录名作为视频标题；不创建合集时使用原文件名
            if series_id:
                if len(videos) > 1:
                    base_title = f"{series_name} 第{idx}集"
                else:
                    base_title = series_name
            else:
                base_title = name

            video_data = {
                'title': base_title,
                'video_url': direct_url,
                'cover': cover_url,
                'category_id': category_id,
                'source': 'openlist',
                'video_type': video_type,
                'is_short_video': is_short_video
            }
            
            # 尝试查找对应的 NFO 文件（复用已验证的 _fetch_nfo_for_video）
            video_full_path = video_info.get('full_path', '')
            nfo_cover_set = False
            nfo_dir_files = None
            if use_nfo:
                try:
                    metadata, nfo_dir_files = _fetch_nfo_for_video(
                        account, video_full_path, api, return_dir_files=True)
                    if metadata:
                        # 使用 NFO 信息更新视频数据
                        if metadata.get('title'):
                            video_data['title'] = metadata['title']
                        if metadata.get('description'):
                            video_data['description'] = metadata['description']
                        if metadata.get('cover'):
                            video_data['cover'] = metadata['cover']
                            nfo_cover_set = True
                        if metadata.get('episode_number'):
                            video_data['episode_number'] = metadata['episode_number']
                            if series_id:
                                video_data['is_series'] = 1
                        if metadata.get('genre'):
                            video_data['genre'] = metadata['genre']
                        if metadata.get('rating'):
                            video_data['rating'] = metadata['rating']
                        if metadata.get('year'):
                            video_data['year'] = metadata['year']
                        if metadata.get('actors'):
                            actors_list = metadata['actors']
                            if isinstance(actors_list, list):
                                video_data['actors'] = ', '.join([a.get('name', '') for a in actors_list if a.get('name')])
                            else:
                                video_data['actors'] = str(actors_list)

                        nfo_used += 1
                except Exception:
                    nfo_dir_files = None

            # 封面 fallback：NFO封面 > 视频所在目录图片 > 手动选择的cover_url
            # 非末端目录批量导入时，各子目录中的视频优先使用各自目录中的封面图片
            if not nfo_cover_set:
                try:
                    if '/' in video_full_path:
                        dir_path = video_full_path.rsplit('/', 1)[0] or '/'
                        cover_from_dir = _find_openlist_cover_in_dir(
                            api, dir_path, dir_files=nfo_dir_files)
                        if cover_from_dir:
                            video_data['cover'] = cover_from_dir
                except Exception:
                    pass

            if series_id:
                video_data['series_id'] = series_id
                if not video_data.get('episode_number'):
                    video_data['episode_number'] = idx
                video_data['is_series'] = 1
            
            create_video(video_data)
            imported.append({
                'name': video_data.get('title', name),
                'url': direct_url,
                'nfo_used': nfo_used > 0
            })
        
        if series_id and len(videos) > 0:
            import_series = get_series(series_id)
            if import_series:
                update_series(series_id, {'total_episodes': len(videos)})
        
        return jsonify({
            'success': True,
            'imported_count': len(imported),
            'imported': imported[:20],
            'series_name': series_name if series_id else None,
            'nfo_used': nfo_used,
            'nfo_files_found': nfo_used
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        _set_import_progress(done=True)

@app.route('/api/openlist/import_progress')
@admin_required
def api_import_progress():
    """查询当前导入进度（total 总数 / current 已处理数）"""
    return jsonify({'success': True, 'total': _import_progress['total'],
                    'current': _import_progress['current'],
                    'done': _import_progress['done']})

@app.route('/api/openlist/single_import', methods=['POST'])
@admin_required
def api_single_import():
    data = request.json
    account = data.get('account')
    file_path = data.get('file_path', '')
    file_name = data.get('file_name', '')
    category_id = data.get('category_id', 0)
    cover_url = data.get('cover_url', '')
    is_short_video = int(data.get('is_short_video', 0) or 0)

    api = OpenListApi(account['server_url'], account['username'], account['password'])
    try:
        if not account.get('token'):
            api.login()

        direct_url = api.get_file_link(file_path)
        video_type = file_name.rsplit('.', 1)[-1] if '.' in file_name else ''

        # 去重：如果 video_url 已存在则返回提示
        if direct_url and get_video_by_url(direct_url):
            return jsonify({'success': False, 'message': '该视频已导入，请勿重复导入'}), 400

        # 默认使用文件名作为标题
        video_data = {
            'title': file_name,
            'video_url': direct_url,
            'cover': cover_url,
            'category_id': category_id,
            'source': 'openlist',
            'video_type': video_type,
            'is_short_video': is_short_video
        }

        nfo_used = False
        # 尝试在视频所在目录查找 NFO 文件，自动获取标题与元数据
        try:
            metadata = _fetch_nfo_for_video(account, file_path, api)
            if metadata:
                # NFO 标题优先于文件名
                if metadata.get('title'):
                    video_data['title'] = metadata['title']
                if metadata.get('description'):
                    video_data['description'] = metadata['description']
                # NFO 封面优先，除非用户已显式指定封面
                if metadata.get('cover'):
                    video_data['cover'] = metadata['cover']
                if metadata.get('genre'):
                    video_data['genre'] = metadata['genre']
                if metadata.get('rating'):
                    video_data['rating'] = metadata['rating']
                if metadata.get('year'):
                    video_data['year'] = metadata['year']
                if metadata.get('actors'):
                    actors_list = metadata['actors']
                    if isinstance(actors_list, list):
                        video_data['actors'] = ', '.join([a.get('name', '') for a in actors_list if a.get('name')])
                    else:
                        video_data['actors'] = str(actors_list)
                nfo_used = True
        except Exception:
            pass

        create_video(video_data)

        return jsonify({
            'success': True,
            'video_name': video_data.get('title', file_name),
            'video_url': direct_url,
            'nfo_used': nfo_used
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/openlist/multi_import', methods=['POST'])
@admin_required
def api_multi_import():
    """多视频文件导入：支持一次性导入用户在 OpenList 文件列表中选中的多个视频。
    每个视频使用原文件名作为标题（若存在 NFO 则用 NFO 标题），不创建系列。
    """
    data = request.json
    account = data.get('account')
    files = data.get('files', []) or []
    category_id = data.get('category_id', 0)
    cover_url = data.get('cover_url', '')
    is_short_video = int(data.get('is_short_video', 0) or 0)

    if not files:
        return jsonify({'success': False, 'message': '未选择任何视频文件'}), 400

    api = OpenListApi(account['server_url'], account['username'], account['password'])
    try:
        if not account.get('token'):
            api.login()

        imported = []
        skipped = []
        failed = []
        nfo_used = 0

        # 初始化导入进度（前端轮询显示）
        _set_import_progress(total=len(files), current=0, done=False, task='multi_import')

        for f_idx, f in enumerate(files, 1):
            _set_import_progress(current=f_idx)
            file_path = f.get('file_path', '')
            file_name = f.get('file_name', '')
            if not file_path or not file_name:
                failed.append({'name': file_name or file_path, 'error': '路径或文件名缺失'})
                continue

            try:
                direct_url = api.get_file_link(file_path)
            except Exception as e:
                failed.append({'name': file_name, 'error': f'获取直链失败: {e}'})
                continue

            # 去重：video_url 已存在则跳过
            if direct_url and get_video_by_url(direct_url):
                skipped.append({'name': file_name, 'reason': '已存在'})
                continue

            video_type = file_name.rsplit('.', 1)[-1] if '.' in file_name else ''

            # 默认使用原文件名作为标题（与单个视频导入一致）
            video_data = {
                'title': file_name,
                'video_url': direct_url,
                'cover': cover_url,
                'category_id': category_id,
                'source': 'openlist',
                'video_type': video_type,
                'is_short_video': is_short_video
            }

            # 尝试在视频所在目录查找 NFO 文件，自动获取标题与元数据
            file_nfo_used = False
            try:
                metadata = _fetch_nfo_for_video(account, file_path, api)
                if metadata:
                    if metadata.get('title'):
                        video_data['title'] = metadata['title']
                    if metadata.get('description'):
                        video_data['description'] = metadata['description']
                    # NFO 封面优先，除非用户已显式指定封面
                    if metadata.get('cover'):
                        video_data['cover'] = metadata['cover']
                    if metadata.get('genre'):
                        video_data['genre'] = metadata['genre']
                    if metadata.get('rating'):
                        video_data['rating'] = metadata['rating']
                    if metadata.get('year'):
                        video_data['year'] = metadata['year']
                    if metadata.get('actors'):
                        actors_list = metadata['actors']
                        if isinstance(actors_list, list):
                            video_data['actors'] = ', '.join([a.get('name', '') for a in actors_list if a.get('name')])
                        else:
                            video_data['actors'] = str(actors_list)
                    file_nfo_used = True
                    nfo_used += 1
            except Exception:
                pass

            try:
                create_video(video_data)
                imported.append({
                    'name': video_data.get('title', file_name),
                    'nfo_used': file_nfo_used
                })
            except Exception as e:
                failed.append({'name': file_name, 'error': str(e)})

        return jsonify({
            'success': True,
            'imported_count': len(imported),
            'skipped_count': len(skipped),
            'failed_count': len(failed),
            'imported': imported[:20],
            'nfo_used': nfo_used
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        _set_import_progress(done=True)

@app.route('/api/stats', methods=['GET'])
@api_login_required
def api_get_stats():
    stats = get_video_stats()
    return jsonify({'success': True, 'stats': stats})

@app.route('/api/search', methods=['GET'])
@api_login_required
def api_search():
    keyword = request.args.get('keyword', '').strip()
    video_result = get_all_videos(keyword=keyword, per_page=50)
    video_results = video_result['videos']
    series_results = get_all_series(keyword=keyword, per_page=50)['series_list']
    return jsonify({'success': True, 'videos': video_results, 'series': series_results})

@app.route('/api/users', methods=['POST'])
@admin_required
def api_create_user():
    data = request.json
    success = create_user(data['username'], data['password'], data.get('role', 'user'))
    if success:
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': '用户名已存在'}), 400

@app.route('/api/users/<int:user_id>', methods=['DELETE'])
@admin_required
def api_delete_user(user_id):
    if user_id == session.get('user_id'):
        return jsonify({'success': False, 'message': '不能删除当前登录用户'}), 400
    delete_user(user_id)
    return jsonify({'success': True})

@app.route('/api/users/<int:user_id>/password', methods=['PUT'])
@admin_required
def api_update_password(user_id):
    data = request.json
    new_password = data.get('password', '').strip()
    if not new_password:
        return jsonify({'success': False, 'message': '密码不能为空'}), 400
    if len(new_password) < 6:
        return jsonify({'success': False, 'message': '密码长度不能少于6位'}), 400
    update_password(user_id, new_password)
    return jsonify({'success': True})

# ===== 需求1：用户分类权限 API =====

@app.route('/api/users/<int:user_id>/permissions', methods=['GET'])
@admin_required
def api_get_user_permissions(user_id):
    perms = get_user_permissions(user_id)
    return jsonify({'success': True, 'permissions': perms})

@app.route('/api/users/<int:user_id>/permissions', methods=['PUT'])
@admin_required
def api_set_user_permissions(user_id):
    data = request.json
    normal_ids = data.get('normal_category_ids', [])
    short_ids = data.get('short_category_ids', [])
    album_ids = data.get('album_category_ids', [])
    set_user_permissions(user_id, normal_ids, 'normal')
    set_user_permissions(user_id, short_ids, 'short')
    set_user_permissions(user_id, album_ids, 'album')
    # 合集权限开关：未传 = 保持默认 True（向后兼容）
    if 'can_access_series' in data:
        set_user_series_access(user_id, bool(data.get('can_access_series')))
    return jsonify({'success': True})

# ===== 需求2：收藏 API =====

@app.route('/api/favorites/<int:video_id>', methods=['POST'])
@api_login_required
def api_toggle_favorite(video_id):
    uid = session.get('user_id')
    if not uid:
        return jsonify({'success': False, 'message': '未登录'}), 401
    action = request.args.get('action', 'toggle')
    if action == 'check':
        return jsonify({'success': True, 'favorited': is_favorited(uid, video_id)})
    if is_favorited(uid, video_id):
        remove_favorite(uid, video_id)
        return jsonify({'success': True, 'favorited': False})
    else:
        add_favorite(uid, video_id)
        return jsonify({'success': True, 'favorited': True})

@app.route('/api/favorites', methods=['GET'])
@api_login_required
def api_get_favorites():
    uid = session.get('user_id')
    if not uid:
        return jsonify({'success': False, 'message': '未登录'}), 401
    fav_ids = get_user_favorite_ids(uid)
    return jsonify({'success': True, 'favorite_ids': fav_ids})

@app.route('/api/favorites/<int:favorite_id>', methods=['DELETE'])
@admin_required
def api_delete_favorite(favorite_id):
    delete_favorite(favorite_id)
    return jsonify({'success': True})

@app.route('/api/favorites/batch_delete', methods=['POST'])
@admin_required
def api_batch_delete_favorites():
    data = request.json
    ids = data.get('favorite_ids', [])
    if not ids:
        return jsonify({'success': False, 'message': '未选择项'}), 400
    count = batch_delete_favorites(ids)
    return jsonify({'success': True, 'deleted_count': count})

@app.route('/api/favorites/batch_delete_all', methods=['POST'])
@admin_required
def api_batch_delete_all_favorites():
    count = batch_delete_all_favorites()
    return jsonify({'success': True, 'deleted_count': count, 'message': '已删除全部收藏'})


def _extract_path_from_video_url(video_url):
    """从 OpenList 直链 URL 中提取文件路径。
    直链格式: {server_url}/d/{url_encoded_path}
    返回: (server_url, file_path) 或 (None, None)
    """
    if not video_url:
        return None, None
    try:
        parsed = urlparse(video_url)
        server_url = f"{parsed.scheme}://{parsed.netloc}"
        # 路径部分: /d/xxx/yyy -> /xxx/yyy
        raw_path = parsed.path
        if raw_path.startswith('/d/'):
            encoded_path = raw_path[3:]  # 去掉 '/d/' 前缀
        elif raw_path.startswith('/d'):
            encoded_path = raw_path[2:]
        else:
            return None, None
        file_path = unquote(encoded_path)
        if not file_path.startswith('/'):
            file_path = '/' + file_path
        return server_url, file_path
    except Exception:
        return None, None


# 视频导入进度（供前端轮询显示 "10/100"）
_import_progress = {'total': 0, 'current': 0, 'done': True, 'task': ''}


def _set_import_progress(total=None, current=None, done=None, task=None):
    """更新导入进度（线程不敏感的单管理员场景，简单全局 dict 即可）。"""
    if total is not None:
        _import_progress['total'] = total
    if current is not None:
        _import_progress['current'] = current
    if done is not None:
        _import_progress['done'] = done
    if task is not None:
        _import_progress['task'] = task


_OPENLIST_IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')
_OPENLIST_VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.m3u8', '.flv', '.wmv', '.ts', '.m4v', '.rmvb', '.vob', '.asf'}


# ---------- 图片导入：typecho_web 风格的辅助函数 ----------
@app.template_filter('source_label')
def source_label(value):
    """统一图集/视频来源的展示文案，防止列表与详情页显示不一致。

    source 值域：openlist(OpenList远端) / local(本地磁盘) / url·urls(手工或未知URL)。
    """
    mapping = {
        'openlist': 'OpenList',
        'local': '本地',
        'url': 'URL',
        'urls': 'URL',
        '': '未知',
    }
    return mapping.get(value, value or '未知')


def _build_pv_stats(num_images, num_videos):
    """构造 typecho_web 风格的统计信息行，如 [12P3V] / [5P] / [3V] / 空字符串。"""
    img = int(num_images or 0)
    vid = int(num_videos or 0)
    if img > 0 and vid > 0:
        return f'{img}P{vid}V'
    if img > 0:
        return f'{img}P'
    if vid > 0:
        return f'{vid}V'
    return ''


def _append_pv_stats_to_description(existing, num_images, num_videos):
    """把 [NP MV] 统计信息写入图集描述（如已有则追加）。"""
    stats = _build_pv_stats(num_images, num_videos)
    if not stats:
        return existing
    stats_line = f'统计信息:        [{stats}]'
    base = (existing or '').strip()
    if not base:
        return stats_line
    # 如果已经有一行统计信息，覆盖之
    lines = base.splitlines()
    if lines and lines[0].startswith('统计信息:'):
        lines[0] = stats_line
        return '\n'.join(lines)
    return stats_line + '\n' + base


def _classify_url(url):
    """根据 URL 扩展名判断是图片、视频还是其他。

    本地图集预览 URL（/api/local_import/preview?path=D:\\xxx\\001.jpg&name=001.jpg）
    的 path 部分没有扩展名，因此当 path 无扩展名时回退从 query 的 name= / path= 取扩展名。
    """
    try:
        parsed = urlparse(url)
        path = unquote(parsed.path)
        ext = os.path.splitext(path)[1].lower()
        if not ext and parsed.query:
            from urllib.parse import parse_qs
            qs = parse_qs(parsed.query)
            for key in ('name', 'path'):
                if key in qs and qs[key]:
                    ext = os.path.splitext(qs[key][0])[1].lower()
                    if ext:
                        break
    except Exception:
        return None, None, None
    is_image = ext in _LOCAL_IMAGE_EXTENSIONS
    is_video = ext in _LOCAL_VIDEO_EXTENSIONS
    if is_image:
        return 'image', ext, path
    if is_video:
        return 'video', ext, path
    return None, ext, path


def _parse_url_lines(text):
    """从一段文本中提取 URL 列表（每行一条），过滤空白与注释行。"""
    if not text:
        return []
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        out.append(s)
    return out


def _extract_media_urls(text):
    """从一段文本中提取所有图片/视频 URL，支持多种形式（去重、保序）。

    支持：
    1. HTML 里的 src/href 属性  -> <img src="..."> / <video src="...">
    2. Markdown 链接           -> ![alt](url) / [text](url)
    3. 纯文本 URL，每行一条或混排

    Returns:
        list[str]: 去重后的 URL 列表
    """
    if not text:
        return []
    urls, seen = [], set()

    def push(u):
        u = (u or '').strip()
        if not u:
            return
        u = re.sub(r'[)\].,;:]+$', '', u)
        if not u or u in seen:
            return
        seen.add(u)
        urls.append(u)

    # 1) HTML src/href 属性
    for m in re.finditer(r'(?:src|href)\s*=\s*["\']([^"\']+)["\']', text, re.IGNORECASE):
        push(m.group(1))
    # 2) Markdown 链接
    for m in re.finditer(r'!?\[[^\]]*\]\(\s*(https?://[^)]+)\s*\)', text, re.IGNORECASE):
        push(m.group(1))
    # 3) 纯文本 URL（括号内文件名如 (2).jpg 不被截断）
    for m in re.finditer(r'https?://[^\s"\'<>]+', text, re.IGNORECASE):
        push(m.group(0))
    return urls


def _find_openlist_cover_in_dir(api, dir_path, dir_files=None):
    """在 OpenList 指定目录按优先级查找封面图片文件，返回直链URL或空字符串。

    优先级：
    1. 目录中只有一张图片 → 使用它
    2. 文件名含 "poster" → 使用它
    3. 首张图片 → 使用它

    Args:
        api: OpenListApi 实例
        dir_path: 远程目录路径
        dir_files: 可选，已获取的目录文件列表（避免重复请求）

    Returns:
        str: 图片直链URL，或空字符串
    """
    if not dir_path:
        return ''
    if dir_files is None:
        try:
            dir_files = api.get_file_list(dir_path) or []
        except Exception:
            return ''

    image_files = [
        f for f in dir_files
        if not f.get('is_dir')
        and os.path.splitext(f.get('name', ''))[1].lower() in _OPENLIST_IMAGE_EXTENSIONS
    ]

    if not image_files:
        return ''

    image_files.sort(key=lambda f: f.get('name', '').lower())

    # 优先级1：目录中只有一张图片
    if len(image_files) == 1:
        chosen = image_files[0]
    # 优先级2：文件名含"poster"
    elif any('poster' in f.get('name', '').lower() for f in image_files):
        chosen = next(f for f in image_files if 'poster' in f.get('name', '').lower())
    # 优先级3：首张图片
    else:
        chosen = image_files[0]

    full_path = (chosen.get('path') or dir_path).rstrip('/') + '/' + chosen.get('name', '')
    try:
        return api.get_file_link(full_path)
    except Exception:
        return ''


def _resolve_nfo_cover(poster, dir_path, api):
    """将 NFO 中的封面地址转换为可访问的完整 URL。

    NFO 中 <poster>/<thumb> 常为纯文件名（封面图片与视频同目录），
    直接存文件名前端无法显示。此处：
    - 已是 http(s):// 完整地址或本地路径（/ 开头）→ 原样返回
    - 纯文件名 → 拼接视频所在目录的 OpenList 直链（get_file_link 自带 URL 编码）
    """
    if not poster:
        return poster
    p = poster.strip()
    if not p:
        return poster
    if p.startswith(('http://', 'https://', '/', 'data:')):
        return p
    # 纯文件名 → 视频所在目录 + 文件名 的 OpenList 直链
    return api.get_file_link(dir_path.rstrip('/') + '/' + p)


def _fetch_nfo_for_video(account, file_path, api, return_dir_files=False):
    """从视频所在目录查找并解析 NFO，返回 metadata dict（可能为空）。

    return_dir_files=True 时返回 (metadata, dir_files)，供封面 fallback
    复用已获取的目录文件列表，避免重复调用远程 API。
    """
    if not file_path or '/' not in file_path:
        return ({}, []) if return_dir_files else {}
    dir_path = file_path.rsplit('/', 1)[0] or '/'
    dir_files = api.get_file_list(dir_path) or []

    file_list_for_nfo = []
    for f in dir_files:
        name = f.get('name', '')
        if f.get('is_dir'):
            continue
        full_path = (f.get('path') or dir_path).rstrip('/') + '/' + name
        file_list_for_nfo.append({'name': name, 'full_path': full_path})

    matching_nfo = get_nfo_file_for_video(file_path, file_list_for_nfo)
    if not matching_nfo or not matching_nfo.get('full_path'):
        return ({}, dir_files) if return_dir_files else {}

    nfo_direct_url = api.get_file_link(matching_nfo['full_path'])
    headers = {"Authorization": f"Bearer {api.token}"}
    resp = requests.get(nfo_direct_url, headers=headers, timeout=5)
    if resp.status_code != 200:
        return ({}, dir_files) if return_dir_files else {}
    nfo_data = parse_nfo_content(resp.text)
    metadata = extract_nfo_metadata(nfo_data)
    # 封面为纯文件名时转为 OpenList 完整直链（封面与视频同目录）
    if metadata and metadata.get('cover'):
        metadata['cover'] = _resolve_nfo_cover(metadata['cover'], dir_path, api)
    metadata = metadata or {}
    return (metadata, dir_files) if return_dir_files else metadata


@app.route('/api/videos/<int:video_id>/refresh_nfo', methods=['POST'])
@admin_required
def api_refresh_video_nfo(video_id):
    """重新读取视频所在目录的 NFO 文件并更新视频元数据。
    适用于修改前导入的视频：通过 video_url 反推 OpenList 账户与路径。
    """
    from models import get_all_openlist_accounts
    video = get_video(video_id)
    if not video:
        return jsonify({'success': False, 'message': '视频不存在'}), 404

    video_url = video.get('video_url', '')
    server_url, file_path = _extract_path_from_video_url(video_url)
    if not server_url or not file_path:
        return jsonify({'success': False, 'message': '无法从视频URL解析路径，可能不是OpenList来源'}), 400

    # 匹配 OpenList 账户
    accounts = get_all_openlist_accounts()
    account = None
    for acc in accounts:
        if acc.get('server_url', '').rstrip('/') == server_url.rstrip('/'):
            account = acc
            break
    if not account:
        return jsonify({'success': False, 'message': f'未找到匹配的OpenList账户: {server_url}'}), 400

    api = OpenListApi(account['server_url'], account['username'], account['password'])
    try:
        api.login()
    except Exception as e:
        return jsonify({'success': False, 'message': f'OpenList登录失败: {e}'}), 500

    try:
        metadata = _fetch_nfo_for_video(account, file_path, api)
    except Exception as e:
        return jsonify({'success': False, 'message': f'读取NFO失败: {e}'}), 500

    if not metadata:
        return jsonify({'success': False, 'message': '未在视频所在目录找到匹配的NFO文件'}), 404

    # 更新数据库（NFO 字段优先）
    update_data = {}
    if metadata.get('title'):
        update_data['title'] = metadata['title']
    if metadata.get('description'):
        update_data['description'] = metadata['description']
    if metadata.get('cover'):
        update_data['cover'] = metadata['cover']
    if metadata.get('genre'):
        update_data['genre'] = metadata['genre']
    if metadata.get('rating'):
        update_data['rating'] = metadata['rating']
    if metadata.get('year'):
        update_data['year'] = metadata['year']
    if metadata.get('actors'):
        actors_list = metadata['actors']
        if isinstance(actors_list, list):
            update_data['actors'] = ', '.join([a.get('name', '') for a in actors_list if a.get('name')])
        else:
            update_data['actors'] = str(actors_list)

    if update_data:
        update_video(video_id, update_data)

    return jsonify({
        'success': True,
        'message': f'成功更新 {len(update_data)} 个字段',
        'updated_fields': list(update_data.keys()),
        'new_title': update_data.get('title', video.get('title'))
    })


# ===================== 本地视频导入模块 =====================

# 本地视频/图片扩展名集合
_LOCAL_VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm',
                           '.m4v', '.3gp', '.mpg', '.mpeg', '.ts', '.m2ts', '.mts',
                           '.iso', '.rmvb', '.rm', '.dat', '.vob', '.asf', '.m3u8'}
_LOCAL_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg',
                           '.ico', '.tiff', '.tif', '.heic', '.avif'}


def _get_local_mime(file_path):
    """根据扩展名猜测 MIME 类型"""
    mime, _ = mimetypes.guess_type(file_path)
    return mime or 'application/octet-stream'


def _find_local_nfo_for_video(video_path):
    """从视频所在目录查找并解析同名/通用 NFO 文件，返回 metadata dict（可能为空）。"""
    if not video_path or not os.path.exists(video_path):
        return {}
    dir_path = os.path.dirname(video_path) or '.'
    video_base = os.path.splitext(os.path.basename(video_path))[0].lower()

    nfo_candidates = []
    try:
        for entry in os.scandir(dir_path):
            if entry.is_dir():
                continue
            if entry.name.lower().endswith('.nfo'):
                nfo_candidates.append(entry.name)
    except (PermissionError, OSError):
        return {}

    target_nfo = None
    # 优先级 1：与视频同名的 NFO
    for nfo_name in nfo_candidates:
        if os.path.splitext(nfo_name)[0].lower() == video_base:
            target_nfo = os.path.join(dir_path, nfo_name)
            break
    # 优先级 2：通用 NFO（movie.nfo / tvshow.nfo / serie.nfo）
    if not target_nfo:
        for nfo_name in nfo_candidates:
            if nfo_name.lower() in ('movie.nfo', 'tvshow.nfo', 'serie.nfo'):
                target_nfo = os.path.join(dir_path, nfo_name)
                break
    if not target_nfo:
        return {}

    try:
        with open(target_nfo, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        nfo_data = parse_nfo_content(content)
        return extract_nfo_metadata(nfo_data) or {}
    except Exception:
        return {}


def _find_local_cover_for_video(video_path):
    """在视频所在目录查找封面图片。返回 (absolute_path, reason) 或 (None, None)。"""
    if not video_path or not os.path.exists(video_path):
        return None, None
    dir_path = os.path.dirname(video_path) or '.'
    return _find_local_cover_in_dir(dir_path)


def _find_local_cover_in_dir(dir_path):
    """在指定目录中按优先级挑选封面图片。"""
    image_files = []
    try:
        for entry in os.scandir(dir_path):
            if entry.is_dir():
                continue
            ext = os.path.splitext(entry.name)[1].lower()
            if ext in _LOCAL_IMAGE_EXTENSIONS:
                image_files.append(entry.name)
    except (PermissionError, OSError):
        return None, None

    if not image_files:
        return None, None

    image_files.sort(key=str.lower)

    # 优先级 1：目录中只有一张图片
    if len(image_files) == 1:
        return os.path.join(dir_path, image_files[0]), '目录唯一图片'
    # 优先级 2：图片名含 "poster"
    for img_name in image_files:
        if 'poster' in img_name.lower():
            return os.path.join(dir_path, img_name), '图片名含poster'
    # 优先级 3：首张图片
    return os.path.join(dir_path, image_files[0]), '目录首张图片'


def _apply_nfo_metadata_to_video_data(metadata, video_data):
    """将 NFO 元数据合并到 video_data 字典中（仅当字段存在时覆盖）。"""
    if not metadata:
        return False
    if metadata.get('title'):
        video_data['title'] = metadata['title']
    if metadata.get('description'):
        video_data['description'] = metadata['description']
    if metadata.get('cover'):
        # NFO 封面通常是远程URL，直接写入 cover 字段；若后续找到本地封面文件会覆盖
        video_data['cover'] = metadata['cover']
    if metadata.get('genre'):
        video_data['genre'] = metadata['genre']
    if metadata.get('rating'):
        video_data['rating'] = metadata['rating']
    if metadata.get('year'):
        video_data['year'] = metadata['year']
    if metadata.get('actors'):
        actors_list = metadata['actors']
        if isinstance(actors_list, list):
            video_data['actors'] = ', '.join([a.get('name', '') for a in actors_list if a.get('name')])
        else:
            video_data['actors'] = str(actors_list)
    if metadata.get('episode_number'):
        video_data['episode_number'] = metadata['episode_number']
    return True


@app.route('/api/local_import/browse', methods=['POST'])
@admin_required
def api_local_browse():
    """浏览本地目录：返回子目录与文件列表。
    path 为空时返回磁盘驱动器列表（Windows）或根目录（其它系统）。
    """
    data = request.json or {}
    path = (data.get('path') or '').strip()

    # 无路径 → 列出驱动器/根
    if not path or path in ('/', '\\', ''):
        if os.name == 'nt':
            drives = []
            for letter in 'CDEFGHIJKLMNOPQRSTUVWXYZ':
                p = f'{letter}:\\'
                if os.path.exists(p) and os.path.isdir(p):
                    drives.append({
                        'name': f'{letter}:',
                        'full_path': p,
                        'is_dir': True,
                        'size': 0,
                    })
            return jsonify({'success': True, 'files': drives, 'current_path': ''})
        path = '/'

    # 规范化并校验
    path = os.path.normpath(path)
    if not os.path.exists(path):
        return jsonify({'success': False, 'message': '路径不存在: ' + path}), 400
    if not os.path.isdir(path):
        return jsonify({'success': False, 'message': '不是目录: ' + path}), 400

    files = []
    try:
        for entry in os.scandir(path):
            try:
                is_dir = entry.is_dir()
                size = 0 if is_dir else entry.stat().st_size
            except OSError:
                is_dir = False
                size = 0
            files.append({
                'name': entry.name,
                'full_path': entry.path,
                'is_dir': is_dir,
                'size': size,
            })
    except PermissionError:
        return jsonify({'success': False, 'message': '无权限访问此目录'}), 403
    except Exception as e:
        return jsonify({'success': False, 'message': '读取目录失败: ' + str(e)}), 500

    # 排序：目录优先，再按名称
    files.sort(key=lambda f: (not f['is_dir'], str(f['name']).lower()))
    return jsonify({'success': True, 'files': files, 'current_path': path})


@app.route('/api/local_import/nfo', methods=['POST'])
@admin_required
def api_local_nfo():
    """解析本地 NFO 文件，返回元数据字典。"""
    data = request.json or {}
    file_path = (data.get('path') or '').strip()
    if not file_path or not os.path.exists(file_path) or not os.path.isfile(file_path):
        return jsonify({'success': False, 'message': 'NFO 文件不存在'}), 400
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        nfo_data = parse_nfo_content(content)
        return jsonify({'success': True, 'data': nfo_data})
    except Exception as e:
        return jsonify({'success': False, 'message': '解析失败: ' + str(e)}), 500


@app.route('/api/local_import/preview')
@admin_required
def api_local_preview():
    """预览本地文件（视频/图片），仅后台管理使用。"""
    file_path = (request.args.get('path') or '').strip()
    if not file_path or not os.path.exists(file_path) or not os.path.isfile(file_path):
        abort(404)
    mime = _get_local_mime(file_path)
    try:
        return send_file(file_path, mimetype=mime, conditional=True)
    except Exception:
        abort(404)


@app.route('/api/local_import/single_import', methods=['POST'])
@admin_required
def api_local_single_import():
    """导入单个本地视频文件。"""
    data = request.json or {}
    file_path = (data.get('file_path') or '').strip()
    category_id = int(data.get('category_id', 0) or 0)
    cover_path = (data.get('cover_path') or '').strip()
    is_short_video = int(data.get('is_short_video', 0) or 0)
    use_nfo = bool(data.get('use_nfo', True))

    if not file_path:
        return jsonify({'success': False, 'message': '未指定文件路径'}), 400
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        return jsonify({'success': False, 'message': '文件不存在: ' + file_path}), 400
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in _LOCAL_VIDEO_EXTENSIONS:
        return jsonify({'success': False, 'message': '不是支持的视频格式: ' + ext}), 400

    # 去重：按本地文件绝对路径
    existing = get_video_by_local_path(file_path)
    if existing:
        return jsonify({'success': False, 'message': '该本地视频已导入: ' + existing.get('title', '')}), 400

    file_name = os.path.basename(file_path)
    video_base_name = os.path.splitext(file_name)[0]
    video_data = {
        'title': video_base_name,
        'video_url': '',  # 创建后回填流式URL
        'cover': '',
        'category_id': category_id,
        'source': 'local',
        'video_type': ext.lstrip('.'),
        'is_short_video': is_short_video,
        'local_file_path': file_path,
        'local_cover_path': '',
    }

    nfo_used = False
    if use_nfo:
        metadata = _find_local_nfo_for_video(file_path)
        nfo_used = _apply_nfo_metadata_to_video_data(metadata, video_data)

    # 封面：手动指定 > 自动查找
    cover_path_resolved = cover_path
    if cover_path_resolved and (not os.path.exists(cover_path_resolved) or not os.path.isfile(cover_path_resolved)):
        cover_path_resolved = ''
    if not cover_path_resolved:
        cover_path_resolved, _ = _find_local_cover_for_video(file_path)
    if cover_path_resolved:
        video_data['local_cover_path'] = cover_path_resolved

    video_id = create_video(video_data)

    # 回填流式播放URL
    update_data = {'video_url': f'/local_video/{video_id}'}
    if cover_path_resolved:
        update_data['cover'] = f'/local_cover/{video_id}'
    update_video(video_id, update_data)

    return jsonify({
        'success': True,
        'video_id': video_id,
        'video_name': video_data['title'],
        'nfo_used': nfo_used,
        'cover_used': bool(cover_path_resolved),
    })


@app.route('/api/local_import/multi_import', methods=['POST'])
@admin_required
def api_local_multi_import():
    """导入多个本地视频文件（使用原文件名作为标题，不创建系列）。"""
    data = request.json or {}
    files = data.get('files', []) or []
    category_id = int(data.get('category_id', 0) or 0)
    cover_path = (data.get('cover_path') or '').strip()
    is_short_video = int(data.get('is_short_video', 0) or 0)
    use_nfo = bool(data.get('use_nfo', True))

    if not files:
        return jsonify({'success': False, 'message': '未选择任何视频文件'}), 400

    imported, skipped, failed = [], [], []
    nfo_used = 0

    for f in files:
        file_path = (f.get('file_path') or '').strip()
        file_name = f.get('file_name') or os.path.basename(file_path)
        if not file_path:
            failed.append({'name': file_name, 'error': '路径缺失'})
            continue
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            failed.append({'name': file_name, 'error': '文件不存在'})
            continue
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in _LOCAL_VIDEO_EXTENSIONS:
            failed.append({'name': file_name, 'error': '不支持的视频格式: ' + ext})
            continue

        # 去重
        if get_video_by_local_path(file_path):
            skipped.append({'name': file_name, 'reason': '已存在'})
            continue

        video_base_name = os.path.splitext(file_name)[0]
        video_data = {
            'title': video_base_name,
            'video_url': '',
            'cover': '',
            'category_id': category_id,
            'source': 'local',
            'video_type': ext.lstrip('.'),
            'is_short_video': is_short_video,
            'local_file_path': file_path,
            'local_cover_path': '',
        }

        file_nfo_used = False
        if use_nfo:
            metadata = _find_local_nfo_for_video(file_path)
            file_nfo_used = _apply_nfo_metadata_to_video_data(metadata, video_data)
            if file_nfo_used:
                nfo_used += 1

        # 每个视频独立查找封面（除非用户指定了统一封面）
        cover_path_resolved = cover_path
        if cover_path_resolved and (not os.path.exists(cover_path_resolved) or not os.path.isfile(cover_path_resolved)):
            cover_path_resolved = ''
        if not cover_path_resolved:
            cover_path_resolved, _ = _find_local_cover_for_video(file_path)
        if cover_path_resolved:
            video_data['local_cover_path'] = cover_path_resolved

        try:
            video_id = create_video(video_data)
            update_data = {'video_url': f'/local_video/{video_id}'}
            if cover_path_resolved:
                update_data['cover'] = f'/local_cover/{video_id}'
            update_video(video_id, update_data)
            imported.append({'name': video_data['title'], 'nfo_used': file_nfo_used})
        except Exception as e:
            failed.append({'name': file_name, 'error': str(e)})

    return jsonify({
        'success': True,
        'imported_count': len(imported),
        'skipped_count': len(skipped),
        'failed_count': len(failed),
        'imported': imported[:20],
        'nfo_used': nfo_used,
    })


@app.route('/api/local_import/directory_import', methods=['POST'])
@admin_required
def api_local_directory_import():
    """批量导入本地目录下所有视频（支持递归子目录，可选创建系列）。"""
    data = request.json or {}
    dir_path = (data.get('path') or '').strip()
    category_id = int(data.get('category_id', 0) or 0)
    auto_create_series = bool(data.get('auto_create_series', False))
    series_name = (data.get('series_name') or '').strip()
    cover_path = (data.get('cover_path') or '').strip()
    use_nfo = bool(data.get('use_nfo', True))
    is_short_video = int(data.get('is_short_video', 0) or 0)
    recursive = bool(data.get('recursive', True))

    if not dir_path or not os.path.isdir(dir_path):
        return jsonify({'success': False, 'message': '目录不存在'}), 400

    # 收集所有视频文件
    videos = []
    if recursive:
        for root, _dirs, fnames in os.walk(dir_path):
            for fname in fnames:
                ext = os.path.splitext(fname)[1].lower()
                if ext in _LOCAL_VIDEO_EXTENSIONS:
                    videos.append(os.path.join(root, fname))
    else:
        try:
            for entry in os.scandir(dir_path):
                if entry.is_file():
                    ext = os.path.splitext(entry.name)[1].lower()
                    if ext in _LOCAL_VIDEO_EXTENSIONS:
                        videos.append(entry.path)
        except (PermissionError, OSError) as e:
            return jsonify({'success': False, 'message': '读取目录失败: ' + str(e)}), 500
    videos.sort()

    if not videos:
        return jsonify({'success': False, 'message': '目录中没有可导入的视频文件'}), 400

    imported, skipped, failed = [], [], []
    nfo_used = 0
    series_id = None

    # 创建系列
    if auto_create_series and series_name:
        existing_series = get_all_series(per_page=500)['series_list']
        for s in existing_series:
            if s['title'] == series_name:
                series_id = s['id']
                break

        if not series_id:
            series_cover = ''
            # 尝试从目录根的 movie.nfo/tvshow.nfo 获取系列封面（NFO 中的封面通常是远程URL，直接使用）
            if use_nfo:
                for nfo_name in ('movie.nfo', 'tvshow.nfo', 'serie.nfo'):
                    nfo_path = os.path.join(dir_path, nfo_name)
                    if os.path.exists(nfo_path) and os.path.isfile(nfo_path):
                        try:
                            with open(nfo_path, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read()
                            nfo_data = parse_nfo_content(content)
                            if nfo_data.get('poster'):
                                series_cover = nfo_data['poster']
                            elif nfo_data.get('thumbs'):
                                series_cover = nfo_data['thumbs'][0]
                            if nfo_data.get('title') and not series_name:
                                series_name = nfo_data['title']
                            break
                        except Exception:
                            pass
            # 没有NFO封面则使用手动/目录图片
            if not series_cover:
                if cover_path and os.path.isfile(cover_path):
                    series_cover = cover_path
                else:
                    cp, _ = _find_local_cover_in_dir(dir_path)
                    if cp:
                        series_cover = cp

            series_id = create_series({
                'title': series_name,
                'cover': series_cover,
                'category_id': category_id,
                'total_episodes': len(videos),
            })

    for idx, video_path in enumerate(videos, 1):
        file_name = os.path.basename(video_path)
        # 去重
        if get_video_by_local_path(video_path):
            skipped.append({'name': file_name, 'reason': '已存在'})
            continue

        ext = os.path.splitext(video_path)[1].lower()
        video_base_name = os.path.splitext(file_name)[0]

        # 标题：创建系列时用「系列名 第N集」；否则用原文件名
        if series_id:
            base_title = f'{series_name} 第{idx}集' if len(videos) > 1 else series_name
        else:
            base_title = video_base_name

        video_data = {
            'title': base_title,
            'video_url': '',
            'cover': '',
            'category_id': category_id,
            'source': 'local',
            'video_type': ext.lstrip('.'),
            'is_short_video': is_short_video,
            'local_file_path': video_path,
            'local_cover_path': '',
        }

        file_nfo_used = False
        if use_nfo:
            metadata = _find_local_nfo_for_video(video_path)
            file_nfo_used = _apply_nfo_metadata_to_video_data(metadata, video_data)
            if file_nfo_used:
                nfo_used += 1
                # 若NFO提供集数且创建系列，标记为系列分集
                if metadata.get('episode_number') and series_id:
                    video_data['is_series'] = 1

        # 封面优先级：视频所在目录的封面 > 手动选择的 cover_path
        # 非末端目录批量导入时，各子目录中的视频优先使用各自目录中的封面图片
        dir_cover, _ = _find_local_cover_for_video(video_path)
        if dir_cover:
            cover_path_resolved = dir_cover
        elif cover_path and os.path.isfile(cover_path):
            cover_path_resolved = cover_path
        else:
            cover_path_resolved = ''
        if cover_path_resolved:
            video_data['local_cover_path'] = cover_path_resolved

        if series_id:
            video_data['series_id'] = series_id
            if not video_data.get('episode_number'):
                video_data['episode_number'] = idx
            video_data['is_series'] = 1

        try:
            video_id = create_video(video_data)
            update_data = {'video_url': f'/local_video/{video_id}'}
            if cover_path_resolved:
                update_data['cover'] = f'/local_cover/{video_id}'
            update_video(video_id, update_data)
            imported.append({'name': video_data['title'], 'nfo_used': file_nfo_used})
        except Exception as e:
            failed.append({'name': file_name, 'error': str(e)})

    # 更新系列总集数
    if series_id and (imported or skipped):
        try:
            update_series(series_id, {'total_episodes': len(videos)})
        except Exception:
            pass

    return jsonify({
        'success': True,
        'imported_count': len(imported),
        'skipped_count': len(skipped),
        'failed_count': len(failed),
        'imported': imported[:20],
        'series_name': series_name if series_id else None,
        'nfo_used': nfo_used,
    })


@app.route('/local_video/<int:video_id>')
def local_video_stream(video_id):
    """流式播放本地视频文件（支持 HTTP Range，用于浏览器/APP 拖动进度条）。"""
    video = get_video(video_id)
    if not video or video.get('source') != 'local':
        abort(404)
    file_path = video.get('local_file_path') or ''
    if not file_path or not os.path.exists(file_path) or not os.path.isfile(file_path):
        abort(404)
    mime = _get_local_mime(file_path)
    try:
        return send_file(file_path, mimetype=mime, conditional=True)
    except Exception:
        abort(404)


@app.route('/local_cover/<int:video_id>')
def local_cover_stream(video_id):
    """提供本地视频封面图片流。"""
    video = get_video(video_id)
    if not video or video.get('source') != 'local':
        abort(404)
    file_path = video.get('local_cover_path') or ''
    if not file_path or not os.path.exists(file_path) or not os.path.isfile(file_path):
        abort(404)
    mime = _get_local_mime(file_path)
    try:
        return send_file(file_path, mimetype=mime, conditional=True)
    except Exception:
        abort(404)


# ===================== 图集模块 =====================

# 图集本地复制文件存储根目录：static/album_images/<album_id>/
# 【关键】打包成 EXE 后必须落在 BASE_DIR（用户数据目录 = EXE 同级，持久化），
# 绝不能落在 RESOURCE_DIR —— 后者是 sys._MEIPASS 临时解压目录，单文件模式下
# 每次退出即被删除，会导致导入的图集图片/视频全部丢失。
_ALBUM_IMAGE_ROOT = os.path.join(BASE_DIR, 'static', Config.ALBUM_IMAGE_DIR)
# 打包资源内的图集目录：旧版 onedir 布局会把图片写进 _internal/static/album_images。
# 保留仅作读取回退，用于兼容升级前已导入的旧图集。
_ALBUM_IMAGE_ROOT_BUNDLED = os.path.join(RESOURCE_DIR, 'static', Config.ALBUM_IMAGE_DIR)


def _resolve_album_file(filename):
    """在图集根目录内解析相对路径，返回真实文件路径；不存在或非法则返回 None。

    查找顺序：持久化用户数据目录（新导入的图集）→ 打包资源目录（旧版 onedir 布局）。
    做目录穿越防护：解析后的绝对路径必须仍位于允许的根目录内。
    """
    norm = os.path.normpath(filename or '').replace('\\', '/').lstrip('/')
    if not norm or norm == '.' or norm == '..' or norm.startswith('../'):
        return None
    for root in (_ALBUM_IMAGE_ROOT, _ALBUM_IMAGE_ROOT_BUNDLED):
        if not root:
            continue
        root_norm = os.path.normpath(root)
        fp = os.path.normpath(os.path.join(root_norm, norm))
        if not (fp == root_norm or fp.startswith(root_norm + os.sep)):
            continue  # 目录穿越，跳过该根目录
        if os.path.isfile(fp):
            return fp
    return None


@app.route('/static/album_images/<path:filename>')
def serve_album_image(filename):
    """图集图片/视频：从持久化用户数据目录读取，不随 EXE 解压目录销毁。

    打包成单文件后，Flask 内置 static 路由指向 _MEI 临时目录，而导入的图集
    文件保存在 EXE 同级的 static/album_images/ 下，因此显式接管该前缀，
    保证图集文件可访问、重启后不丢失。conditional=True 支持视频拖动进度条（Range）。
    """
    fp = _resolve_album_file(filename)
    if not fp:
        abort(404)
    return send_file(fp, conditional=True)


def _safe_filename(name, max_len=80):
    """生成安全的文件名（保留扩展名），用于复制到图集目录"""
    name = (name or '').strip().replace('\\', '_').replace('/', '_').replace(':', '_')
    name = ''.join(ch for ch in name if ch.isprintable())
    if len(name) > max_len:
        base, ext = os.path.splitext(name)
        name = base[:max_len - len(ext)] + ext
    return name or 'image'


def _natural_sort_key(name):
    """自然排序键：让 '2.jpg' 排在 '10.jpg' 前。"""
    import re
    parts = re.split(r'(\d+)', (name or '').lower())
    return [int(p) if p.isdigit() else p for p in parts]


def _normalize_sort_order_list(value):
    """解析前端传来的顺序列表，支持 list 或 JSON 字符串。"""
    if isinstance(value, list):
        return [int(x) for x in value if str(x).isdigit()]
    if isinstance(value, str):
        try:
            arr = json.loads(value)
            if isinstance(arr, list):
                return [int(x) for x in arr if str(x).isdigit()]
        except Exception:
            return []
    return []


def _make_album_dir(album_id):
    """创建图集本地图片目录，返回绝对路径。"""
    d = os.path.join(_ALBUM_IMAGE_ROOT, str(album_id))
    os.makedirs(d, exist_ok=True)
    return d


def _basename_from_url(url):
    """从 URL 中抽取文件名。"""
    try:
        from urllib.parse import urlparse, unquote
        path = urlparse(url).path
        name = path.rstrip('/').split('/')[-1] if path else url
        return unquote(name) or url
    except Exception:
        return url


# ---------- 公开浏览 ----------

@app.route('/albums')
@login_required
def albums_index():
    """图集浏览首页（侧栏分类 + 图集网格 + 分页）"""
    categories = get_all_album_categories()
    cat_tree = get_album_category_tree()
    parent_ids = {c['id'] for c in categories if c.get('parent_id', 0) == 0}
    sub_parent_set = {c.get('parent_id', 0) for c in categories if c.get('parent_id', 0) in parent_ids}
    categories = sorted(categories, key=lambda c: (
        c.get('parent_id', 0),
        0 if (c.get('parent_id', 0) == 0 and c['id'] in sub_parent_set) else 1,
        c.get('sort_order', 0),
        c.get('id', 0),
    ))
    # 图集分类权限过滤（参考短视频逻辑）：有权限限制时仅显示允许的分类
    uid = session.get('user_id')
    allowed_ids = get_user_allowed_category_ids(uid, 'album') if uid else None
    if allowed_ids is not None:
        categories = [c for c in categories if c['id'] in allowed_ids]
    keyword = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 20
    # 有权限限制时，仅查询允许分类下的图集
    if allowed_ids is not None:
        result = get_all_albums(keyword=keyword, page=page, per_page=per_page, category_ids=allowed_ids)
    else:
        result = get_all_albums(keyword=keyword, page=page, per_page=per_page)
    return render_template('albums.html',
                         categories=categories,
                         cat_tree=cat_tree,
                         albums=result['albums'],
                         keyword=keyword,
                         page=page,
                         total_pages=result['total_pages'],
                         total=result['total'],
                         active_tab='albums')


@app.route('/albums/category/<int:category_id>')
@login_required
def albums_by_category(category_id):
    """按图集分类浏览"""
    categories = get_all_album_categories()
    cat_tree = get_album_category_tree()
    parent_ids = {c['id'] for c in categories if c.get('parent_id', 0) == 0}
    sub_parent_set = {c.get('parent_id', 0) for c in categories if c.get('parent_id', 0) in parent_ids}
    categories = sorted(categories, key=lambda c: (
        c.get('parent_id', 0),
        0 if (c.get('parent_id', 0) == 0 and c['id'] in sub_parent_set) else 1,
        c.get('sort_order', 0),
        c.get('id', 0),
    ))
    # 图集分类权限过滤：无权访问的分类直接跳回全部
    uid = session.get('user_id')
    allowed_ids = get_user_allowed_category_ids(uid, 'album') if uid else None
    if allowed_ids is not None:
        categories = [c for c in categories if c['id'] in allowed_ids]
        if category_id not in allowed_ids:
            return redirect(url_for('albums_index'))
    page = request.args.get('page', 1, type=int)
    per_page = 20
    result = get_all_albums(category_id=category_id, page=page, per_page=per_page)
    current_category = next((c for c in categories if c['id'] == category_id), None)
    return render_template('albums.html',
                         categories=categories,
                         cat_tree=cat_tree,
                         albums=result['albums'],
                         current_category=current_category,
                         page=page,
                         total_pages=result['total_pages'],
                         total=result['total'],
                         active_tab='albums')


@app.route('/album/<int:album_id>')
@login_required
def album_detail(album_id):
    """图集详情页：展示图片网格 + 灯箱 + 视频内嵌播放"""
    album = get_album(album_id)
    if not album:
        abort(404)
    # 图集分类权限过滤：无权访问该图集所属分类时禁止查看
    uid = session.get('user_id')
    allowed_ids = get_user_allowed_category_ids(uid, 'album') if uid else None
    if allowed_ids is not None and album.get('category_id') not in allowed_ids:
        abort(403)
    all_media = get_album_images(album_id)
    # 按 media_type 分桶：图片走灯箱，视频走内嵌播放（两者顺序各自连续）
    image_items = [m for m in all_media if (m.get('media_type') or 'image') == 'image']
    video_items = [m for m in all_media if (m.get('media_type') or 'image') == 'video']
    increment_album_views(album_id)
    album['views'] = album.get('views', 0) + 1
    category = get_album_category(album.get('category_id', 0)) if album.get('category_id') else None
    return render_template('album_detail.html',
                         album=album,
                         images=image_items,
                         videos=video_items,
                         category=category,
                         active_tab='albums')


# ---------- 后台：图集分类管理 ----------

@app.route('/admin/album_categories')
@admin_required
def admin_album_categories():
    categories = get_all_album_categories()
    cat_map = {c['id']: c for c in categories}
    children_map = {}
    for c in categories:
        pid = c.get('parent_id', 0)
        children_map.setdefault(pid, []).append(c['id'])
    ordered, visited = [], set()

    def _walk(cat_id):
        if cat_id in visited:
            return
        visited.add(cat_id)
        ordered.append(cat_map[cat_id])
        kids = sorted(children_map.get(cat_id, []),
                      key=lambda kid_id: (cat_map[kid_id].get('sort_order', 0),
                                          cat_map[kid_id].get('id', 0)))
        for kid_id in kids:
            _walk(kid_id)

    top_level = sorted([c['id'] for c in categories if c.get('parent_id', 0) == 0],
                       key=lambda tid: (cat_map[tid].get('sort_order', 0), cat_map[tid].get('id', 0)))
    for tid in top_level:
        _walk(tid)
    for c in categories:
        if c['id'] not in visited:
            ordered.append(c)
            visited.add(c['id'])

    page = request.args.get('page', 1, type=int)
    per_page = 20
    total = len(ordered)
    total_pages = (total + per_page - 1) // per_page if per_page > 0 else 0
    start = (page - 1) * per_page
    paginated_categories = ordered[start:start + per_page]
    return render_template('admin/album_categories.html',
                         categories=ordered,
                         paginated_categories=paginated_categories,
                         page=page,
                         total=total,
                         total_pages=total_pages,
                         active_tab='album_categories')


# ---------- 后台：图集管理 ----------

@app.route('/admin/albums')
@admin_required
def admin_albums():
    keyword = request.args.get('keyword', '').strip()
    category_id = request.args.get('category_id', type=int)
    page = request.args.get('page', 1, type=int)
    per_page = 20
    result = get_all_albums(category_id=category_id, keyword=keyword, page=page, per_page=per_page)
    categories = get_all_album_categories()
    return render_template('admin/albums.html',
                         albums=result['albums'],
                         categories=categories,
                         keyword=keyword,
                         selected_category=category_id,
                         page=page,
                         total_pages=result['total_pages'],
                         total=result['total'],
                         active_tab='albums')


@app.route('/admin/albums/add', methods=['GET', 'POST'])
@admin_required
def admin_album_add():
    categories = get_all_album_categories()
    if request.method == 'POST':
        data = {
            'title': request.form.get('title', '').strip(),
            'description': request.form.get('description', '').strip(),
            'category_id': request.form.get('category_id', 0, type=int),
            'cover': request.form.get('cover', '').strip(),
            'source': request.form.get('source', 'openlist').strip(),
            'sort_order': request.form.get('sort_order', 0, type=int),
        }
        if not data['title']:
            return render_template('admin/album_form.html',
                                 album=data, categories=categories,
                                 error='标题为必填项',
                                 active_tab='albums')
        album_id = create_album(data)
        # 可选：一次性附 URL 列表
        image_urls_text = request.form.get('initial_image_urls', '').strip()
        if image_urls_text:
            urls = [u.strip() for u in image_urls_text.splitlines() if u.strip()]
            items = [{'image_url': u, 'source': data['source']} for u in urls]
            add_album_images(album_id, items)
        return redirect(url_for('admin_albums'))
    return render_template('admin/album_form.html',
                         album={'source': 'openlist'},
                         categories=categories,
                         active_tab='albums')


@app.route('/admin/albums/edit/<int:album_id>', methods=['GET', 'POST'])
@admin_required
def admin_album_edit(album_id):
    album = get_album(album_id)
    if not album:
        abort(404)
    categories = get_all_album_categories()
    images = get_album_images(album_id)
    if request.method == 'POST':
        data = {
            'title': request.form.get('title', '').strip(),
            'description': request.form.get('description', '').strip(),
            'category_id': request.form.get('category_id', 0, type=int),
            'cover': request.form.get('cover', '').strip(),
            'source': request.form.get('source', album.get('source', 'openlist')).strip(),
            'sort_order': request.form.get('sort_order', 0, type=int),
        }
        if not data['title']:
            return render_template('admin/album_form.html',
                                 album=data, categories=categories,
                                 images=images, error='标题为必填项',
                                 active_tab='albums')
        update_album(album_id, data)
        return redirect(url_for('admin_album_edit', album_id=album_id))
    return render_template('admin/album_form.html',
                         album=album,
                         categories=categories,
                         images=images,
                         active_tab='albums')


# ---------- 后台：图片导入 ----------

@app.route('/admin/image_import')
@admin_required
def admin_image_import():
    categories = get_all_album_categories()
    openlist_accounts = get_all_openlist_accounts()
    return render_template('admin/image_import.html',
                         categories=categories,
                         openlist_accounts=openlist_accounts,
                         active_tab='image_import')


# ---------- 图集分类 API ----------

@app.route('/api/album_categories', methods=['GET'])
@api_login_required
def api_album_categories_list():
    categories = get_all_album_categories()
    return jsonify({'success': True, 'categories': categories})


@app.route('/api/album_categories', methods=['POST'])
@api_login_required
def api_album_categories_create():
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'message': '分类名称不能为空'})
    parent_id = int(data.get('parent_id') or 0)
    sort_order = int(data.get('sort_order') or 0)
    ok, cat_id = create_album_category(name, parent_id=parent_id, sort_order=sort_order)
    if not ok:
        return jsonify({'success': False, 'message': '分类名称已存在'})
    return jsonify({'success': True, 'id': cat_id})


@app.route('/api/album_categories/<int:cat_id>', methods=['PUT'])
@api_login_required
def api_album_categories_update(cat_id):
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'message': '分类名称不能为空'})
    update_album_category(cat_id, name=name,
                          parent_id=int(data.get('parent_id') or 0),
                          sort_order=int(data.get('sort_order') or 0))
    return jsonify({'success': True})


@app.route('/api/album_categories/<int:cat_id>', methods=['DELETE'])
@api_login_required
def api_album_categories_delete(cat_id):
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    delete_album_category(cat_id)
    return jsonify({'success': True})


@app.route('/api/album_categories/batch_delete', methods=['POST'])
@api_login_required
def api_album_categories_batch_delete():
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    data = request.get_json() or {}
    ids = [int(x) for x in (data.get('category_ids') or []) if str(x).isdigit()]
    deleted = batch_delete_album_categories(ids)
    return jsonify({'success': True, 'deleted_count': deleted})


@app.route('/api/album_categories/batch_delete_all', methods=['POST'])
@api_login_required
def api_album_categories_batch_delete_all():
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    deleted = batch_delete_all_album_categories()
    return jsonify({'success': True, 'deleted_count': deleted})


# ---------- 图集 API ----------

@app.route('/api/albums', methods=['GET'])
@api_login_required
def api_albums_list():
    keyword = request.args.get('keyword', '').strip()
    category_id = request.args.get('category_id', type=int)
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 500)
    result = get_all_albums(category_id=category_id, keyword=keyword, page=page, per_page=per_page)
    return jsonify({'success': True,
                    'albums': result['albums'],
                    'total': result['total'],
                    'page': result['page'],
                    'per_page': result['per_page'],
                    'total_pages': result['total_pages']})


@app.route('/api/albums/<int:album_id>', methods=['GET'])
@api_login_required
def api_albums_get(album_id):
    album = get_album(album_id)
    if not album:
        return jsonify({'success': False, 'message': '图集不存在'}), 404
    images = get_album_images(album_id)
    return jsonify({'success': True, 'album': album, 'images': images})


@app.route('/api/albums/<int:album_id>', methods=['PUT'])
@api_login_required
def api_albums_update(album_id):
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    album = get_album(album_id)
    if not album:
        return jsonify({'success': False, 'message': '图集不存在'}), 404
    data = request.get_json() or {}
    update_album(album_id, {
        'title': (data.get('title') or album['title']).strip(),
        'description': (data.get('description') or '').strip(),
        'category_id': int(data.get('category_id') or 0),
        'cover': (data.get('cover') or '').strip(),
        'sort_order': int(data.get('sort_order') or 0),
    })
    return jsonify({'success': True})


@app.route('/api/albums/<int:album_id>', methods=['DELETE'])
@api_login_required
def api_albums_delete(album_id):
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    delete_files = request.args.get('delete_files', 'false').lower() == 'true'
    delete_album(album_id, delete_files=delete_files)
    return jsonify({'success': True})


@app.route('/api/albums/batch_delete', methods=['POST'])
@api_login_required
def api_albums_batch_delete():
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    data = request.get_json() or {}
    ids = [int(x) for x in (data.get('album_ids') or []) if str(x).isdigit()]
    delete_files = bool(data.get('delete_files'))
    deleted = batch_delete_albums(ids, delete_files=delete_files)
    return jsonify({'success': True, 'deleted_count': deleted})


@app.route('/api/albums/batch_delete_all', methods=['POST'])
@api_login_required
def api_albums_batch_delete_all():
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    data = request.get_json() or {}
    delete_files = bool(data.get('delete_files'))
    deleted = batch_delete_all_albums(delete_files=delete_files)
    return jsonify({'success': True, 'deleted_count': deleted})


# ---------- 图集图片 API ----------

@app.route('/api/albums/<int:album_id>/images', methods=['POST'])
@api_login_required
def api_album_images_add(album_id):
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    album = get_album(album_id)
    if not album:
        return jsonify({'success': False, 'message': '图集不存在'}), 404
    data = request.get_json() or {}
    items = data.get('items') or []
    image_items = []
    for it in items:
        url = (it.get('image_url') or '').strip()
        if not url:
            continue
        image_items.append({
            'image_url': url,
            'source': it.get('source') or album.get('source', 'openlist'),
            'original_filename': it.get('original_filename') or '',
        })
    inserted = add_album_images(album_id, image_items)
    return jsonify({'success': True, 'inserted': inserted})


@app.route('/api/album_images/<int:image_id>', methods=['DELETE'])
@api_login_required
def api_album_images_delete(image_id):
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    delete_file = request.args.get('delete_file', 'false').lower() == 'true'
    delete_album_image(image_id, delete_file=delete_file)
    return jsonify({'success': True})


@app.route('/api/album_images/batch_delete', methods=['POST'])
@api_login_required
def api_album_images_batch_delete():
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    data = request.get_json() or {}
    ids = [int(x) for x in (data.get('image_ids') or []) if str(x).isdigit()]
    delete_files = bool(data.get('delete_files'))
    deleted = batch_delete_album_images(ids, delete_files=delete_files)
    return jsonify({'success': True, 'deleted_count': deleted})


@app.route('/api/albums/<int:album_id>/images/reorder', methods=['POST'])
@api_login_required
def api_album_images_reorder(album_id):
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    data = request.get_json() or {}
    ordered_ids = _normalize_sort_order_list(data.get('ordered_ids') or data.get('order') or [])
    update_album_images_order(album_id, ordered_ids)
    return jsonify({'success': True})


# ---------- 图片导入 API ----------

@app.route('/api/image_import/progress')
@api_login_required
def api_image_import_progress():
    """图片导入进度（与视频导入共用 _import_progress）"""
    return jsonify({'success': True,
                    'total': _import_progress['total'],
                    'current': _import_progress['current'],
                    'done': _import_progress['done'],
                    'task': _import_progress['task']})


@app.route('/api/image_import/categories', methods=['GET'])
@api_login_required
def api_image_import_categories():
    """以 typecho_web 风格的 {parent_id: [children]} 树返回图集分类。"""
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    cats = get_all_album_categories() or []
    # 构建树：{0: 一级分类, id: 子分类}
    tree = {0: []}
    # 先按 parent_id 分桶
    bucket = {}
    for c in cats:
        bucket.setdefault(c.get('parent_id') or 0, []).append(c)
    # 仅保留有子级的父级
    def has_children(pid):
        for c in bucket.get(pid, []):
            children = bucket.get(c['id'], [])
            if children:
                return True
        return False
    for c in cats:
        c['has_children'] = has_children(c['id'])
    tree[0] = bucket.get(0, [])
    for pid, children in bucket.items():
        if pid:
            tree[pid] = children
    return jsonify({'success': True, 'tree': tree, 'flat': cats})


@app.route('/api/image_import/file_link', methods=['POST'])
@api_login_required
def api_image_import_file_link():
    """获取 OpenList 文件的直链。Body: {account_id, file_path}"""
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    data = request.get_json() or {}
    account_id = int(data.get('account_id') or 0)
    file_path = (data.get('file_path') or '').strip()
    if not file_path:
        return jsonify({'success': False, 'message': 'file_path 必填'}), 400
    accounts = get_all_openlist_accounts()
    account = next((a for a in accounts if a['id'] == account_id), None)
    if not account:
        return jsonify({'success': False, 'message': 'OpenList 账户不存在'}), 400
    api = OpenListApi(account['server_url'], account['username'], account['password'])
    try:
        link = api.get_file_link(file_path)
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取直链失败：{e}'}), 500
    if not link:
        return jsonify({'success': False, 'message': 'OpenList 返回空链接'}), 500
    return jsonify({'success': True, 'link': link})


@app.route('/api/image_import/create', methods=['POST'])
@api_login_required
def api_image_import_create():
    """接收博客式内容（Markdown + 直链），自动提取图片/视频 URL 创建图集。

    Body:
      title: 必填，图集标题
      content: 必填，Markdown 或纯 URL 文本（含图片/视频直链）
      description: 选填
      category_id: 选填，第一个选中的分类
      category_ids: 选填，分类列表（暂用第一个）
      include_videos: 选填，是否将视频也作为独立视频入库
      download_local: 选填，是否下载 OpenList 图片到本地（默认 False，存直链）
      first_as_cover: 选填，是否把首张图作封面（默认 True）
      reverse_order: 选填，是否倒序排列
    """
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    data = request.get_json() or {}
    title = (data.get('title') or '').strip()
    content = (data.get('content') or '').strip()
    if not title or not content:
        return jsonify({'success': False, 'message': 'title 和 content 必填'}), 400

    description = (data.get('description') or '').strip()
    category_id = int(data.get('category_id') or 0)
    include_videos = bool(data.get('include_videos'))
    download_local = bool(data.get('download_local'))
    first_as_cover = bool(data.get('first_as_cover', True))
    reverse_order = bool(data.get('reverse_order'))

    # 1) 从 content 抽取 URL（支持 HTML src/href、Markdown 链接、纯文本 URL）
    urls = _extract_media_urls(content)
    if not urls:
        return jsonify({'success': False, 'message': '未识别到任何图片/视频 URL'}), 400

    image_urls = [u for u in urls if _classify_url(u)[0] == 'image']
    video_urls = [u for u in urls if _classify_url(u)[0] == 'video']
    if not image_urls and not video_urls:
        return jsonify({'success': False, 'message': '没有可用的图片/视频 URL'}), 400

    # 按 typecho extract_sort_key 排序
    image_urls.sort(key=_extract_url_sort_key)
    if reverse_order:
        image_urls = list(reversed(image_urls))
    video_urls.sort(key=_extract_url_sort_key)
    if reverse_order:
        video_urls = list(reversed(video_urls))

    stats = _build_pv_stats(len(image_urls), len(video_urls))
    description = _append_pv_stats_to_description(description, len(image_urls), len(video_urls))

    # 2) 创建图集
    # 来源：优先用前端显式传入的 source；否则 download_local 时视为本地，否则视为 OpenList 远端直链。
    source_val = (data.get('source') or ('local' if download_local else 'openlist')).strip()
    if source_val not in ('openlist', 'local', 'url', 'urls'):
        source_val = 'openlist'
    album_id = create_album({
        'title': title,
        'description': description,
        'category_id': category_id,
        'cover': '',
        'source': source_val,
    })

    # 3) 把图片入库
    album_dir = _make_album_dir(album_id)
    cover_url = ''
    image_items = []

    if download_local:
        # 把 OpenList 直链（或 http url）下载到本地
        total = len(image_urls) + (len(video_urls) if include_videos else 0)
        _set_import_progress(total=total, current=0, done=False, task='image_import_blog')
        try:
            for idx, url in enumerate(image_urls):
                try:
                    safe = _safe_filename(_basename_from_url(url))
                    target_name = f'{idx:03d}_{safe}'
                    target_path = os.path.join(album_dir, target_name)
                    r = requests.get(url, timeout=30)
                    r.raise_for_status()
                    with open(target_path, 'wb') as fp:
                        fp.write(r.content)
                    stored = f'/static/{Config.ALBUM_IMAGE_DIR}/{album_id}/{target_name}'
                except Exception as e:
                    print(f'[image_import_blog] 下载失败 {url}: {e}')
                    # 下载失败则改存直链
                    stored = url
                image_items.append({
                    'image_url': stored,
                    'source': 'openlist',
                    'original_filename': _basename_from_url(url),
                })
                if not cover_url:
                    cover_url = stored
                _set_import_progress(current=idx + 1)
        finally:
            _set_import_progress(done=True)
    else:
        # 纯直链模式：直接记录 URL
        for idx, url in enumerate(image_urls):
            image_items.append({
                'image_url': url,
                'source': 'openlist',
                'original_filename': _basename_from_url(url),
            })
        if image_urls:
            cover_url = image_urls[0]

    if not first_as_cover and len(image_items) > 1:
        cover_url = ''  # 让模型函数自动设置第一张

    if image_items:
        add_album_images(album_id, image_items)
    if cover_url:
        try:
            update_album(album_id, {'cover': cover_url})
        except Exception as e:
            print(f'[image_import_blog] set cover failed: {e}')

    # 4) 视频作为图集媒体入库（不再写入 videos 表；content 中的 URL 已是直链）
    #    与图片共用 album_images 表，靠 media_type='video' 区分；详情页按 media_type 渲染 <video>
    imported_videos = 0
    video_items = []
    if include_videos and video_urls:
        base_idx = len(image_items)
        for j, url in enumerate(video_urls):
            video_items.append({
                'image_url': url,
                'media_type': 'video',
                'source': 'openlist',
                'original_filename': _basename_from_url(url),
                'sort_order': base_idx + j,
            })
            imported_videos += 1
    if video_items:
        try:
            add_album_images(album_id, video_items)
        except Exception as e:
            print(f'[image_import_blog] add album videos failed: {e}')

    return jsonify({
        'success': True,
        'album_id': album_id,
        'images_imported': len(image_items),
        'videos_imported': imported_videos,
        'stats': stats,
    })


@app.route('/api/image_import/browse_local', methods=['POST'])
@api_login_required
def api_image_import_browse_local():
    """列出本地驱动器或目录中的图片文件（用于图片导入选择）。"""
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    data = request.get_json() or {}
    raw_path = (data.get('path') or '').strip()
    include_videos = bool(data.get('include_videos'))
    is_windows = (os.name == 'nt')
    # 跨平台：响应里告知前端该用什么分隔符，避免前端硬编码
    platform_name = 'windows' if is_windows else ('darwin' if sys.platform == 'darwin' else 'linux')
    path_sep = '\\' if is_windows else '/'

    items = []
    breadcrumb = []

    try:
        # === 与 api_local_browse 行为一致：空路径 → 列出"根"内容（Windows 盘符 / POSIX 的 /）===
        # POSIX 空路径：不要返回虚拟根条目（前端会被迫点击两次才能看到文件），
        # 而是直接把 path 设为 '/'，落到下面统一的 scandir 分支列出真实条目
        if not raw_path:
            if is_windows:
                import string
                drives = []
                for letter in string.ascii_uppercase:
                    d = f'{letter}:\\'
                    if os.path.exists(d):
                        drives.append(d)
                for d in drives:
                    items.append({
                        'name': d,
                        'path': d,
                        'is_dir': True,
                        'size': 0,
                    })
                breadcrumb = [{'name': '驱动器', 'path': ''}]
                # Windows 早返回，避免走到下面的 POSIX 分支
                return jsonify({
                    'success': True,
                    'path': '',
                    'items': items,
                    'breadcrumb': breadcrumb,
                    'platform': platform_name,
                    'sep': path_sep,
                })
            # POSIX：直接以 '/' 作为 raw_path，落到下面的 scandir 列出真实条目
            raw_path = '/'
            breadcrumb = [{'name': '/', 'path': '/'}]

        # 规范化并校验（与 api_local_browse 完全一致）
        target = os.path.normpath(raw_path)
        if not os.path.exists(target):
            return jsonify({'success': False, 'message': '路径不存在: ' + target}), 400
        if not os.path.isdir(target):
            return jsonify({'success': False, 'message': '不是目录: ' + target}), 400

        # 列出子目录 + 图片文件（统一用 entry.path，与 api_local_browse 一致）
        try:
            with os.scandir(target) as it:
                for entry in it:
                    try:
                        if entry.is_dir():
                            items.append({
                                'name': entry.name,
                                'path': entry.path,
                                'is_dir': True,
                                'size': 0,
                            })
                        elif entry.is_file():
                            ext = os.path.splitext(entry.name)[1].lower()
                            is_image = ext in _LOCAL_IMAGE_EXTENSIONS
                            is_video = ext in _LOCAL_VIDEO_EXTENSIONS
                            if is_image or (include_videos and is_video):
                                try:
                                    size = entry.stat().st_size
                                except OSError:
                                    size = 0
                                items.append({
                                    'name': entry.name,
                                    'path': entry.path,
                                    'is_dir': False,
                                    'size': size,
                                    'is_image': is_image,
                                    'is_video': is_video,
                                })
                    except (PermissionError, OSError):
                        # 与 api_local_browse 一致：跳过无权访问的单个 entry，继续下一个
                        continue
        except PermissionError:
            return jsonify({'success': False, 'message': '无权限访问此目录'}), 403
        except OSError as e:
            return jsonify({'success': False, 'message': '读取目录失败: ' + str(e)}), 500

        items.sort(key=lambda x: (not x.get('is_dir', False), _natural_sort_key(x.get('name', ''))))

        # 面包屑：按响应 sep 拼（Windows 用 \，POSIX 用 /）
        # POSIX 根路径（target == '/'）时不再追加 —— line 3884 已经初始化了一项 [{name:'/', path:'/'}]
        norm = target.replace('\\', '/').rstrip('/')
        parts = [p for p in norm.split('/') if p]
        if is_windows and len(parts) >= 1:
            acc = parts[0]
            breadcrumb.append({'name': acc, 'path': acc + path_sep})
            for p in parts[1:]:
                acc = (acc + '/' + p).replace('//', '/')
                breadcrumb.append({'name': p, 'path': acc + ('\\' if is_windows else '')})
        elif not is_windows and target != '/':
            breadcrumb.append({'name': '/', 'path': '/'})
            acc = ''
            for p in parts:
                acc = acc + '/' + p
                breadcrumb.append({'name': p, 'path': acc})
    except PermissionError:
        return jsonify({'success': False, 'message': '无权限访问该目录'}), 403
    except Exception as e:
        return jsonify({'success': False, 'message': f'读取失败：{e}'}), 500

    return jsonify({
        'success': True,
        'path': raw_path,
        'items': items,
        'breadcrumb': breadcrumb,
        'platform': platform_name,   # 'windows' | 'linux' | 'darwin'
        'sep': path_sep,             # '\\' | '/'
    })


@app.route('/api/image_import/browse_openlist', methods=['POST'])
@api_login_required
def api_image_import_browse_openlist():
    """列出 OpenList 目录中的图片文件（用于图片导入选择）。"""
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    data = request.get_json() or {}
    account_id = int(data.get('account_id') or 0)
    raw_path = (data.get('path') or '/').strip()
    include_videos = bool(data.get('include_videos'))

    accounts = get_all_openlist_accounts()
    account = next((a for a in accounts if a['id'] == account_id), None)
    if not account:
        return jsonify({'success': False, 'message': 'OpenList 账户不存在'}), 400

    api = OpenListApi(account['server_url'], account['username'], account['password'])
    try:
        api.login()
    except Exception as e:
        return jsonify({'success': False, 'message': f'OpenList 登录失败：{e}'}), 500

    try:
        file_list = api.get_file_list(raw_path) or []
    except Exception as e:
        return jsonify({'success': False, 'message': f'读取目录失败：{e}'}), 500

    items = []
    for f in file_list:
        name = f.get('name', '')
        is_dir = bool(f.get('is_dir'))
        ext = os.path.splitext(name)[1].lower()
        if is_dir:
            items.append({
                'name': name,
                'path': (f.get('path') or raw_path).rstrip('/') + '/' + name,
                'is_dir': True,
                'size': 0,
            })
        else:
            is_image = ext in _OPENLIST_IMAGE_EXTENSIONS
            is_video = ext in {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.m3u8', '.flv'}
            if is_image or (include_videos and is_video):
                items.append({
                    'name': name,
                    'path': (f.get('path') or raw_path).rstrip('/') + '/' + name,
                    'is_dir': False,
                    'size': f.get('size', 0),
                    'is_image': is_image,
                    'is_video': is_video,
                })
    items.sort(key=lambda x: (not x.get('is_dir', False), _natural_sort_key(x.get('name', ''))))

    # 面包屑
    norm = (raw_path or '/').replace('//', '/').rstrip('/') or '/'
    parts = [p for p in norm.split('/') if p]
    breadcrumb = [{'name': '根目录', 'path': '/'}]
    acc = ''
    for p in parts:
        acc = acc + '/' + p
        breadcrumb.append({'name': p, 'path': acc})

    return jsonify({'success': True, 'items': items, 'breadcrumb': breadcrumb})


@app.route('/api/image_import/import_local', methods=['POST'])
@api_login_required
def api_image_import_local():
    """本地图片导入：把指定路径下的图片批量入库为一个新图集。

    Body:
      folder_path: 必填，本地目录绝对路径
      album_title: 必填，图集标题
      category_id: 选填，图集分类
      description: 选填
      include_videos: 选填，是否将目录中的视频也作为视频入库（非图集）
    """
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    data = request.get_json() or {}
    folder_path = (data.get('folder_path') or '').strip()
    album_title = (data.get('album_title') or '').strip()
    if not folder_path or not album_title:
        return jsonify({'success': False, 'message': '目录路径与图集标题必填'})
    if not os.path.isdir(folder_path):
        return jsonify({'success': False, 'message': f'目录不存在：{folder_path}'})
    category_id = int(data.get('category_id') or 0)
    description = (data.get('description') or '').strip()
    include_videos = bool(data.get('include_videos'))

    # 1. 扫描目录
    image_files = []
    video_files = []
    try:
        with os.scandir(folder_path) as it:
            for entry in it:
                if entry.is_file():
                    ext = os.path.splitext(entry.name)[1].lower()
                    if ext in _LOCAL_IMAGE_EXTENSIONS:
                        image_files.append(entry)
                    elif include_videos and ext in _LOCAL_VIDEO_EXTENSIONS:
                        video_files.append(entry)
    except PermissionError:
        return jsonify({'success': False, 'message': '无权限读取目录'}), 403

    image_files.sort(key=lambda e: _natural_sort_key(e.name))
    video_files.sort(key=lambda e: _natural_sort_key(e.name))

    if not image_files and not video_files:
        return jsonify({'success': False, 'message': '目录下没有可导入的图片/视频'})

    description = _append_pv_stats_to_description(description, len(image_files), len(video_files))

    # 2. 创建图集
    album_id = create_album({
        'title': album_title,
        'description': description,
        'category_id': category_id,
        'cover': '',
        'source': 'local',
    })

    # 3. 复制图片到 static/album_images/<album_id>/
    album_dir = _make_album_dir(album_id)
    image_items = []
    cover_url = ''
    _set_import_progress(total=len(image_files) + len(video_files),
                         current=0, done=False, task='image_import_local')
    seq = 0
    try:
        for idx, entry in enumerate(image_files):
            safe = _safe_filename(entry.name)
            target_name = f'{seq:03d}_{safe}'
            target_path = os.path.join(album_dir, target_name)
            try:
                shutil.copy2(entry.path, target_path)
            except Exception as e:
                print(f'[image_import_local] 复制失败 {entry.path}: {e}')
                continue
            url = f'/static/{Config.ALBUM_IMAGE_DIR}/{album_id}/{target_name}'
            image_items.append({
                'image_url': url,
                'source': 'local',
                'original_filename': entry.name,
            })
            if not cover_url:
                cover_url = url
            seq += 1
            _set_import_progress(current=idx + 1)

        inserted = add_album_images(album_id, image_items)
        if cover_url:
            update_album(album_id, {'cover': cover_url})

        # 4. 可选：把视频作为图集媒体入库（拷贝到 album_dir，作为 album_images media_type='video' 行；
        #    不再写入 videos 表，避免污染长视频库；详情页可直接 <video src=...mp4> 播放）
        imported_videos = 0
        video_items = []
        base_idx = len(image_items)
        for j, entry in enumerate(video_files):
            safe = _safe_filename(entry.name)
            target_name = f'{base_idx + j:03d}_{safe}'
            target_path = os.path.join(album_dir, target_name)
            try:
                shutil.copy2(entry.path, target_path)
            except Exception as e:
                print(f'[image_import_local] 复制视频失败 {entry.path}: {e}')
                _set_import_progress(current=len(image_files) + j + 1)
                continue
            url = f'/static/{Config.ALBUM_IMAGE_DIR}/{album_id}/{target_name}'
            video_items.append({
                'image_url': url,
                'media_type': 'video',
                'source': 'local',
                'original_filename': entry.name,
                'sort_order': base_idx + j,
            })
            imported_videos += 1
            _set_import_progress(current=len(image_files) + j + 1)

        if video_items:
            try:
                add_album_images(album_id, video_items)
            except Exception as e:
                print(f'[image_import_local] add album videos failed: {e}')

        _set_import_progress(done=True)
        return jsonify({'success': True,
                        'album_id': album_id,
                        'images_imported': inserted,
                        'videos_imported': imported_videos})
    except Exception as e:
        _set_import_progress(done=True)
        return jsonify({'success': False, 'message': f'导入失败：{e}'})


@app.route('/api/image_import/import_openlist', methods=['POST'])
@api_login_required
def api_image_import_openlist():
    """OpenList 图片导入：把 OpenList 目录下的图片批量入库为一个新图集。"""
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    data = request.get_json() or {}
    account_id = int(data.get('account_id') or 0)
    folder_path = (data.get('folder_path') or '').strip()
    album_title = (data.get('album_title') or '').strip()
    if not account_id or not folder_path or not album_title:
        return jsonify({'success': False, 'message': '账户、路径、图集标题必填'})
    category_id = int(data.get('category_id') or 0)
    description = (data.get('description') or '').strip()
    include_videos = bool(data.get('include_videos'))

    accounts = get_all_openlist_accounts()
    account = next((a for a in accounts if a['id'] == account_id), None)
    if not account:
        return jsonify({'success': False, 'message': 'OpenList 账户不存在'}), 400

    api = OpenListApi(account['server_url'], account['username'], account['password'])
    try:
        api.login()
    except Exception as e:
        return jsonify({'success': False, 'message': f'OpenList 登录失败：{e}'}), 500

    try:
        file_list = api.get_file_list(folder_path) or []
    except Exception as e:
        return jsonify({'success': False, 'message': f'读取目录失败：{e}'}), 500

    image_files = []
    video_files = []
    for f in file_list:
        if f.get('is_dir'):
            continue
        name = f.get('name', '')
        ext = os.path.splitext(name)[1].lower()
        full_path = (f.get('path') or folder_path).rstrip('/') + '/' + name
        if ext in _OPENLIST_IMAGE_EXTENSIONS:
            image_files.append({'name': name, 'path': full_path})
        elif include_videos and ext in {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.m3u8', '.flv'}:
            video_files.append({'name': name, 'path': full_path})
    image_files.sort(key=lambda x: _natural_sort_key(x['name']))
    video_files.sort(key=lambda x: _natural_sort_key(x['name']))

    if not image_files and not video_files:
        return jsonify({'success': False, 'message': '目录下没有可导入的图片/视频'})

    description = _append_pv_stats_to_description(description, len(image_files), len(video_files))

    album_id = create_album({
        'title': album_title,
        'description': description,
        'category_id': category_id,
        'cover': '',
        'source': 'openlist',
    })

    _set_import_progress(total=len(image_files) + len(video_files),
                         current=0, done=False, task='image_import_openlist')
    image_items = []
    cover_url = ''
    try:
        for idx, f in enumerate(image_files):
            try:
                url = api.get_file_link(f['path'])
            except Exception:
                continue
            image_items.append({
                'image_url': url,
                'source': 'openlist',
                'original_filename': f['name'],
            })
            if not cover_url:
                cover_url = url
            _set_import_progress(current=idx + 1)

        inserted = add_album_images(album_id, image_items)
        if cover_url:
            update_album(album_id, {'cover': cover_url})

        # 5. 可选：把视频作为图集媒体入库（走 api.get_file_link() 转直链后写入 album_images media_type='video'；
        #    不再写入 videos 表，避免污染长视频库；详情页可直接 <video src=直链> 播放）
        imported_videos = 0
        video_items = []
        for j, f in enumerate(video_files):
            try:
                url = api.get_file_link(f['path'])
            except Exception:
                _set_import_progress(current=len(image_files) + j + 1)
                continue
            video_items.append({
                'image_url': url,
                'media_type': 'video',
                'source': 'openlist',
                'original_filename': f['name'],
                'sort_order': len(image_files) + j,
            })
            imported_videos += 1
            _set_import_progress(current=len(image_files) + j + 1)

        if video_items:
            try:
                add_album_images(album_id, video_items)
            except Exception as e:
                print(f'[image_import_openlist] add album videos failed: {e}')

        _set_import_progress(done=True)
        return jsonify({'success': True,
                        'album_id': album_id,
                        'images_imported': inserted,
                        'videos_imported': imported_videos})
    except Exception as e:
        _set_import_progress(done=True)
        return jsonify({'success': False, 'message': f'导入失败：{e}'})


# ---------- URL 批量导入（typecho_web 风格的 zylj.txt 工作流） ----------
@app.route('/api/image_import/preview_urls', methods=['POST'])
@api_login_required
def api_image_import_preview_urls():
    """预览一批 URL 的分类：识别图片/视频数量与首张封面，返回统计信息。

    Body:
      urls: 必填，字符串（多行）或 list
      filename: 可选，若提供则尝试从磁盘读取该 .txt 文件
    """
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    data = request.get_json() or {}
    urls_text = data.get('urls') or ''
    filename = (data.get('filename') or '').strip()

    # 1) 若指定 filename，先读文件内容（再叠加 urls）
    if filename and os.path.isfile(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                urls_text = (urls_text + '\n' + f.read()) if urls_text else f.read()
        except Exception as e:
            return jsonify({'success': False, 'message': f'读取文件失败：{e}'}), 400

    parsed = _parse_url_lines(urls_text)
    if not parsed:
        return jsonify({'success': False, 'message': '没有解析到任何 URL，请粘贴或上传 URL 列表'}), 400

    image_urls, video_urls = [], []
    skipped = []
    for u in parsed:
        kind, ext, path = _classify_url(u)
        if kind == 'image':
            image_urls.append({'url': u, 'ext': ext, 'name': os.path.basename(path or u)})
        elif kind == 'video':
            video_urls.append({'url': u, 'ext': ext, 'name': os.path.basename(path or u)})
        else:
            skipped.append({'url': u, 'ext': ext})

    # 按 typecho_web 风格的 extract_sort_key 排序
    image_urls.sort(key=lambda x: _extract_url_sort_key(x['url']))
    video_urls.sort(key=lambda x: _extract_url_sort_key(x['url']))

    return jsonify({
        'success': True,
        'total_urls': len(parsed),
        'image_count': len(image_urls),
        'video_count': len(video_urls),
        'skipped_count': len(skipped),
        'stats': _build_pv_stats(len(image_urls), len(video_urls)),
        'first_image_url': image_urls[0]['url'] if image_urls else '',
        'image_urls': image_urls,
        'video_urls': video_urls,
        'skipped': skipped,
    })


@app.route('/api/image_import/from_urls', methods=['POST'])
@api_login_required
def api_image_import_from_urls():
    """从 URL 列表批量导入为一个新图集（typecho_web 风格）。

    Body:
      urls: 必填，字符串（多行）或 list
      album_title: 必填
      category_id: 可选
      description: 可选
      include_videos: bool，是否把视频作为视频入库（非图集）
      filename: 可选，文件路径（与 urls 二选一）
    """
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'message': '需要管理员权限'}), 403
    data = request.get_json() or {}
    urls_text = data.get('urls') or ''
    filename = (data.get('filename') or '').strip()
    album_title = (data.get('album_title') or '').strip()

    if filename and os.path.isfile(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                urls_text = (urls_text + '\n' + f.read()) if urls_text else f.read()
        except Exception as e:
            return jsonify({'success': False, 'message': f'读取文件失败：{e}'}), 400

    parsed = _parse_url_lines(urls_text)
    if not parsed:
        return jsonify({'success': False, 'message': '没有解析到任何 URL'}), 400
    if not album_title:
        return jsonify({'success': False, 'message': '请填写图集标题'}), 400

    category_id = int(data.get('category_id') or 0)
    description = (data.get('description') or '').strip()
    include_videos = bool(data.get('include_videos'))

    image_urls, video_urls = [], []
    for u in parsed:
        kind, ext, path = _classify_url(u)
        if kind == 'image':
            image_urls.append({'url': u, 'name': os.path.basename(path or u)})
        elif kind == 'video':
            video_urls.append({'url': u, 'name': os.path.basename(path or u)})
    image_urls.sort(key=lambda x: _extract_url_sort_key(x['url']))
    video_urls.sort(key=lambda x: _extract_url_sort_key(x['url']))

    if not image_urls and not video_urls:
        return jsonify({'success': False, 'message': 'URL 列表中没有可识别的图片或视频'}), 400

    # 写 typecho_web 风格的 [NP MV] 统计到 description
    description = _append_pv_stats_to_description(description, len(image_urls), len(video_urls))

    album_id = create_album({
        'title': album_title,
        'description': description,
        'category_id': category_id,
        'cover': image_urls[0]['url'] if image_urls else '',
        'source': 'urls',
    })

    _set_import_progress(total=len(image_urls) + len(video_urls),
                         current=0, done=False, task='image_import_urls')
    image_items = []
    try:
        for idx, item in enumerate(image_urls):
            image_items.append({
                'image_url': item['url'],
                'source': 'urls',
                'original_filename': item['name'],
            })
            _set_import_progress(current=idx + 1)

        inserted = add_album_images(album_id, image_items)
        cover_url = image_urls[0]['url'] if image_urls else ''
        if cover_url:
            update_album(album_id, {'cover': cover_url})

        # 视频作为图集媒体入库（直链原样入库，不再调 create_video）
        imported_videos = 0
        video_items = []
        for j, item in enumerate(video_urls):
            video_items.append({
                'image_url': item['url'],
                'media_type': 'video',
                'source': 'openlist',
                'original_filename': item['name'],
                'sort_order': len(image_urls) + j,
            })
            imported_videos += 1
            _set_import_progress(current=len(image_urls) + j + 1)

        if video_items:
            try:
                add_album_images(album_id, video_items)
            except Exception as e:
                print(f'[image_import_from_urls] add album videos failed: {e}')

        _set_import_progress(done=True)
        return jsonify({
            'success': True,
            'album_id': album_id,
            'images_imported': inserted,
            'videos_imported': imported_videos,
            'stats': _build_pv_stats(len(image_urls), len(video_urls)),
        })
    except Exception as e:
        _set_import_progress(done=True)
        return jsonify({'success': False, 'message': f'导入失败：{e}'})


def _extract_url_sort_key(url):
    """仿 typecho_web extract_sort_key：优先 (NN)，其次文件名前缀数字，最后 inf。"""
    try:
        path = unquote(urlparse(url).path)
        filename = os.path.basename(path)
        m = re.search(r'\((\d+)\)', filename)
        if m:
            return int(m.group(1))
        stem = os.path.splitext(filename)[0]
        nums = re.findall(r'\d+', stem)
        if nums:
            return int(nums[-1][:6])
    except Exception:
        pass
    return float('inf')


# ---------- v1 图集 API（供 APP 调用，遵循现有 v1 API 风格：免鉴权/可选 Basic Auth） ----------

def _album_to_dict(a, with_cover_abs=True):
    """图集记录转为 API 输出字典（图片绝对 URL）"""
    if not a:
        return None
    cover = a.get('cover') or ''
    if with_cover_abs and cover and not cover.startswith(('http://', 'https://')):
        cover = _abs_url(cover)
    return {
        'id': a['id'],
        'title': a.get('title', ''),
        'description': a.get('description', ''),
        'category_id': a.get('category_id', 0),
        'cover': cover,
        'image_count': a.get('image_count', 0),
        'views': a.get('views', 0),
        'source': a.get('source', 'openlist'),
        'created_at': a.get('created_at', ''),
        'updated_at': a.get('updated_at', ''),
    }


@app.route('/api/v1/album_categories')
def api_v1_album_categories():
    """获取图集分类树。带 Basic Auth 且有图集权限时仅返回允许的分类，否则返回全部。"""
    cats = get_all_album_categories()
    uid = _get_current_user_id()
    allowed_ids = get_user_allowed_category_ids(uid, 'album') if uid else None
    if allowed_ids is not None:
        cats = [c for c in cats if c['id'] in allowed_ids]
    cat_map = {c['id']: {**c, 'children': []} for c in cats}
    tree = []
    for c in cats:
        pid = c.get('parent_id', 0)
        if pid and pid in cat_map:
            cat_map[pid]['children'].append(cat_map[c['id']])
        else:
            tree.append(cat_map[c['id']])
    return jsonify({'success': True, 'categories': tree})


@app.route('/api/v1/albums')
def api_v1_albums():
    """图集列表。带 Basic Auth 且有图集权限时仅返回允许分类下的图集，否则返回全部。
    参数: page, per_page, category_id, q
    """
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 500)
    category_id = request.args.get('category_id', 0, type=int)
    keyword = request.args.get('q', '').strip()
    uid = _get_current_user_id()
    allowed_ids = get_user_allowed_category_ids(uid, 'album') if uid else None
    # 有权限限制：分类参数必须落于权限内，否则回退到权限范围过滤
    if allowed_ids is not None:
        if category_id and category_id not in allowed_ids:
            category_id = 0
        if category_id:
            result = get_all_albums(category_id=category_id, keyword=keyword, page=page, per_page=per_page)
        else:
            result = get_all_albums(keyword=keyword, page=page, per_page=per_page, category_ids=allowed_ids)
    else:
        result = get_all_albums(category_id=category_id, keyword=keyword, page=page, per_page=per_page)
    albums = [_album_to_dict(a) for a in result['albums']]
    return jsonify({
        'success': True,
        'albums': albums,
        'total': result['total'],
        'page': result['page'],
        'per_page': result['per_page'],
        'total_pages': result['total_pages'],
    })


@app.route('/api/v1/albums/<int:album_id>')
def api_v1_album_detail(album_id):
    """图集详情（含图片列表）。带 Basic Auth 且有图集权限时校验是否可访问。"""
    album = get_album(album_id)
    if not album:
        return jsonify({'success': False, 'message': '图集不存在'}), 404
    uid = _get_current_user_id()
    allowed_ids = get_user_allowed_category_ids(uid, 'album') if uid else None
    if allowed_ids is not None and album.get('category_id') not in allowed_ids:
        return jsonify({'success': False, 'message': '无权限访问该图集'}), 403
    images = get_album_images(album_id)
    # 图片 URL 绝对化
    for img in images:
        url = img.get('image_url') or ''
        if url and not url.startswith(('http://', 'https://')):
            img['image_url'] = _abs_url(url)
    increment_album_views(album_id)
    album['views'] = album.get('views', 0) + 1
    return jsonify({
        'success': True,
        'album': _album_to_dict(album),
        'images': images,
    })


@app.route('/api/v1/albums/<int:album_id>/images')
def api_v1_album_images(album_id):
    """仅返回图片列表（APP 分页/懒加载用）。带 Basic Auth 且有图集权限时校验。"""
    album = get_album(album_id)
    if not album:
        return jsonify({'success': False, 'message': '图集不存在'}), 404
    uid = _get_current_user_id()
    allowed_ids = get_user_allowed_category_ids(uid, 'album') if uid else None
    if allowed_ids is not None and album.get('category_id') not in allowed_ids:
        return jsonify({'success': False, 'message': '无权限访问该图集'}), 403
    images = get_album_images(album_id)
    for img in images:
        url = img.get('image_url') or ''
        if url and not url.startswith(('http://', 'https://')):
            img['image_url'] = _abs_url(url)
    return jsonify({'success': True, 'images': images, 'total': len(images)})


@app.route('/api/v1/album_import', methods=['POST'])
def api_v1_album_import():
    """从 URL 列表批量创建一个新图集（公开，APP 调用）。

    Body (JSON or form):
      urls: 必填，list 或字符串（多行）。也可传 filename 指定服务端 .txt 文件读取
      album_title: 必填
      category_id: 可选
      description: 可选
      include_videos: bool，是否把视频也作为视频入库
    """
    # 内部鉴权（v1 模式：缺鉴权直接 401）
    uid = _get_current_user_id()
    if not uid:
        return jsonify({'success': False, 'error': '需要登录', 'code': 'UNAUTHORIZED'}), 401
    if session.get('user_role') != 'admin':
        return jsonify({'success': False, 'error': '需要管理员权限', 'code': 'FORBIDDEN'}), 403

    # JSON / form 兼容
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    urls_text = data.get('urls') or ''
    if isinstance(urls_text, list):
        urls_text = '\n'.join([str(x) for x in urls_text])
    filename = (data.get('filename') or '').strip()
    album_title = (data.get('album_title') or '').strip()
    if filename and os.path.isfile(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                urls_text = (urls_text + '\n' + f.read()) if urls_text else f.read()
        except Exception as e:
            return jsonify({'success': False, 'message': f'读取文件失败：{e}'}), 400

    parsed = _parse_url_lines(urls_text)
    if not parsed:
        return jsonify({'success': False, 'message': '没有解析到任何 URL'}), 400
    if not album_title:
        return jsonify({'success': False, 'message': '请填写图集标题'}), 400

    category_id = int(data.get('category_id') or 0)
    description = (data.get('description') or '').strip()
    include_videos = bool(data.get('include_videos') in (True, 'true', '1', 1, 'on'))

    image_urls, video_urls = [], []
    for u in parsed:
        kind, ext, path = _classify_url(u)
        if kind == 'image':
            image_urls.append({'url': u, 'name': os.path.basename(path or u)})
        elif kind == 'video':
            video_urls.append({'url': u, 'name': os.path.basename(path or u)})
    image_urls.sort(key=lambda x: _extract_url_sort_key(x['url']))
    video_urls.sort(key=lambda x: _extract_url_sort_key(x['url']))

    if not image_urls and not video_urls:
        return jsonify({'success': False, 'message': 'URL 列表中没有可识别的图片或视频'}), 400

    description = _append_pv_stats_to_description(description, len(image_urls), len(video_urls))
    album_id = create_album({
        'title': album_title,
        'description': description,
        'category_id': category_id,
        'cover': image_urls[0]['url'] if image_urls else '',
        'source': 'urls',
    })

    image_items = [{
        'image_url': x['url'],
        'source': 'urls',
        'original_filename': x['name'],
    } for x in image_urls]
    inserted = add_album_images(album_id, image_items)

    # 视频作为图集媒体入库（不再写入 videos 表；直链原样入库）
    imported_videos = 0
    video_items = []
    if include_videos:
        for j, item in enumerate(video_urls):
            video_items.append({
                'image_url': item['url'],
                'media_type': 'video',
                'source': 'openlist',
                'original_filename': item['name'],
                'sort_order': len(image_urls) + j,
            })
            imported_videos += 1

    if video_items:
        try:
            add_album_images(album_id, video_items)
        except Exception as e:
            print(f'[api_v1_album_import] add album videos failed: {e}')

    return jsonify({
        'success': True,
        'album_id': album_id,
        'images_imported': inserted,
        'videos_imported': imported_videos,
        'stats': _build_pv_stats(len(image_urls), len(video_urls)),
        'album': _album_to_dict(get_album(album_id)) if inserted else None,
    })


# ===================== 开放API接口（供APP调用） =====================

def _abs_url(path):
    """将相对路径转为绝对URL，供APP跨设备访问本机流式资源。

    本地导入的视频/封面在库中存为相对路径（如 /local_video/3、/local_cover/3），
    同设备浏览器能自动补全为 http://127.0.0.1:3090/...，但局域网内其它设备的
    APP 拿到相对路径无法解析主机。APP 调用本接口时 request.host_url 即为 APP
    实际可达的服务器地址（如 http://192.168.x.x:3090/），据此拼接即可。
    已是绝对URL（OpenList/直链）或空值则原样返回。
    """
    if not path:
        return path
    if path.startswith(('http://', 'https://')):
        return path
    try:
        return request.host_url.rstrip('/') + path
    except RuntimeError:
        # 非请求上下文（如脚本/测试调用）下保持原值
        return path


def _filter_categories_by_allowed_ids(categories, allow_set):
    """按允许的分类ID集合裁剪分类列表（含父子级的"父类若空则保留子类"语义）。

    规则：
    - 父分类在白名单 → 整组（包括所有子孙）保留，即便子孙分类自身不在白名单
    - 子分类在白名单但父不在 → 补回父链（即使用户没选父）
    - 完全不沾边 → 丢弃

    返回：清洗后的分类列表（包含被保留的合法父链）。
    """
    if not categories:
        return []
    sorted_cats = sorted(categories, key=lambda c: (c.get('parent_id', 0), c.get('id', 0)))
    kept = []
    seen_ids = set()
    children_by_parent = {}
    for c in sorted_cats:
        pid = c.get('parent_id', 0)
        children_by_parent.setdefault(pid, []).append(c)

    def keep_branch(parent_id):
        """递归保留 parent_id 整棵子树，父已在 seen_ids 内时调用。"""
        for child in children_by_parent.get(parent_id, []):
            if child['id'] in seen_ids:
                continue
            seen_ids.add(child['id'])
            kept.append(child)
            keep_branch(child['id'])  # 子孙一律保留（不论子是否在白名单）

    # 第一步：白名单里的顶级分类 → 整组保留
    top_in_allow = [c for c in children_by_parent.get(0, []) if c['id'] in allow_set]
    for c in top_in_allow:
        if c['id'] in seen_ids:
            continue
        seen_ids.add(c['id'])
        kept.append(c)
        keep_branch(c['id'])

    # 第二步：白名单里出现的非顶级分类 → 补回完整父链（即便祖先不在白名单）
    by_id = {c['id']: c for c in sorted_cats}
    for cat_id in list(allow_set):
        if cat_id in seen_ids:
            continue
        c = by_id.get(cat_id)
        if not c or c['id'] in seen_ids:
            continue
        # 收集完整父链：从 cat_id 一路走到顶层
        chain = []
        cur = c
        while cur:
            chain.append(cur)
            if not cur.get('parent_id', 0):
                break
            cur = by_id.get(cur.get('parent_id', 0))
        # 逆序加入（父 → 子），不在 seen_ids 才入
        for node in reversed(chain):
            if node['id'] in seen_ids:
                continue
            seen_ids.add(node['id'])
            kept.append(node)
            keep_branch(node['id'])
    return kept


def _expand_allowed_to_all_descendants(category_ids):
    """把白名单分类 ID 扩展为"自身 + 所有子分类 ID"集合（用于 video 列表 IN 过滤）。

    用户允许"视频A"父分类时，应当也能看到 videoA-子 分类下的视频。
    """
    if not category_ids:
        return []
    all_cats = get_all_categories()
    children_by_parent = {}
    for c in all_cats:
        children_by_parent.setdefault(c.get('parent_id', 0), []).append(c['id'])
    expanded = set(category_ids)
    stack = list(category_ids)
    while stack:
        pid = stack.pop()
        for child in children_by_parent.get(pid, []):
            if child not in expanded:
                expanded.add(child)
                stack.append(child)
    return list(expanded)


def _video_to_dict(v):
    """将视频记录转为API输出字典，隐藏内部字段"""
    if not v:
        return None
    return {
        'id': v['id'],
        'title': v.get('title', ''),
        'description': v.get('description', ''),
        'cover': _abs_url(v.get('cover', '')),
        'video_url': _abs_url(v.get('video_url', '')),
        'video_type': v.get('video_type', ''),
        'category_id': v.get('category_id', 0),
        'series_id': v.get('series_id'),
        'episode_number': v.get('episode_number', 0),
        'is_series': v.get('is_series', 0),
        'is_short_video': v.get('is_short_video', 0),
        'genre': v.get('genre', ''),
        'rating': v.get('rating', 0),
        'year': v.get('year', ''),
        'actors': v.get('actors', ''),
        'views': v.get('views', 0),
        'duration': v.get('duration', 0),
        'source': v.get('source', 'openlist'),
    }

@app.route('/api/v1/categories')
def api_v1_categories():
    """获取分类树（含父子层级）。若用户已登录且设置了 normal 权限白名单，按其裁剪。"""
    categories = get_all_categories()
    # 用户权限裁剪（未登录 → 全量）
    uid = _get_current_user_id()
    allowed_ids = get_user_allowed_category_ids(uid, 'normal') if uid else None
    if allowed_ids is not None:
        allow_set = set(allowed_ids)
        # 当父分类被禁，保留其子分类中允许的（避免子项消失）；子项全被禁则父分类也不显示
        categories = _filter_categories_by_allowed_ids(categories, allow_set)
    # 构建树形结构
    cat_map = {c['id']: {**c, 'children': []} for c in categories}
    tree = []
    for c in categories:
        pid = c.get('parent_id', 0)
        if pid and pid in cat_map:
            cat_map[pid]['children'].append(cat_map[c['id']])
        else:
            tree.append(cat_map[c['id']])
    return jsonify({'success': True, 'categories': tree})

@app.route('/api/v1/videos')
def api_v1_videos():
    """获取视频列表（首页全部视频，排除系列分集和短视频）

    参数:
      page: 页码 (默认1)
      per_page: 每页数量 (默认20, 最大500)
      category_id: 分类ID筛选
      keyword: 搜索关键词

    权限：登录用户若设置了 normal 分类白名单，则只返回白名单内分类的视频。
          未登录或未设置（None）= 全部可见。
    """
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 500)
    category_id = request.args.get('category_id', 0, type=int)
    keyword = request.args.get('q', '').strip()

    # 权限裁剪（父分类被允许时，子分类视频自动包含）
    uid = _get_current_user_id()
    allowed_ids = get_user_allowed_category_ids(uid, 'normal') if uid else None
    effective_category_id = category_id
    final_category_ids = None
    if allowed_ids is not None:
        if category_id and category_id not in set(allowed_ids):
            effective_category_id = 0
        if not effective_category_id:
            # 扩到所有子孙分类
            final_category_ids = _expand_allowed_to_all_descendants(allowed_ids)

    if keyword:
        result = get_all_videos(keyword=keyword, page=page, per_page=per_page,
                                exclude_series_episodes=True, is_short_video=False,
                                category_id=effective_category_id, category_ids=final_category_ids)
    else:
        result = get_all_videos(category_id=effective_category_id, page=page, per_page=per_page,
                                exclude_series_episodes=True, is_short_video=False,
                                category_ids=final_category_ids)

    videos = [_video_to_dict(v) for v in result['videos']]
    return jsonify({
        'success': True,
        'videos': videos,
        'total': result['total'],
        'page': result['page'],
        'per_page': result['per_page'],
        'total_pages': result['total_pages']
    })

@app.route('/api/v1/videos/<int:video_id>')
def api_v1_video_detail(video_id):
    """获取视频详情。权限：登录用户若设置了 normal 分类白名单，仅允许白名单内分类。"""
    video = get_video(video_id)
    if not video:
        return jsonify({'success': False, 'message': '视频不存在'}), 404
    # 权限校验（normal 分类白名单）
    uid = _get_current_user_id()
    if uid is not None:
        allowed_ids = get_user_allowed_category_ids(uid, 'normal')
        if allowed_ids is not None and video.get('category_id', 0) not in set(allowed_ids):
            return jsonify({'success': False, 'message': '无权限访问该视频'}), 403
    increment_views(video_id)
    return jsonify({'success': True, 'video': _video_to_dict(video)})

# ================= v1 短视频播放标记接口（APP 配套） =================

@app.route('/api/v1/shorts/<int:video_id>/play', methods=['POST'])
def api_v1_short_play(video_id):
    """[APP 专用] 标记短视频为已播放，同时 views+1。

    返回的 played.reset=True 表示所有短视频都已播放完毕，后端已自动清空标记。
    APP 在下次拉取列表时将重新得到全部视频。
    """
    video = get_video(video_id)
    if not video or not video.get('is_short_video'):
        return jsonify({'success': False, 'message': '短视频不存在'}), 404
    increment_views(video_id)
    uid = _get_current_user_id()
    marked, reset, played_cnt, total_cnt = mark_short_played(video_id, user_id=uid)
    return jsonify({
        'success': True,
        'views': (video.get('views', 0) or 0) + 1,
        'played': {
            'marked': marked,
            'reset': reset,
            'played_count': played_cnt,
            'total_count': total_cnt,
        }
    })

@app.route('/api/v1/shorts/played')
def api_v1_short_played_status():
    """[APP 专用] 获取短视频播放状态。

    参数:
      category_id: 0或不传=全部, 其它=指定短分类
    返回:
      played_ids:       已播放ID列表，APP 随机时可本地过滤
      unplayed_ids:     未播放ID列表
      played_count / unplayed_count / total_count
    """
    category_id = request.args.get('category_id', type=int)
    uid = _get_current_user_id()
    # 获取用户可访问的短视频分类权限
    allowed_ids = get_user_allowed_category_ids(uid, 'short') if uid else None
    # 仅在"全部"请求时按权限过滤
    allowed_kwarg = allowed_ids if (category_id is None and allowed_ids is not None) else None
    status = get_short_played_status(category_id, user_id=uid, allowed_category_ids=allowed_kwarg)
    return jsonify({'success': True, **status})

@app.route('/api/admin/shorts/reset_played', methods=['POST'])
@admin_required
def api_admin_reset_short_played():
    """[后台] 手动清空短视频的播放标记。支持传 user_id 清空指定用户，不传则清空全部。"""
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    affected = reset_all_short_played(user_id=user_id)
    return jsonify({'success': True, 'reset_count': affected})

@app.route('/api/v1/short_categories')
def api_v1_short_categories():
    """获取短视频分类树（含父子层级）

    若用户携带 Basic Auth 且有短视频分类权限限制：
      - categories 仅返回权限内的分类（含其父子层级展示）
      - category_counts 仅统计权限内分类的视频数
      - total_short_count 改为权限内的总数（非全局 5000）
    无 Basic Auth / 无权限限制时：保持原有全局行为。
    """
    categories = get_all_short_categories()
    # 获取当前用户及其短视频分类权限
    uid = _get_current_user_id()
    allowed_ids = get_user_allowed_category_ids(uid, 'short') if uid else None

    # 按权限过滤分类列表
    if allowed_ids is not None:
        categories = [c for c in categories if c['id'] in allowed_ids]

    cat_map = {c['id']: {**c, 'children': []} for c in categories}
    tree = []
    for c in categories:
        pid = c.get('parent_id', 0)
        if pid and pid in cat_map:
            cat_map[pid]['children'].append(cat_map[c['id']])
        else:
            tree.append(cat_map[c['id']])
    # 统计每个分类的视频数量（按权限范围过滤）
    conn = get_db()
    cur = conn.cursor()
    counts = {}
    if allowed_ids is not None and len(allowed_ids) > 0:
        placeholders = ','.join(['?' for _ in allowed_ids])
        cur.execute(
            f'SELECT category_id, COUNT(*) FROM videos WHERE is_short_video = 1 AND category_id IN ({placeholders}) GROUP BY category_id',
            allowed_ids)
        for row in cur.fetchall():
            counts[row[0] or 0] = row[1]
        cur.execute(
            f'SELECT COUNT(*) FROM videos WHERE is_short_video = 1 AND category_id IN ({placeholders})',
            allowed_ids)
    else:
        cur.execute('SELECT category_id, COUNT(*) FROM videos WHERE is_short_video = 1 GROUP BY category_id')
        for row in cur.fetchall():
            counts[row[0] or 0] = row[1]
        cur.execute('SELECT COUNT(*) FROM videos WHERE is_short_video = 1')
    total_count = cur.fetchone()[0]
    conn.close()
    return jsonify({
        'success': True,
        'categories': tree,
        'total_short_count': total_count,
        'category_counts': counts,
        # 标识当前是否按用户权限过滤（便于 APP 调试）
        'filtered_by_permission': allowed_ids is not None,
    })

@app.route('/api/v1/shorts')
def api_v1_shorts():
    """获取短视频列表

    参数:
      page: 页码 (默认1)
      per_page: 每页数量 (默认20, 最大500)
      category_id: 短视频分类ID (0或不传=全部)
      q: 搜索关键词
      exclude_played: 0/1 (默认0), 为1时仅返回未播放短视频；未播放为空时自动回退全部
    """
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 500)
    category_id = request.args.get('category_id', 0, type=int)
    keyword = request.args.get('q', '').strip()
    exclude_played = bool(request.args.get('exclude_played', 0, type=int))

    # 获取当前用户及其短视频分类权限
    uid = _get_current_user_id()
    allowed_ids = get_user_allowed_category_ids(uid, 'short') if uid else None

    # 权限校验：用户有权限限制且请求的具体分类不在权限内 → 返回空
    if allowed_ids is not None and category_id != 0 and category_id not in allowed_ids:
        return jsonify({
            'success': True,
            'videos': [],
            'total': 0,
            'page': page,
            'per_page': per_page,
            'total_pages': 0,
            'message': '无权访问该分类',
        })

    # 需求1：exclude_played=1 且无搜索关键词时，走专用查询（优先未播放，按用户维度）
    if exclude_played and not keyword:
        limit = per_page * page
        cat_kwarg = category_id if category_id else None
        # 全部请求 + 权限受限时，传 allowed_ids 让模型层按权限过滤
        allowed_kwarg = allowed_ids if (category_id == 0 and allowed_ids is not None) else None
        videos_pool, used_fallback, played_count, total_count = get_shorts_for_random(
            category_id=cat_kwarg, exclude_played=True, limit=limit,
            user_id=uid, allowed_category_ids=allowed_kwarg)
        # 分页（简单切片即可，limit 已预留 page*per_page）
        start = (page - 1) * per_page
        videos_page = videos_pool[start: start + per_page]
        videos = [_video_to_dict(v) for v in videos_page]
        total_pages = (len(videos_pool) + per_page - 1) // per_page if per_page else 0
        return jsonify({
            'success': True,
            'videos': videos,
            'total': len(videos_pool),
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
            'exclude_played': True,
            'used_fallback': used_fallback,
            'played_count': played_count,
            'total_count': total_count,
        })

    kwargs = {'page': page, 'per_page': per_page, 'is_short_video': True}
    if category_id:
        kwargs['category_id'] = category_id
    elif allowed_ids is not None:
        # 全部请求 + 用户有权限限制 → 按权限范围过滤
        kwargs['category_ids'] = allowed_ids
    if keyword:
        kwargs['keyword'] = keyword

    result = get_all_videos(**kwargs)

    videos = [_video_to_dict(v) for v in result['videos']]
    return jsonify({
        'success': True,
        'videos': videos,
        'total': result['total'],
        'page': result['page'],
        'per_page': result['per_page'],
        'total_pages': result['total_pages']
    })

@app.route('/api/v1/series')
def api_v1_series():
    """获取系列列表

    参数:
      page: 页码 (默认1)
      per_page: 每页数量 (默认20, 最大500)
      category_id: 分类ID筛选

    权限：
      - can_access_series=0 → 403（APP 端应隐藏合集入口）
      - normal 白名单 → 仅展示白名单内分类的合集
    """
    uid = _get_current_user_id()
    if not get_user_series_access(uid):
        return jsonify({'success': False, 'message': '无合集访问权限'}), 403
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 500)
    category_id = request.args.get('category_id', 0, type=int)

    # normal 权限裁剪：若用户指定 category_id 但不在白名单，回退到不过滤白名单模式
    final_category_id = category_id
    normal_allowed = None
    if uid is not None:
        normal_allowed = get_user_allowed_category_ids(uid, 'normal')
    if normal_allowed is not None:
        allow_set = set(normal_allowed)
        if category_id and category_id not in allow_set:
            final_category_id = 0  # 回退到全分类列表

    result = get_all_series(category_id=final_category_id, page=page, per_page=per_page)
    series_list = []
    for s in result['series_list']:
        # 即使未传 category_id，再做一次正常类裁剪兜底
        if normal_allowed is not None and s.get('category_id', 0) not in set(normal_allowed):
            continue
        series_list.append({
            'id': s['id'],
            'title': s.get('title', ''),
            'description': s.get('description', ''),
            'cover': s.get('cover', ''),
            'category_id': s.get('category_id', 0),
            'total_episodes': s.get('total_episodes', 0),
            'episode_count': s.get('episode_count', 0),
        })
    # 因二次裁剪后 total 不准，手动重算
    new_total = len(series_list)
    return jsonify({
        'success': True,
        'series': series_list,
        'total': new_total,
        'page': result['page'],
        'per_page': result['per_page'],
        'total_pages': max(1, (new_total + per_page - 1) // per_page) if new_total else 0
    })


@app.route('/api/v1/series/<int:series_id>/episodes')
def api_v1_series_episodes(series_id):
    """获取系列的所有分集

    权限：can_access_series 必须开启；normal 白名单会校验合集所属分类。
    """
    # 合集权限校验
    uid = _get_current_user_id()
    if not get_user_series_access(uid):
        return jsonify({'success': False, 'message': '无合集访问权限'}), 403
    series = get_series(series_id)
    if not series:
        return jsonify({'success': False, 'message': '系列不存在'}), 404
    # normal 权限二次校验（用户可能改了白名单）
    if uid is not None:
        normal_allowed = get_user_allowed_category_ids(uid, 'normal')
        if normal_allowed is not None and series.get('category_id', 0) not in set(normal_allowed):
            return jsonify({'success': False, 'message': '无权限访问该合集'}), 403
    episodes = get_episodes_by_series(series_id)
    return jsonify({
        'success': True,
        'series': {
            'id': series['id'],
            'title': series.get('title', ''),
            'cover': series.get('cover', ''),
            'description': series.get('description', ''),
            'total_episodes': series.get('total_episodes', 0),
        },
        'episodes': [_video_to_dict(e) for e in episodes]
    })

@app.route('/api/v1/stats')
def api_v1_stats():
    """获取统计数据"""
    stats = get_video_stats()
    return jsonify({'success': True, 'stats': stats})

@app.route('/api/v1/search')
def api_v1_search():
    """全局搜索视频（包含普通视频和短视频）

    参数:
      q: 搜索关键词
      page: 页码 (默认1)
      per_page: 每页数量 (默认20, 最大500)
      type: 筛选类型 all|video|shorts (默认all)

    权限：登录用户的 normal 白名单仅对 type=video/all 生效，与 videos 列表同款。
    """
    keyword = request.args.get('q', '').strip()
    if not keyword:
        return jsonify({'success': False, 'message': '请提供搜索关键词 q'}), 400

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 500)
    search_type = request.args.get('type', 'all')

    # 权限裁剪（仅作用于普通视频；shorts 由 short 权限独立控制）
    final_category_ids = None
    uid = _get_current_user_id()
    if uid is not None and search_type in ('video', 'all'):
        allowed_ids = get_user_allowed_category_ids(uid, 'normal')
        if allowed_ids is not None:
            final_category_ids = _expand_allowed_to_all_descendants(allowed_ids)

    if search_type == 'video':
        result = get_all_videos(keyword=keyword, page=page, per_page=per_page,
                                exclude_series_episodes=True, is_short_video=False,
                                category_ids=final_category_ids)
    elif search_type == 'shorts':
        result = get_all_videos(keyword=keyword, page=page, per_page=per_page,
                                is_short_video=True)
    else:
        result = get_all_videos(keyword=keyword, page=page, per_page=per_page,
                                category_ids=final_category_ids)

    videos = [_video_to_dict(v) for v in result['videos']]
    return jsonify({
        'success': True,
        'videos': videos,
        'total': result['total'],
        'page': result['page'],
        'per_page': result['per_page'],
        'total_pages': result['total_pages']
    })


# ===== 需求3：APP 专用 V1 API =====

@app.route('/api/v1/login', methods=['POST'])
def api_v1_login():
    """APP 登录接口：验证用户名密码，返回分类权限信息"""
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if not username or not password:
        return jsonify({'success': False, 'message': '用户名和密码不能为空'}), 400
    users = load_users()
    user = users.get(username)
    if not user or not verify_password(password, user['password']):
        return jsonify({'success': False, 'message': '用户名或密码错误'}), 401
    perms = get_user_permissions(user['id'])
    return jsonify({
        'success': True,
        'user': {
            'id': user['id'],
            'username': username,
            'role': user['role'],
        },
        'permissions': perms
    })

@app.route('/api/v1/user/categories')
def api_v1_user_categories():
    """获取当前登录用户的分类权限

    通过 session 或 Authorization header (username:password) 鉴权。
    返回 normal/short 两种类型的可查看分类ID列表，空列表表示全部可见。
    """
    uid = None
    # 方式1: session
    if session.get('logged_in'):
        uid = session.get('user_id')
    # 方式2: Basic Auth header
    if not uid:
        auth = request.authorization
        if auth and auth.username and auth.password:
            users = load_users()
            user = users.get(auth.username)
            if user and verify_password(auth.password, user['password']):
                uid = user['id']
    if not uid:
        return jsonify({'success': False, 'message': '未登录或认证失败'}), 401
    perms = get_user_permissions(uid)
    return jsonify({'success': True, 'permissions': perms})

@app.route('/api/v1/shorts/<int:video_id>/favorite', methods=['POST'])
def api_v1_toggle_favorite(video_id):
    """APP 收藏/取消收藏短视频"""
    uid = None
    if session.get('logged_in'):
        uid = session.get('user_id')
    if not uid:
        auth = request.authorization
        if auth and auth.username and auth.password:
            users = load_users()
            user = users.get(auth.username)
            if user and verify_password(auth.password, user['password']):
                uid = user['id']
    if not uid:
        return jsonify({'success': False, 'message': '未登录或认证失败'}), 401
    if is_favorited(uid, video_id):
        remove_favorite(uid, video_id)
        return jsonify({'success': True, 'favorited': False})
    else:
        add_favorite(uid, video_id)
        return jsonify({'success': True, 'favorited': True})

@app.route('/api/v1/favorites')
def api_v1_favorites():
    """获取当前登录用户的收藏视频列表"""
    uid = None
    if session.get('logged_in'):
        uid = session.get('user_id')
    if not uid:
        auth = request.authorization
        if auth and auth.username and auth.password:
            users = load_users()
            user = users.get(auth.username)
            if user and verify_password(auth.password, user['password']):
                uid = user['id']
    if not uid:
        return jsonify({'success': False, 'message': '未登录或认证失败'}), 401
    fav_ids = get_user_favorite_ids(uid)
    resp = {'success': True, 'favorite_ids': fav_ids}
    if request.args.get('full', 0, type=int) == 1:
        videos = [_video_to_dict(v) for v in get_user_favorite_videos(uid)]
        resp['videos'] = videos
        resp['total'] = len(videos)
    return jsonify(resp)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=3090)

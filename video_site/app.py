from flask import Flask, render_template, request, jsonify, redirect, url_for, session, abort, send_file
import os
import json
import mimetypes
from functools import wraps
import requests
from urllib.parse import unquote, urlparse
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config, RESOURCE_DIR
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
    get_all_favorites, delete_favorite, batch_delete_favorites, batch_delete_all_favorites
)
from alist_api import OpenListApi
from nfo_parser import parse_nfo_content, get_nfo_file_for_video, extract_nfo_metadata

app = Flask(__name__,
            template_folder=os.path.join(RESOURCE_DIR, 'templates'),
            static_folder=os.path.join(RESOURCE_DIR, 'static'))
app.config['SECRET_KEY'] = Config.SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = 86400
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
    return render_template('admin/users.html',
                         users=users,
                         all_categories=all_categories,
                         all_short_categories=all_short_categories,
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
                                    series_cover = nfo_data['poster']
                                elif nfo_data.get('thumbs'):
                                    series_cover = nfo_data['thumbs'][0]
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
            if use_nfo:
                try:
                    video_full_path = video_info.get('full_path', '')
                    metadata = _fetch_nfo_for_video(account, video_full_path, api)
                    if metadata:
                        # 使用 NFO 信息更新视频数据
                        if metadata.get('title'):
                            video_data['title'] = metadata['title']
                        if metadata.get('description'):
                            video_data['description'] = metadata['description']
                        if metadata.get('cover'):
                            video_data['cover'] = metadata['cover']
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
                except:
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

        for f in files:
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
    set_user_permissions(user_id, normal_ids, 'normal')
    set_user_permissions(user_id, short_ids, 'short')
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


def _fetch_nfo_for_video(account, file_path, api):
    """从视频所在目录查找并解析 NFO，返回 metadata dict（可能为空）。"""
    if not file_path or '/' not in file_path:
        return {}
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
        return {}

    nfo_direct_url = api.get_file_link(matching_nfo['full_path'])
    headers = {"Authorization": f"Bearer {api.token}"}
    resp = requests.get(nfo_direct_url, headers=headers, timeout=5)
    if resp.status_code != 200:
        return {}
    nfo_data = parse_nfo_content(resp.text)
    metadata = extract_nfo_metadata(nfo_data)
    return metadata or {}


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

        # 系列封面用首个视频的封面（流式URL），单视频封面各自查找
        cover_path_resolved = cover_path
        if cover_path_resolved and not os.path.isfile(cover_path_resolved):
            cover_path_resolved = ''
        if not cover_path_resolved:
            cover_path_resolved, _ = _find_local_cover_for_video(video_path)
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
    """获取分类树（含父子层级）"""
    categories = get_all_categories()
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
    """
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 500)
    category_id = request.args.get('category_id', 0, type=int)
    keyword = request.args.get('q', '').strip()

    if keyword:
        result = get_all_videos(keyword=keyword, page=page, per_page=per_page,
                                exclude_series_episodes=True, is_short_video=False)
    else:
        result = get_all_videos(category_id=category_id, page=page, per_page=per_page,
                                exclude_series_episodes=True, is_short_video=False)

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
    """获取视频详情"""
    video = get_video(video_id)
    if not video:
        return jsonify({'success': False, 'message': '视频不存在'}), 404
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

    权限：用户若 can_access_series=0 则返回 403，APP 端应隐藏合集入口
    """
    uid = _get_current_user_id()
    if not get_user_series_access(uid):
        return jsonify({'success': False, 'message': '无合集访问权限'}), 403
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 500)
    category_id = request.args.get('category_id', 0, type=int)

    result = get_all_series(category_id=category_id, page=page, per_page=per_page)
    series_list = []
    for s in result['series_list']:
        series_list.append({
            'id': s['id'],
            'title': s.get('title', ''),
            'description': s.get('description', ''),
            'cover': s.get('cover', ''),
            'category_id': s.get('category_id', 0),
            'total_episodes': s.get('total_episodes', 0),
            'episode_count': s.get('episode_count', 0),
        })
    return jsonify({
        'success': True,
        'series': series_list,
        'total': result['total'],
        'page': result['page'],
        'per_page': result['per_page'],
        'total_pages': result['total_pages']
    })

@app.route('/api/v1/series/<int:series_id>/episodes')
def api_v1_series_episodes(series_id):
    """获取系列的所有分集"""
    # 合集权限校验
    uid = _get_current_user_id()
    if not get_user_series_access(uid):
        return jsonify({'success': False, 'message': '无合集访问权限'}), 403
    series = get_series(series_id)
    if not series:
        return jsonify({'success': False, 'message': '系列不存在'}), 404
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
    """
    keyword = request.args.get('q', '').strip()
    if not keyword:
        return jsonify({'success': False, 'message': '请提供搜索关键词 q'}), 400

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 500)
    search_type = request.args.get('type', 'all')

    if search_type == 'video':
        result = get_all_videos(keyword=keyword, page=page, per_page=per_page,
                                exclude_series_episodes=True, is_short_video=False)
    elif search_type == 'shorts':
        result = get_all_videos(keyword=keyword, page=page, per_page=per_page,
                                is_short_video=True)
    else:
        result = get_all_videos(keyword=keyword, page=page, per_page=per_page)

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
    return jsonify({'success': True, 'favorite_ids': fav_ids})


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=3090)

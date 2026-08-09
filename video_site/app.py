from flask import Flask, render_template, request, jsonify, redirect, url_for, session, abort
import os
import json
from functools import wraps
import requests
from urllib.parse import unquote, urlparse
from config import Config
from models import (
    init_db, get_db, load_users, hash_password, verify_password,
    create_user, delete_user, get_all_categories, create_category,
    delete_category, batch_delete_categories, get_category_tree,
    get_all_short_categories, create_short_category,
    delete_short_category, batch_delete_short_categories, get_short_category_tree,
    get_all_videos, get_video, get_video_by_url, create_video, update_video, delete_video, increment_views,
    batch_delete_videos,
    get_all_series, get_series, create_series, update_series, delete_series, batch_delete_series, get_episodes_by_series,
    get_all_openlist_accounts, create_openlist_account, delete_openlist_account,
    get_video_stats
)
from alist_api import OpenListApi
from nfo_parser import parse_nfo_content, get_nfo_file_for_video, extract_nfo_metadata

app = Flask(__name__)
app.config['SECRET_KEY'] = Config.SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = 86400

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
    # 统计每个分类的视频数量
    conn = get_db()
    c = conn.cursor()
    cat_counts = {}
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
    """
    per_page = 500
    # 获取短分类以过滤验证 category_id
    short_categories = get_all_short_categories()
    valid_ids = {c['id'] for c in short_categories}
    if category_id != 0 and category_id not in valid_ids:
        return redirect(url_for('shorts_play', category_id=0))

    result = get_all_videos(page=1, per_page=per_page, is_short_video=True,
                            category_id=category_id if category_id else None)
    videos = result['videos']
    total = result['total']
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
                         active_tab='shorts')

@app.route('/admin')
@admin_required
def admin_dashboard():
    stats = get_video_stats()
    categories = get_all_categories()
    return render_template('admin/dashboard.html',
                         stats=stats,
                         categories=categories,
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

@app.route('/admin/users')
@admin_required
def admin_users():
    users = load_users()
    return render_template('admin/users.html',
                         users=users,
                         active_tab='users')

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
    return jsonify({'success': True, 'views': (video.get('views', 0) or 0) + 1})

@app.route('/api/videos/batch_delete', methods=['POST'])
@admin_required
def api_batch_delete_videos():
    data = request.json
    video_ids = data.get('video_ids', [])
    if not video_ids:
        return jsonify({'success': False, 'message': '请选择要删除的视频'}), 400
    count = batch_delete_videos(video_ids)
    return jsonify({'success': True, 'deleted_count': count})

@app.route('/api/series/batch_delete', methods=['POST'])
@admin_required
def api_batch_delete_series():
    data = request.json
    series_ids = data.get('series_ids', [])
    if not series_ids:
        return jsonify({'success': False, 'message': '请选择要删除的系列'}), 400
    count = batch_delete_series(series_ids)
    return jsonify({'success': True, 'deleted_count': count})

@app.route('/api/categories/batch_delete', methods=['POST'])
@admin_required
def api_batch_delete_categories():
    data = request.json
    category_ids = data.get('category_ids', [])
    if not category_ids:
        return jsonify({'success': False, 'message': '请选择要删除的分类'}), 400
    count = batch_delete_categories(category_ids)
    return jsonify({'success': True, 'deleted_count': count})

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

            # 标题优先级：NFO标题 > 目录名 > 文件名
            # 点击"选择此目录"时 series_name 非空，用目录名作为视频名称
            if series_name:
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


# ===================== 开放API接口（供APP调用） =====================

def _video_to_dict(v):
    """将视频记录转为API输出字典，隐藏内部字段"""
    if not v:
        return None
    return {
        'id': v['id'],
        'title': v.get('title', ''),
        'description': v.get('description', ''),
        'cover': v.get('cover', ''),
        'video_url': v.get('video_url', ''),
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

@app.route('/api/v1/short_categories')
def api_v1_short_categories():
    """获取短视频分类树（含父子层级）"""
    categories = get_all_short_categories()
    cat_map = {c['id']: {**c, 'children': []} for c in categories}
    tree = []
    for c in categories:
        pid = c.get('parent_id', 0)
        if pid and pid in cat_map:
            cat_map[pid]['children'].append(cat_map[c['id']])
        else:
            tree.append(cat_map[c['id']])
    # 统计每个分类的视频数量
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT category_id, COUNT(*) FROM videos WHERE is_short_video = 1 GROUP BY category_id')
    counts = {}
    for row in cur.fetchall():
        counts[row[0] or 0] = row[1]
    cur.execute('SELECT COUNT(*) FROM videos WHERE is_short_video = 1')
    total_count = cur.fetchone()[0]
    conn.close()
    return jsonify({
        'success': True,
        'categories': tree,
        'total_short_count': total_count,
        'category_counts': counts
    })

@app.route('/api/v1/shorts')
def api_v1_shorts():
    """获取短视频列表

    参数:
      page: 页码 (默认1)
      per_page: 每页数量 (默认20, 最大500)
      category_id: 短视频分类ID (0或不传=全部)
      q: 搜索关键词
    """
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 500)
    category_id = request.args.get('category_id', 0, type=int)
    keyword = request.args.get('q', '').strip()

    kwargs = {'page': page, 'per_page': per_page, 'is_short_video': True}
    if category_id:
        kwargs['category_id'] = category_id
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
    """
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


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=3090)

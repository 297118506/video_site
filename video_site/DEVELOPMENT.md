# 视频管理系统 - 开发文档

## 1. 项目概述

基于 Flask 的视频管理系统，支持通过 OpenList 管理视频文件，提供首页视频浏览、抖音式短视频播放、系列合集、分类管理等功能。系统内置完整的 RESTful API 接口，方便开发配套 APP。

### 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | Flask 3.x (Python 3.12+) |
| 数据库 | SQLite |
| 前端 | Bootstrap 5 + Jinja2 模板 |
| 视频播放 | Video.js / HLS.js |
| 文件存储 | OpenList (AList 兼容) |
| 元数据解析 | NFO 文件 (XML 格式) |

### 运行环境

- Python 3.12+
- 依赖: `flask>=3.0.0`, `requests>=2.31.0`
- 端口: 3090
- 启动命令: `python run.py`
- 默认账号: `admin / password`

## 2. 项目结构

```
video_site/
├── app.py              # Flask 主应用 (路由、API、业务逻辑)
├── models.py           # 数据库模型 (SQLite CRUD)
├── config.py           # 配置文件
├── alist_api.py        # OpenList API 封装
├── nfo_parser.py       # NFO 文件解析器
├── run.py              # 启动入口
├── requirements.txt    # Python 依赖
├── data/
│   └── videos.db       # SQLite 数据库文件
├── static/
│   ├── css/style.css   # 全局样式
│   └── js/main.js      # 全局脚本
└── templates/
    ├── base.html       # 基础模板 (导航栏)
    ├── index.html      # 首页 (视频列表 + 分类)
    ├── shorts.html     # 短视频页面 (抖音式滑动)
    ├── player.html     # 视频播放器页面
    ├── video_detail.html  # 视频详情页
    ├── login.html      # 登录页
    └── admin/
        ├── dashboard.html    # 后台仪表盘
        ├── videos.html       # 视频管理列表
        ├── video_form.html   # 视频添加/编辑表单
        ├── categories.html   # 分类管理
        ├── series.html       # 系列管理
        ├── series_form.html  # 系列添加/编辑表单
        ├── openlist.html     # OpenList 文件管理
        └── users.html        # 用户管理
```

## 3. 数据库设计

### 3.1 videos 表 (视频)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| title | TEXT | 视频标题 |
| cover | TEXT | 封面图 URL |
| category_id | INTEGER | 分类 ID (0=未分类) |
| description | TEXT | 描述 |
| series_id | INTEGER | 所属系列 ID (NULL=独立视频) |
| episode_number | INTEGER | 集数编号 |
| duration | TEXT | 时长 |
| source | TEXT | 来源 (默认 'openlist') |
| video_url | TEXT | 视频直链 URL |
| video_type | TEXT | 视频格式 (mp4/mkv/m3u8...) |
| is_series | INTEGER | 是否为系列分集 (0/1) |
| views | INTEGER | 播放量 |
| sort_order | INTEGER | 排序权重 |
| genre | TEXT | 类型/标签 |
| rating | TEXT | 评分 |
| year | TEXT | 年份 |
| actors | TEXT | 演员 (逗号分隔) |
| is_short_video | INTEGER | 是否为短视频 (0=普通, 1=短视频) |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

### 3.2 series 表 (系列)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| title | TEXT | 系列标题 |
| cover | TEXT | 系列封面 URL |
| category_id | INTEGER | 所属分类 ID |
| description | TEXT | 描述 |
| total_episodes | INTEGER | 总集数 |
| created_at | TIMESTAMP | 创建时间 |

### 3.3 categories 表 (分类)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| name | TEXT | 分类名称 |
| slug | TEXT UNIQUE | URL 友好标识 |
| parent_id | INTEGER | 父分类 ID (0=顶级分类) |
| sort_order | INTEGER | 排序权重 |
| created_at | TIMESTAMP | 创建时间 |

### 3.4 users 表 (用户)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| username | TEXT UNIQUE | 用户名 |
| password | TEXT | SHA-256 哈希密码 |
| role | TEXT | 角色 (admin/user) |
| created_at | TIMESTAMP | 创建时间 |

### 3.5 openlist_accounts 表 (OpenList 账户)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| name | TEXT | 账户名称 |
| server_url | TEXT | OpenList 服务器地址 |
| username | TEXT | 用户名 |
| password | TEXT | 密码 |
| created_at | TIMESTAMP | 创建时间 |

### 3.6 模块隔离逻辑

```
首页「全部视频」列表:  is_short_video=0 AND (series_id IS NULL OR series_id=0)
短视频模块列表:        is_short_video=1
系列合集:              is_series=1, 通过 series_id 关联
```

## 4. 开放 API 接口 (供 APP 调用)

所有 API 以 `/api/v1` 为前缀，**无需认证**，直接调用。

### 4.1 获取分类树

```
GET /api/v1/categories
```

**响应:**
```json
{
  "success": true,
  "categories": [
    {
      "id": 1,
      "name": "日本",
      "slug": "日本",
      "parent_id": 0,
      "sort_order": 0,
      "children": [
        { "id": 2, "name": "子分类", "parent_id": 1, "children": [] }
      ]
    }
  ]
}
```

### 4.2 获取视频列表

```
GET /api/v1/videos?page=1&per_page=20&category_id=0&q=关键词
```

**参数:**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| page | int | 1 | 页码 |
| per_page | int | 20 | 每页数量 (最大 500) |
| category_id | int | 0 | 分类筛选 (0=全部) |
| q | string | - | 搜索关键词 |

**说明:** 返回首页全部视频，自动排除系列分集 (`is_series=0`) 和短视频 (`is_short_video=0`)。

**响应:**
```json
{
  "success": true,
  "videos": [
    {
      "id": 1,
      "title": "视频标题",
      "description": "描述",
      "cover": "https://example.com/cover.jpg",
      "video_url": "https://example.com/video.mp4",
      "video_type": "mp4",
      "category_id": 1,
      "series_id": null,
      "episode_number": 0,
      "is_series": 0,
      "is_short_video": 0,
      "genre": "喜剧",
      "rating": "8.5",
      "year": "2024",
      "actors": "演员A, 演员B",
      "views": 128,
      "duration": 0
    }
  ],
  "total": 100,
  "page": 1,
  "per_page": 20,
  "total_pages": 5
}
```

### 4.3 获取视频详情

```
GET /api/v1/videos/{video_id}
```

**说明:** 每次调用自动 +1 浏览量。

**响应:**
```json
{
  "success": true,
  "video": {
    "id": 1,
    "title": "视频标题",
    "description": "描述",
    "cover": "https://...",
    "video_url": "https://...",
    "video_type": "mp4",
    "category_id": 1,
    "series_id": null,
    "episode_number": 0,
    "is_series": 0,
    "is_short_video": 0,
    "genre": "喜剧",
    "rating": "8.5",
    "year": "2024",
    "actors": "演员A",
    "views": 129,
    "duration": 0
  }
}
```

### 4.4 获取短视频列表

```
GET /api/v1/shorts?page=1&per_page=500&q=关键词
```

**参数:**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| page | int | 1 | 页码 |
| per_page | int | 20 | 每页数量 (最大 500) |
| q | string | - | 搜索关键词 |

**说明:** 仅返回 `is_short_video=1` 的视频。建议 APP 端一次性拉取较多数量 (如 per_page=500) 以实现流畅的滑动体验。

### 4.5 获取系列列表

```
GET /api/v1/series?page=1&per_page=20&category_id=0
```

**响应:**
```json
{
  "success": true,
  "series": [
    {
      "id": 1,
      "title": "系列名称",
      "description": "描述",
      "cover": "https://...",
      "category_id": 1,
      "total_episodes": 10,
      "episode_count": 10
    }
  ],
  "total": 5,
  "page": 1,
  "per_page": 20,
  "total_pages": 1
}
```

### 4.6 获取系列分集

```
GET /api/v1/series/{series_id}/episodes
```

**响应:**
```json
{
  "success": true,
  "series": {
    "id": 1,
    "title": "系列名称",
    "cover": "https://...",
    "description": "描述",
    "total_episodes": 10
  },
  "episodes": [
    {
      "id": 10,
      "title": "系列名称 第1集",
      "episode_number": 1,
      "video_url": "https://...",
      "cover": "https://...",
      ...
    }
  ]
}
```

### 4.7 获取统计数据

```
GET /api/v1/stats
```

**响应:**
```json
{
  "success": true,
  "stats": {
    "total": 100,
    "total_views": 5000,
    "total_series": 10,
    "total_categories": 5
  }
}
```

### 4.8 全局搜索

```
GET /api/v1/search?q=关键词&type=all&page=1&per_page=20
```

**参数:**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| q | string | **必填** | 搜索关键词 |
| type | string | all | 搜索范围: `all` (全部), `video` (仅普通视频), `shorts` (仅短视频) |
| page | int | 1 | 页码 |
| per_page | int | 20 | 每页数量 (最大 500) |

**说明:** 搜索匹配 `title` 和 `description` 字段。

### 4.9 错误响应

```json
{
  "success": false,
  "message": "视频不存在"
}
```

| HTTP 状态码 | 说明 |
|-------------|------|
| 200 | 成功 |
| 400 | 参数错误 |
| 404 | 资源不存在 |
| 500 | 服务器错误 |

## 5. APP 开发指南

### 5.1 视频播放

视频播放地址通过 `video_url` 字段获取，支持以下格式:

| 格式 | 扩展名 | 播放方案 |
|------|--------|----------|
| HLS 流 | .m3u8 | 使用 HLS 播放器 (ExoPlayer/AVPlayer/Video.js) |
| MP4 | .mp4 | 系统原生播放器 |
| WebM | .webm | 系统原生播放器 |
| FLV | .flv | 需 FLV 播放器 |
| MKV/AVI 等 | .mkv/.avi | 需要软解码播放器 |

**`video_type` 字段** 标识了视频格式，APP 可据此选择播放器内核。

### 5.2 封面图处理

- `cover` 字段为图片直链 URL
- 封面可能为空字符串，APP 需要处理默认占位图
- 短视频封面同样通过 `cover` 字段获取

### 5.3 首页视频列表 APP 实现建议

```
1. GET /api/v1/categories          → 渲染分类导航栏
2. GET /api/v1/videos?page=1       → 首页视频列表 (瀑布流/网格)
3. 点击分类 → GET /api/v1/videos?category_id={id}
4. 搜索 → GET /api/v1/search?q={keyword}&type=video
5. 点击视频 → GET /api/v1/videos/{id} → 跳转播放器
```

### 5.4 短视频模块 APP 实现建议

```
1. GET /api/v1/shorts?per_page=500  → 一次性拉取短视频列表
2. 使用 ViewPager/RecyclerView 实现上下滑动切换
3. 当前视频播放，预加载上下各一个视频
4. 横屏视频: object-fit=contain (完整显示)
5. 竖屏视频: object-fit=cover (填充屏幕)
6. 自动连播: 当前视频播放结束后自动切换下一个
```

### 5.5 系列合集 APP 实现建议

```
1. GET /api/v1/series              → 系列列表
2. GET /api/v1/series/{id}/episodes → 系列分集列表
3. 按 episode_number 排序显示分集
4. 播放完一集后自动播放下一集
```

### 5.6 分页加载策略

```python
# APP 端伪代码
page = 1
has_more = True

while has_more:
    response = GET(f"/api/v1/videos?page={page}&per_page=20")
    data = response.json()
    
    videos.extend(data['videos'])
    has_more = data['page'] < data['total_pages']
    page += 1
```

### 5.7 API 调用示例

**cURL:**
```bash
# 获取视频列表
curl "http://your-server:3090/api/v1/videos?page=1&per_page=20"

# 搜索视频
curl "http://your-server:3090/api/v1/search?q=测试&type=all"

# 获取短视频
curl "http://your-server:3090/api/v1/shorts?per_page=500"
```

**Python:**
```python
import requests

BASE_URL = "http://your-server:3090/api/v1"

# 获取视频列表
resp = requests.get(f"{BASE_URL}/videos", params={"page": 1, "per_page": 20})
data = resp.json()
for video in data["videos"]:
    print(f"[{video['id']}] {video['title']} - {video['video_url']}")

# 获取视频详情
resp = requests.get(f"{BASE_URL}/videos/1")
video = resp.json()["video"]
print(f"标题: {video['title']}")
print(f"播放地址: {video['video_url']}")
```

**JavaScript:**
```javascript
const API_BASE = 'http://your-server:3090/api/v1';

// 获取分类
const catRes = await fetch(`${API_BASE}/categories`);
const { categories } = await catRes.json();

// 获取视频列表
const vidRes = await fetch(`${API_BASE}/videos?page=1&per_page=20`);
const { videos, total, total_pages } = await vidRes.json();

// 播放视频
function playVideo(video) {
  const player = document.createElement('video');
  player.src = video.video_url;
  player.poster = video.cover;
  player.play();
}
```

**Dart (Flutter):**
```dart
final apiBase = 'http://your-server:3090/api/v1';

// 获取短视频列表
final response = await http.get(Uri.parse('$apiBase/shorts?per_page=500'));
final data = json.decode(response.body);

List<Video> shorts = (data['videos'] as List)
    .map((v) => Video.fromJson(v))
    .toList();

// Video 模型
class Video {
  final int id;
  final String title;
  final String videoUrl;
  final String cover;
  final bool isShortVideo;

  Video.fromJson(Map<String, dynamic> json)
      : id = json['id'],
        title = json['title'],
        videoUrl = json['video_url'],
        cover = json['cover'] ?? '',
        isShortVideo = json['is_short_video'] == 1;
}
```

## 6. OpenList 集成说明

### 6.1 OpenList API 封装

系统通过 `alist_api.py` 封装 OpenList 操作:

| 方法 | 说明 |
|------|------|
| `login()` | 登录获取 Token |
| `get_file_list(path)` | 获取目录文件列表 (自动分页) |
| `get_all_files_flat(path)` | 递归获取目录下所有视频文件 |
| `get_file_link(file_path)` | 获取文件直链 URL |
| `get_direct_link(file_path)` | 获取真实直链 (302 重定向地址) |

### 6.2 视频导入流程

```
1. 用户在 OpenList 管理页面选择目录或视频
2. 选择导入模块: 全部视频 / 短视频
3. (可选) 设置封面图片
4. (可选) 启用自动创建系列
5. (可选) 启用 NFO 元数据自动读取
6. 后端递归扫描视频文件，去重后写入数据库
```

### 6.3 NFO 元数据解析

NFO 文件为 XML 格式，支持 `movie`、`tvshow`、`episodedetails` 等根节点。

解析字段:

| NFO 字段 | 数据库字段 | 说明 |
|----------|-----------|------|
| `<title>` | title | 标题 |
| `<plot>` | description | 描述 |
| `<genre>` | genre | 类型 |
| `<rating>` | rating | 评分 |
| `<year>` | year | 年份 |
| `<actor><name>` | actors | 演员 |
| `<thumb>` | cover | 封面 |
| `<episode>` | episode_number | 集数 |

### 6.4 封面选择优先级

1. NFO 文件中指定的封面
2. 目录中唯一的图片文件
3. 文件名包含 'poster' 的图片
4. 手动选择

## 7. 前端页面路由

| 路由 | 页面 | 权限 | 说明 |
|------|------|------|------|
| `/` | 首页 | 登录 | 视频列表 + 分类导航 + 系列合集 |
| `/shorts` | 短视频 | 登录 | 抖音式上下滑动播放 |
| `/play/<id>` | 播放器 | 登录 | 独立播放器页面 |
| `/video/<id>` | 视频详情 | 登录 | 视频信息 + 相关推荐 |
| `/series/<id>` | 系列详情 | 登录 | 系列分集列表 |
| `/category/<id>` | 分类页 | 登录 | 分类下视频列表 |
| `/login` | 登录 | 公开 | 用户登录 |
| `/admin` | 后台首页 | 管理员 | 仪表盘 |
| `/admin/videos` | 视频管理 | 管理员 | 视频列表/编辑/删除 |
| `/admin/shorts` | 短视频管理 | 管理员 | 短视频列表/编辑/删除 |
| `/admin/categories` | 分类管理 | 管理员 | 分类树管理 |
| `/admin/series` | 系列管理 | 管理员 | 系列列表/编辑/删除 |
| `/admin/openlist` | OpenList 管理 | 管理员 | 文件浏览/视频导入 |
| `/admin/users` | 用户管理 | 管理员 | 用户增删 |

## 8. 配置说明

### 8.1 config.py

```python
class Config:
    SECRET_KEY = 'video_site_secret_key_2024'      # Flask 密钥
    DATABASE = 'data/videos.db'                     # 数据库路径
    OPENLIST_CONFIG_FILE = 'data/openlist_config.json'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024           # 最大请求体 16MB
```

### 8.2 启动参数

- **Host**: `0.0.0.0` (监听所有网卡)
- **Port**: `3090`
- **Debug**: 开启 (开发模式)

### 8.3 数据库迁移

系统启动时自动执行表结构创建和字段迁移:
- `init_db()` 创建所有表 (IF NOT EXISTS)
- `_migrate_videos_table()` 为已有表添加新字段 (genre, rating, year, actors, is_short_video)

## 9. 部署说明

### 9.1 开发环境

```bash
cd video_site
pip install -r requirements.txt
python run.py
# 访问 http://localhost:3090
```

### 9.2 生产环境建议

```bash
# 使用 gunicorn
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:3090 app:app

# 或使用 waitress (Windows)
pip install waitress
waitress-serve --port=3090 app:app
```

### 9.3 Nginx 反向代理 (可选)

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:3090;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # 视频文件代理 (如有需要)
    location /d/ {
        proxy_pass http://127.0.0.1:5244;  # OpenList 端口
        proxy_set_header Host $host;
    }
}
```

## 10. 注意事项

1. **API 无认证**: `/api/v1/*` 接口无需认证，请确保服务器网络环境安全，或通过 Nginx 添加 IP 白名单/Token 验证
2. **视频直链**: `video_url` 为 OpenList 的直链地址，APP 直接请求此 URL 播放视频
3. **短视频性能**: 短视频页面一次加载最多 500 条，APP 端建议做本地缓存和预加载
4. **数据隔离**: 普通视频和短视频通过 `is_short_video` 字段隔离，互不干扰
5. **系列分集**: 系列分集不会出现在首页「全部视频」列表中，仅通过系列入口访问
6. **NFO 依赖**: NFO 元数据为可选功能，无 NFO 文件时使用文件名作为标题
7. **去重机制**: 导入视频时按 `video_url` 去重，重复导入会自动跳过

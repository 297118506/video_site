# APP 端功能更新提示词：用户分类权限 + 短视频收藏

## 一、功能背景

后端（视频站点）已于 2026-08-17 新增两个功能：
1. **用户分类权限分配**：管理员可为每个用户设置可查看的长视频分类和短视频分类，APP 登录后获取权限列表，据此过滤可见分类。
2. **短视频收藏**：用户可在播放短视频时点击收藏按钮加入收藏列表，收藏状态多端共享。

用户名和密码对于配套 APP 来说仅作为获取不同分类权限的识别和匹配信息，在 APP 中涉及用户信息的其他功能均不需要实现。

---

## 二、后端提供的 API 清单

### 2.1 登录并获取分类权限

```
POST /api/v1/login
```

**请求体**：
```json
{"username": "admin", "password": "123456"}
```

**响应**：
```json
{
  "success": true,
  "user": {"id": 1, "username": "admin", "role": "admin"},
  "permissions": {
    "normal": [1, 2, 3],
    "short": [5, 6]
  }
}
```

**关键字段**：
- `permissions.normal`：可查看的长视频分类 ID 列表，**空数组表示全部可见**
- `permissions.short`：可查看的短视频分类 ID 列表，**空数组表示全部可见**

### 2.2 获取分类权限（需要鉴权）

```
GET /api/v1/user/categories
```

**鉴权方式**：HTTP Basic Auth（`Authorization: Basic base64(username:password)`）

**响应**：与登录返回的 permissions 结构一致。

### 2.3 收藏/取消收藏短视频

```
POST /api/v1/shorts/{video_id}/favorite
```

**鉴权方式**：HTTP Basic Auth

**响应**：
```json
{"success": true, "favorited": true}
```

### 2.4 获取用户收藏列表

```
GET /api/v1/favorites
```

**鉴权方式**：HTTP Basic Auth

**响应**：
```json
{"success": true, "favorite_ids": [1, 3, 7, 12]}
```

### 2.5 获取分类列表（已有接口，配合权限使用）

```
GET /api/v1/categories         — 长视频分类树
GET /api/v1/short_categories    — 短视频分类树
```

---

## 三、APP 端需要实现的功能点

### 功能点 1：登录并获取分类权限

**实现要求**：
1. APP 启动时或用户输入用户名密码后，调用 `POST /api/v1/login`
2. 保存返回的 `user.id` 和 `permissions` 到本地存储
3. 如果 `permissions.normal` 为空数组 → 长视频全部可见
4. 如果 `permissions.short` 为空数组 → 短视频全部可见
5. 如果有具体的 ID 列表 → 仅显示这些分类中的视频

### 功能点 2：分类列表过滤

**实现要求**：
1. 拉取分类列表：`GET /api/v1/categories` 或 `GET /api/v1/short_categories`
2. 根据本地存储的 `permissions.normal` / `permissions.short` 过滤分类列表
3. 空数组 = 不过滤（全部显示）
4. 非空数组 = 仅显示 ID 在列表中的分类

### 功能点 3：短视频收藏

**触发时机**：用户点击短视频播放界面的收藏按钮。

**实现要求**：
1. 调用 `POST /api/v1/shorts/{video_id}/favorite`
2. 根据 `favorited` 返回值更新 UI（已收藏/未收藏图标切换）
3. 本地缓存收藏列表，避免每次都请求

### 功能点 4：收藏列表展示

**实现要求**：
1. APP 启动时调用 `GET /api/v1/favorites` 获取已收藏的视频 ID 列表
2. 在短视频列表中对已收藏的视频显示收藏标记
3. 可选：提供「我的收藏」入口，仅展示收藏的短视频

### 功能点 5：本地缓存

**存储要求**：
- 使用 SharedPreferences（Android）/ UserDefaults（iOS）/ 对应平台轻量存储
- 缓存键名：`user_permissions_normal`、`user_permissions_short`、`user_favorite_ids`
- 缓存值：JSON 字符串

**同步策略**：
1. 登录时：保存 permissions 和 user_id
2. 收藏时：本地立即更新缓存 + 调用后端 API
3. APP 启动时：调用 `GET /api/v1/favorites` 同步收藏列表

---

## 四、鉴权说明

APP 使用 HTTP Basic Auth 进行鉴权：

```
Authorization: Basic base64(username:password)
```

每个请求的 Header 中携带此字段即可。登录接口 `POST /api/v1/login` 不需要鉴权，用于首次获取用户信息和权限。

---

## 五、验收标准

| 编号 | 测试场景 | 预期结果 |
|------|----------|----------|
| 1 | APP 使用正确用户名密码登录 | 返回 success=true，包含 user 和 permissions |
| 2 | APP 使用错误密码登录 | 返回 401，提示用户名或密码错误 |
| 3 | APP 登录后获取分类列表 | 根据 permissions 过滤后的分类列表 |
| 4 | permissions.normal 为空 | 长视频分类全部可见 |
| 5 | permissions.short = [1,2] | 短视频仅显示分类 1 和 2 中的视频 |
| 6 | APP 点击收藏按钮 | 调用 POST API，UI 图标切换为已收藏 |
| 7 | APP 再次点击 | 取消收藏，UI 图标切换为未收藏 |
| 8 | APP 重启后查看收藏列表 | 与服务端同步，已收藏的视频显示标记 |
| 9 | Web 端收藏后 APP 端查看 | APP 端同步显示已收藏 |
| 10 | APP 端收藏后 Web 端查看 | Web 端同步显示已收藏 |

---

## 六、参考实现（伪代码）

```kotlin
// Android Kotlin 示例
class VideoRepository(private val api: VideoApi, private val prefs: SharedPreferences) {

    private var userId: Int = prefs.getInt("user_id", 0)
    private var normalPerms: Set<Int> = prefs.getStringSet("user_permissions_normal", emptySet())?.mapNotNull { it.toIntOrNull() }?.toSet() ?: emptySet()
    private var shortPerms: Set<Int> = prefs.getStringSet("user_permissions_short", emptySet())?.mapNotNull { it.toIntOrNull() }?.toSet() ?: emptySet()
    private var favoriteIds: MutableSet<Int> = prefs.getStringSet("user_favorite_ids", emptySet())?.mapNotNull { it.toIntOrNull() }?.toMutableSet() ?: mutableSetOf()

    suspend fun login(username: String, password: String): Boolean {
        val response = api.login(LoginRequest(username, password))
        if (response.success) {
            userId = response.user.id
            normalPerms = response.permissions.normal.toSet()
            shortPerms = response.permissions.short.toSet()
            prefs.edit()
                .putInt("user_id", userId)
                .putStringSet("user_permissions_normal", normalPerms.map { it.toString() }.toSet())
                .putStringSet("user_permissions_short", shortPerms.map { it.toString() }.toSet())
                .apply()
            // 保存 Basic Auth 凭证供后续请求使用
            val auth = Base64.encodeToString("$username:$password".toByteArray(), Base64.NO_WRAP)
            prefs.edit().putString("auth_token", "Basic $auth").apply()
            // 同步收藏列表
            syncFavorites()
            return true
        }
        return false
    }

    fun filterCategories(allCategories: List<Category>, type: String): List<Category> {
        val perms = if (type == "normal") normalPerms else shortPerms
        if (perms.isEmpty()) return allCategories  // 空列表 = 全部可见
        return allCategories.filter { it.id in perms }
    }

    suspend fun toggleFavorite(videoId: Int): Boolean {
        val response = api.toggleFavorite(videoId)
        if (response.success) {
            if (response.favorited) {
                favoriteIds.add(videoId)
            } else {
                favoriteIds.remove(videoId)
            }
            prefs.edit().putStringSet("user_favorite_ids", favoriteIds.map { it.toString() }.toSet()).apply()
        }
        return response.favorited
    }

    suspend fun syncFavorites() {
        try {
            val response = api.getFavorites()
            if (response.success) {
                favoriteIds = response.favorite_ids.toMutableSet()
                prefs.edit().putStringSet("user_favorite_ids", favoriteIds.map { it.toString() }.toSet()).apply()
            }
        } catch (e: Exception) { /* 静默失败 */ }
    }

    fun isFavorited(videoId: Int): Boolean = videoId in favoriteIds
}
```

---

## 七、接口汇总速查表

| 接口 | 方法 | 用途 | 鉴权 |
|------|------|------|------|
| `/api/v1/login` | POST | 登录并获取权限 | 无需鉴权 |
| `/api/v1/user/categories` | GET | 获取分类权限 | Basic Auth |
| `/api/v1/shorts/{id}/favorite` | POST | 切换收藏 | Basic Auth |
| `/api/v1/favorites` | GET | 获取收藏列表 | Basic Auth |
| `/api/v1/categories` | GET | 长视频分类树 | 无需鉴权 |
| `/api/v1/short_categories` | GET | 短视频分类树 | 无需鉴权 |
| `/api/v1/shorts` | GET | 短视频列表 | 无需鉴权 |
| `/api/v1/shorts/{id}/play` | POST | 标记播放 | 无需鉴权 |
| `/api/v1/shorts/played` | GET | 查询播放状态 | 无需鉴权 |

---

## 八、后端代码位置参考

如需查阅后端实现，请访问以下文件：

- 数据层：[models.py](file:///d:/文件管理/VIDEO/video_site/models.py)
  - `set_user_permissions` (L745) — 设置用户分类权限
  - `get_user_permissions` (L761) — 获取用户分类权限
  - `add_favorite` (L793) — 添加收藏
  - `remove_favorite` (L806) — 取消收藏
  - `get_all_favorites` (L834) — 后台查询所有收藏
- API 层：[app.py](file:///d:/文件管理/VIDEO/video_site/app.py)
  - `POST /api/v1/login` (L1814) — APP 登录
  - `GET /api/v1/user/categories` (L1837) — 获取分类权限
  - `POST /api/v1/shorts/<id>/favorite` (L1861) — 切换收藏
  - `GET /api/v1/favorites` (L1883) — 获取收藏列表
- 完整更新说明：[UPDATE_20260808.md](file:///d:/文件管理/VIDEO/video_site/UPDATE_20260808.md)

---

请根据上述提示词在 APP 端实现对应功能。实现完成后，按「五、验收标准」逐项测试。

# APP 端功能更新提示词：短视频播放标记与去重随机播放

## 一、功能背景

后端（视频站点）已于 2026-08-12 新增「短视频播放标记」功能。当用户播放过一个短视频后，该视频会被标记为「已播放」；下次随机播放时优先排除已播放视频，直到所有短视频都被播放完后，后端自动清空标记重新开始一轮。

后端的标记状态对 **Web 端和 APP 端共享**，因此 APP 端需要同步实现以下功能，确保两端播放进度互通。

---

## 二、后端提供的 API 清单

### 1. 标记短视频已播放（APP 必须调用）

```
POST /api/v1/shorts/{video_id}/play
```

**用途**：用户在 APP 中播放完（或开始播放）一个短视频时调用，等效于 views+1 + 标记 is_played=1。

**响应示例**：
```json
{
  "success": true,
  "views": 12,
  "played": {
    "marked": true,
    "reset": false,
    "played_count": 5,
    "total_count": 160
  }
}
```

**关键字段**：
- `played.marked`：是否成功标记（非短视频或不存在时为 false）
- `played.reset`：**关键信号**。为 `true` 表示所有短视频都已播完，后端已自动清空标记。APP 收到此信号后必须清空本地 `played_ids` 缓存，下一轮重新开始。
- `played.played_count` / `played.total_count`：当前进度，可用于 UI 显示

### 2. 拉取未播放短视频列表（随机播放用）

```
GET /api/v1/shorts?exclude_played=1&category_id={id}&page=1&per_page=500
```

**用途**：APP 开启随机播放时，优先拉取未播放的短视频列表。

**响应新增字段**：
```json
{
  "success": true,
  "videos": [...],
  "total": 155,
  "exclude_played": true,
  "used_fallback": false,
  "played_count": 5,
  "total_count": 160
}
```

**关键字段**：
- `used_fallback`：为 `true` 表示未播放列表为空，后端已自动回退到全部短视频（此时 APP 可提示用户「已全部播放完，重新开始」）
- `played_count` / `total_count`：可用于顶部进度显示

### 3. 查询播放状态（本地同步用，可选）

```
GET /api/v1/shorts/played?category_id={id}
```

**用途**：APP 启动时或切换分类时调用，获取当前所有已播放视频 ID 列表，用于本地过滤或 UI 标记。

**响应示例**：
```json
{
  "success": true,
  "played_ids": [1, 3, 7, 12],
  "unplayed_ids": [2, 4, 5, 6, 8, ...],
  "played_count": 4,
  "unplayed_count": 156,
  "total_count": 160
}
```

**参数**：
- `category_id`：可选。0 或不传 = 全部短视频；其它 = 指定短分类

---

## 三、APP 端需要实现的功能点

### 功能点 1：播放时同步标记

**触发时机**：用户在 APP 中播放某个短视频时（建议在播放开始或播放结束时触发，与 Web 端保持一致——Web 端在视频进入视口并开始播放时调用）。

**实现要求**：
1. 调用 `POST /api/v1/shorts/{video_id}/play`
2. 检查响应中的 `played.reset` 字段：
   - 若为 `true`：清空本地 `played_ids` 缓存，刷新短视频列表，提示用户「已全部播放完，重新开始」
   - 若为 `false`：将该 `video_id` 加入本地 `played_ids` 缓存
3. 更新顶部进度显示（如「已播 5 / 160」）

**防重复**：同一个视频在一次会话内只调用一次接口（避免暂停恢复时重复标记）。建议用本地 `Set` 记录本次会话已标记的 video_id。

### 功能点 2：随机播放去重

**触发时机**：用户开启「随机播放」开关时。

**实现要求**：
1. 调用 `GET /api/v1/shorts?exclude_played=1&per_page=500` 拉取未播放列表
2. 对返回的列表本地执行 Fisher-Yates 洗牌算法
3. 按洗牌后的顺序播放
4. 检查 `used_fallback` 字段：
   - 若为 `true`：表示未播放为空（已全部播完），可提示用户「本轮已全部播放完，开始新一轮」
5. 每播放一个视频后，按「功能点 1」同步标记到后端

**关闭随机播放**：恢复原始顺序（按 `id DESC` 或后端默认顺序）。

### 功能点 3：本地播放进度缓存

**存储要求**：
- 使用 `SharedPreferences`（Android）/ `UserDefaults`（iOS）/ 对应平台的轻量存储
- 缓存键名建议：`shorts_played_ids`（存为 JSON 字符串或 Set）
- 缓存值：已播放的 video_id 列表

**同步策略**：
1. **APP 启动时**：调用 `GET /api/v1/shorts/played` 拉取后端最新状态，覆盖本地缓存（保证多端同步）
2. **播放时**：本地立即加入缓存（避免等待网络请求）
3. **收到 reset 信号时**：清空本地缓存
4. **切换分类时**：可选重新拉取该分类的播放状态

### 功能点 4：UI 进度显示

**展示位置**：短视频播放页顶部（与 Web 端保持一致）。

**展示内容**：
- 已播放数 / 总数（如「已播 5 / 160」）
- 可选：进度条或百分比

**数据来源**：
- 优先使用本地缓存计数（实时更新）
- 拉取列表时使用后端返回的 `played_count` / `total_count` 校准

### 功能点 5：已播放视频的视觉标记（可选增强）

在短视频列表或播放界面，对已播放的视频添加视觉标记（如右上角小图标、灰度化、徽章等），让用户知道哪些已经看过。

**数据来源**：本地 `played_ids` 缓存。

---

## 四、实现注意事项

1. **接口鉴权**：所有接口需要带上用户的登录凭证（Cookie / Token），与现有 APP 接口调用方式保持一致。

2. **错误处理**：
   - 网络请求失败时不应阻塞播放，标记请求可静默失败
   - `played.reset` 信号必须可靠处理，否则会导致本地缓存与后端不一致

3. **多端同步**：
   - 用户在 Web 端播放的视频，APP 启动时应通过 `GET /api/v1/shorts/played` 同步到本地
   - 反之亦然，APP 播放的视频通过 `POST /api/v1/shorts/{id}/play` 同步到后端，Web 端下次加载时能看到

4. **分类维度**：
   - `category_id` 参数为 0 或不传时表示「全部短视频」
   - 指定分类时仅统计该分类（含子孙分类）的播放进度

5. **性能优化**：
   - `GET /api/v1/shorts?exclude_played=1` 建议缓存列表，避免每次切换视频都重新拉取
   - 本地 `played_ids` 使用 Set 结构，查找性能 O(1)

---

## 五、验收标准

| 编号 | 测试场景 | 预期结果 |
|------|----------|----------|
| 1 | APP 播放一个短视频 | 调用 `POST /api/v1/shorts/{id}/play`，顶部进度 +1 |
| 2 | APP 开启随机播放 | 拉取的列表中不包含已播放视频 |
| 3 | APP 播放完最后一个未播放视频 | 收到 `reset=true`，本地缓存清空，提示「重新开始」 |
| 4 | APP 在 Web 端播放过的视频上播放 | 启动时同步后端状态，该视频显示为已播放 |
| 5 | APP 播放后切换到 Web 端 | Web 端「已播 X / Y」徽章包含 APP 播放过的视频 |
| 6 | APP 关闭随机播放 | 恢复原始顺序，不排除已播放视频 |
| 7 | APP 切换分类 | 进度数字按该分类重新计算 |
| 8 | APP 网络断开时播放 | 播放不阻塞，标记请求静默失败，下次联网时同步 |

---

## 六、参考实现（伪代码）

```kotlin
// Android Kotlin 示例
class ShortVideoRepository(private val api: VideoApi, private val prefs: SharedPreferences) {

    private val playedIds: MutableSet<Int> =
        prefs.getStringSet("shorts_played_ids", emptySet())?.mapNotNull { it.toIntOrNull() }?.toMutableSet()
            ?: mutableSetOf()

    suspend fun markPlayed(videoId: Int) {
        if (playedIds.contains(videoId)) return  // 防重复

        try {
            val response = api.markShortPlayed(videoId)
            if (response.success && response.played.marked) {
                if (response.played.reset) {
                    // 所有短视频播完，清空本地缓存
                    playedIds.clear()
                    prefs.edit().putStringSet("shorts_played_ids", emptySet()).apply()
                    // 通知 UI 刷新列表
                    _resetEvent.postValue(Unit)
                } else {
                    playedIds.add(videoId)
                    prefs.edit().putStringSet("shorts_played_ids", playedIds.map { it.toString() }.toSet()).apply()
                }
                _progress.postValue(response.played.played_count to response.played.total_count)
            }
        } catch (e: Exception) {
            // 网络失败静默处理，不阻塞播放
        }
    }

    suspend fun fetchRandomList(categoryId: Int = 0): List<Video> {
        val response = api.getShorts(excludePlayed = true, categoryId = categoryId, perPage = 500)
        if (response.usedFallback) {
            // 未播放为空，提示新一轮
            _newRoundEvent.postValue(Unit)
        }
        return response.videos.shuffled()  // 本地再次洗牌
    }

    suspend fun syncPlayedStatus(categoryId: Int = 0) {
        try {
            val status = api.getPlayedStatus(categoryId)
            playedIds.clear()
            playedIds.addAll(status.playedIds)
            prefs.edit().putStringSet("shorts_played_ids", playedIds.map { it.toString() }.toSet()).apply()
        } catch (e: Exception) {
            // 静默失败
        }
    }
}
```

---

## 七、接口汇总速查表

| 接口 | 方法 | 用途 | 关键参数 |
|------|------|------|----------|
| `/api/v1/shorts/{id}/play` | POST | 标记播放 + views+1 | 无 body |
| `/api/v1/shorts` | GET | 拉取短视频列表 | `exclude_played=1`, `category_id`, `page`, `per_page` |
| `/api/v1/shorts/played` | GET | 查询播放状态 | `category_id`（可选） |

---

## 八、后端代码位置参考

如需查阅后端实现，请访问以下文件：

- 数据层：[models.py](file:///d:/文件管理/VIDEO/video_site/models.py#L460)
  - `mark_short_played` (L462) — 标记播放 + 自动重置
  - `get_short_played_status` (L493) — 查询播放状态
  - `get_shorts_for_random` (L538) — 排除已播放查询
- API 层：[app.py](file:///d:/文件管理/VIDEO/video_site/app.py)
  - `POST /api/v1/shorts/<id>/play` (L1487)
  - `GET /api/v1/shorts/played` (L1510)
  - `GET /api/v1/shorts` (L1566，含 `exclude_played` 参数)
- 完整更新说明：[UPDATE_20260808.md](file:///d:/文件管理/VIDEO/video_site/UPDATE_20260808.md)

---

请根据上述提示词在 APP 端实现对应功能。实现完成后，按「五、验收标准」逐项测试。

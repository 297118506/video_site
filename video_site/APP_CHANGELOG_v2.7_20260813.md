# APP 更新日志

> 短视频播放客户端（Android · Jetpack Compose）

---

## v3.1 — 2026-08-17

### 新增
- **用户登录与权限管理**：设置页新增账号登录入口，支持用户名密码登录
  - 登录后服务端返回用户可见分类权限（长视频 / 短视频分别配置），APP 端按权限过滤分类列表
  - 权限为空表示全部可见（管理员）；权限非空时仅显示权限列表中的分类
  - 凭证（Basic Auth token）持久化到 DataStore，启动时自动恢复登录状态
- **短视频收藏功能**：播放界面进度条最右端上方新增半透明五角星收藏按钮
  - 未收藏：半透明白色描边五角星；已收藏：半透明金色实心五角星
  - 调用 `POST /api/v1/shorts/{id}/favorite` 切换收藏状态，采用乐观更新（先更新 UI，失败回滚）
  - 登录时自动从服务端同步收藏 ID 列表到本地
- **收藏列表界面**：底部导航栏新增"收藏"入口（位于短视频与搜索之间）
  - 列表样式展示已收藏的短视频（每行一个：标题 + 播放量 + 金色五角星）
  - 点击视频进入播放页，以收藏列表为播放队列，从点击的视频开始播放
  - 支持点击底部导航栏"收藏"按钮刷新列表（与首页、合集、短视频分类页一致）
  - 收藏/取消收藏后本地缓存自动同步，列表实时更新
- **按 videoIds 列表播放模式**：ShortsViewModel 新增 `initialVideoIds` 参数，用于收藏列表等场景按指定 ID 顺序播放

### 优化
- **底部导航栏样式统一**：短视频按钮从中央突出的特殊样式改为与其他按钮一致的 `BarItem` 样式（6 个按钮均匀分布）
- **APP 名称**：由"短视频"改为"镜中景"
- **未登录权限隔离**：未登录时首页和短视频分类页清空内容并显示"请先登录"提示 + 登录按钮，避免未授权访问

### 修复
- **已播完视频划回不重播**：视频自动播完后划回该视频时进度条卡在末尾不播放
  - 原因：`beyondViewportPageCount=1` 保留相邻页 ExoPlayer 实例的 `STATE_ENDED` 状态
  - 修复：页面重新激活时检测 `STATE_ENDED` 并 `seekTo(0L)` 重头播放
- **收藏列表只显示部分视频**：原仅请求第一页（perPage=500），收藏的视频不在前 500 条时被遗漏
  - 修复：改为循环分页拉取所有短视频后再过滤出已收藏的视频
- **收藏列表与标题栏重叠**：LazyColumn 顶部 padding 不足导致首行被标题栏遮挡
  - 修复：`contentPadding.top` 从 56dp 增至 72dp

### 涉及文件
| 文件 | 改动类型 |
|------|---------|
| `data/model/Models.kt` | 新增 `LoginRequest`、`LoginResponse`、`UserInfo`、`UserPermissions`、`UserCategoriesResponse`、`FavoriteResponse`、`FavoritesResponse` |
| `data/remote/ApiService.kt` | 新增 `login()`、`getUserCategories()`、`toggleFavorite()`、`getFavorites()` |
| `data/repository/VideoRepository.kt` | 新增对应仓库方法 |
| `data/local/SettingsStore.kt` | 新增 `UserAuthData`、`userAuth` Flow、`saveUserAuth()`、`favoriteIds` Flow、`setFavoriteIds()` |
| `ui/settings/SettingsViewModel.kt` | 新增登录/注销逻辑、登录状态管理 |
| `ui/settings/SettingsScreen.kt` | 新增账号登录 section（用户名密码输入 + 登录按钮 + 已登录状态显示） |
| `ui/home/HomeViewModel.kt` | 观察登录状态，未登录时清空数据，已登录按 `normalPerms` 过滤分类 |
| `ui/home/HomeScreen.kt` | 未登录时显示登录提示 |
| `ui/shorts/ShortsCategoriesViewModel.kt` | 观察登录状态，未登录时清空分类，已登录按 `shortPerms` 过滤分类 |
| `ui/shorts/ShortsCategoriesScreen.kt` | 未登录时显示登录提示（移除标题栏收藏入口按钮） |
| `ui/shorts/ShortsViewModel.kt` | 新增 `initialVideoIds` 模式、收藏状态管理、`toggleFavorite()` |
| `ui/shorts/ShortsScreen.kt` | 进度条右上方新增五角星收藏按钮、支持 `initialStartIndex` |
| `ui/shorts/FavoritesViewModel.kt` | 新建：收藏列表加载（循环分页）、本地同步、切换收藏 |
| `ui/shorts/FavoritesScreen.kt` | 新建：收藏列表界面（行样式，不显示封面） |
| `ui/components/VideoPlayer.kt` | `isPlaying=true` 时检测 `STATE_ENDED` 并 `seekTo(0)` |
| `ui/navigation/Routes.kt` | 新增 `SHORTS_FAVORITES`、`SHORTS_PLAY_BY_IDS` 路由及辅助方法 |
| `ui/navigation/DYNavHost.kt` | 新增收藏列表和按 IDs 播放的 composable、点击收藏 tab 刷新 |
| `ui/navigation/DYBottomBar.kt` | 新增"收藏"按钮、短视频按钮改为统一样式、删除 `CenterShortsButton` |
| `ui/AppViewModelProvider.kt` | 注册 `FavoritesViewModel` 工厂 |
| `DYApplication.kt` | 新增 `favoritesRefreshTick` |
| `res/values/strings.xml` | `app_name` 由"短视频"改为"镜中景" |
| `app/build.gradle.kts` | 版本号 3.0 → 3.1 |

---

## v3.0 — 2026-08-16

### 新增
- **短视频分类多选播放**：在分类界面长按任意分类卡片进入多选模式，可勾选多个分类后点击右下角悬浮按钮播放
  - 长按分类卡片 → 进入多选模式，该卡片被选中（白色边框 + 右上角蓝色勾选标记）
  - 多选模式中单击卡片 → 切换选中/取消选中
  - 右下角圆形半透明悬浮播放按钮（56dp，蓝色 70% 透明）→ 播放所有已选中分类的短视频
  - 顶部显示"已选 N 个分类"计数 + × 退出按钮
  - 单击播放（原功能）保持不变：非多选模式下单击卡片直接播放对应分类
- **多分类并行加载**：ViewModel 使用 `async`/`awaitAll` 并行请求多个分类的短视频列表，合并结果后统一播放

### 优化
- **分类名称标签样式**：底部进度条时长后的分类名改为细线方框包裹 + 淡蓝色背景（60% 透明），白色文字，`lineHeight` 等于 `fontSize` 使边框紧贴文字

### 涉及文件
| 文件 | 改动类型 |
|------|---------|
| `ui/navigation/Routes.kt` | `categoryId` → `categoryIds`（逗号分隔），`shortsPlay()` 接收 `List<Int>` |
| `ui/navigation/DYNavHost.kt` | 解析逗号分隔 `categoryIds`，回调签名改为 `List<Int>` |
| `ui/shorts/ShortsViewModel.kt` | `categoryId: Int` → `categoryIds: List<Int>`，并行请求合并 |
| `ui/shorts/ShortsCategoriesScreen.kt` | 新增多选模式、长按手势、选中标记、悬浮播放按钮 |
| `ui/shorts/ShortsScreen.kt` | 分类名称标签样式优化 |
| `app/build.gradle.kts` | 版本号 2.9 → 3.0 |

---

## v2.9 — 2026-08-14

### 优化
- **视频所属分类名称显示**：底部进度条左下角在时长后用 `·` 分隔显示当前播放视频自身所属的分类名称（如 `0:45 · 搞笑`）
  - 与顶部标题栏显示的"用户选择的播放分类名"区分：选择"全部"播放时，顶部显示"全部"，底部显示每个视频各自所属的分类
  - 通过展平 `ShortCategory` 父子树构建 `categoryId → name` 映射，查找每个视频的分类名

### 涉及文件
| 文件 | 改动类型 |
|------|---------|
| `ui/shorts/ShortsScreen.kt` | 新增 `categories` 参数传递、`categoryNameMap` 构建、底部显示视频所属分类名 |
| `app/build.gradle.kts` | 版本号 2.8 → 2.9 |

---

## v2.8 — 2026-08-13

### 修复
- **APP 后台继续播放**：APP 切到后台后短视频和长视频仍继续播放（有声音、耗电）
  - 在 `VideoPlayer` 组件中添加 `LifecycleEventObserver` 监听应用生命周期
  - `ON_STOP`（进入后台）：暂停播放并记录播放状态
  - `ON_START`（回到前台）：恢复播放（仅恢复切后台前正在播放的视频）
  - 短视频和长视频共用同一组件，一处修复覆盖两个播放器

### 优化
- **短视频切换黑屏优化**：切换到下一个视频时约 2 秒黑屏 → 降至 0.3-0.5 秒
  - **预缓冲**：分离 URL 和 isPlaying 逻辑，下一页进入组合时即开始预加载（利用 `beyondViewportPageCount=1`）
  - **保留缓冲数据**：非活跃页改为 `pause()` + `setVideoSurface(null)`，不再调用 `stop()` 丢弃已缓冲数据
  - **降低初始缓冲阈值**：`bufferForPlaybackMs` 从默认 2500ms 降至 500ms，`bufferForPlaybackAfterRebufferMs` 从 5000ms 降至 1000ms
- **消除 deprecated 警告**：`LocalLifecycleOwner` import 从 `androidx.compose.ui.platform` 迁移至 `androidx.lifecycle.compose`

### 涉及文件
| 文件 | 改动类型 |
|------|---------|
| `ui/components/VideoPlayer.kt` | 新增生命周期监听、预缓冲逻辑、自定义 LoadControl、迁移 import |
| `app/build.gradle.kts` | 版本号 2.7 → 2.8 |

---

## v2.7 — 2026-08-13

### 新增
- **蓝牙耳机 / 物理按键适配**：通过 `MediaSessionCompat` 完整适配蓝牙耳机媒体按键
  - 单击：播放 / 暂停切换
  - 双击（或 `KEYCODE_MEDIA_NEXT`）：切换到下一个短视频
  - 三击（或 `KEYCODE_MEDIA_PREVIOUS`）：切换到上一个短视频
  - 兼容有线耳机、蓝牙遥控器、物理键盘媒体按键

### 优化
- **随机排序算法**：使用 `SecureRandom` 替代 `java.util.Random`，提高随机性质量
- **加载更多时随机混合**：将"当前播放位置之后的剩余视频"与"新加载视频"合并后重新打乱，避免分批聚类
- **列表刷新时重排**：分类重置后重新加载的短视频列表会全量重新打乱，每轮顺序不同

### 修复
- **TextureView 画面穿透**：非活跃页面调用 `setVideoSurface(null)` 分离视频 Surface，彻底消除当前页底部显示下一页视频内容的渲染 Bug
- **暂停状态管理**：将 `isPaused` 状态从 `ShortVideoItem` 提升到 `ShortsPager` 层，使 `MediaSession` 回调与 UI 手势控制共享同一状态，切换视频时自动重置为播放状态

### 涉及文件
| 文件 | 改动类型 |
|------|---------|
| `app/build.gradle.kts` | 新增 `androidx.media:media:1.7.0` 依赖 |
| `ui/shorts/ShortsScreen.kt` | 新增 MediaSession、暂停状态提升、Surface 分离逻辑 |
| `ui/components/VideoPlayer.kt` | 非活跃页 `setVideoSurface(null)` 分离纹理 |

---

## v2.6 — 2026-08-12

### 优化
- 删除底部进度条时长后面的分类名称（避免与顶部标题栏重复）
- 横屏设备播放竖屏短视频时改用 `ResizeMode.Fit`（信箱模式，完整显示上下留黑边，不再裁剪）
- 播放页顶部标题栏显示 `分类名 · 已播 X / Y`

### 修复
- 无分类但有短视频时，分类列表页正常显示「全部」卡片（此前因空状态分支覆盖导致不显示）

### 涉及文件
| 文件 | 改动类型 |
|------|---------|
| `ui/shorts/ShortsScreen.kt` | 删除底部分类名、进度条显示、横屏 `ResizeMode` 判断 |
| `ui/shorts/ShortsCategoriesScreen.kt` | 空状态条件增加 `totalCount == 0` 判断 |
| `app/build.gradle.kts` | 版本号 2.5 → 2.6 |

---

## v2.5 — 2026-08-12

### 优化
- 底部进度条左下角时长信息后，用 `·` 分隔显示当前分类名称（如 `0:45 · 搞笑`）

### 涉及文件
| 文件 | 改动类型 |
|------|---------|
| `ui/shorts/ShortsScreen.kt` | 新增分类名显示 |
| `app/build.gradle.kts` | 版本号 2.4 → 2.5 |

---

## v2.4 — 2026-08-12

### 新增
- **服务端播放标记同步**：滑到新视频时自动调用 `POST /api/v1/shorts/{id}/play` 标记已播放
- **随机播放去重**：开启随机播放时调用 `GET /shorts?exclude_played=1` 拉取未播放列表
- **播放进度显示**：顶部标题栏显示 `分类名 · 已播 X / Y`
- **全部播放完重开机制**：服务端返回 `reset=true` 时 Toast 提示并刷新列表

### 涉及文件
| 文件 | 改动类型 |
|------|---------|
| `data/model/Models.kt` | 新增 `PlayMarkResponse`、`PlayMarkInfo`、`PlayedStatusResponse`、`ShortsExcludePlayedResponse` |
| `data/remote/ApiService.kt` | 新增 `markShortPlayed()`、`getPlayedStatus()`、`getShortsExcludePlayed()` |
| `data/repository/VideoRepository.kt` | 新增对应仓库方法 |
| `ui/shorts/ShortsViewModel.kt` | 重写，集成播放标记、随机去重加载、进度管理、事件流 |
| `ui/shorts/ShortsScreen.kt` | 播放时触发标记、顶部进度显示、Toast 事件处理 |
| `ui/navigation/DYNavHost.kt` | 适配 ShortsViewModel 新签名 |
| `app/build.gradle.kts` | 版本号 2.3 → 2.4 |

---

## v2.3 — 2026-08-12

### 版本升级
- 版本号从 2.2 → 2.3

---

## v2.2 — 2026-08-12

### 优化
- 进入短视频播放界面时**静音默认开启**，避免外放打扰
- 搜索界面删除关键词后，搜索结果列表一并清空（此前会保留旧结果）

### 涉及文件
| 文件 | 改动类型 |
|------|---------|
| `ui/shorts/ShortsScreen.kt` | `muted` 默认 `true` |
| `ui/search/SearchViewModel.kt` | `onQueryChange("")` 时清空 `results` 并重置状态 |
| `app/build.gradle.kts` | 版本号 2.1 → 2.2 |

---

## v2.1 — 2026-08-12

### 优化
- 分类界面随机播放开关**默认开启**

### 涉及文件
| 文件 | 改动类型 |
|------|---------|
| `ui/shorts/ShortsCategoriesScreen.kt` | `shuffleEnabled` 默认 `true` |
| `app/build.gradle.kts` | 版本号 2.0 → 2.1 |

---

## v2.0 — 2026-08-12

### 新增
- **短视频分类界面随机播放开关**：在点击分类卡片进入播放前可选择是否开启随机顺序

### 移除
- 删除视频播放界面中的随机播放按钮与相关规则（避免播放中途切换打乱顺序导致重复）

### 涉及文件
| 文件 | 改动类型 |
|------|---------|
| `ui/navigation/Routes.kt` | 新增 `shuffle` 路由参数 |
| `ui/navigation/DYNavHost.kt` | 解析并传递 `shuffle` 参数 |
| `ui/shorts/ShortsCategoriesScreen.kt` | 新增顶部随机播放开关胶囊按钮 |
| `ui/shorts/ShortsScreen.kt` | 移除底部随机按钮、接收外部 `shuffleEnabled` 参数 |
| `app/build.gradle.kts` | 版本号 1.0 → 2.0 |

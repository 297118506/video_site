/* ===== 图片导入（博客式）JS — 移植自 typecho_web/static/js/typecho.js ===== */

// ============ 全局状态 ============
let selectedCategories = new Set();
let currentPath = '/';
let currentAccount = null;       // 当前选中的 OpenList 账户（id, name, server_url）
let openlistAccounts = [];
let fileList = [];
let alistTabs = {};
let currentActiveTab = null;
let searchMatches = [];
let searchIndex = 0;
let replaceRules = [];
let replaceHistory = [];
let sourceMode = 'openlist';     // 'openlist' 或 'local'：文件源切换状态
let pathSep = '\\';                // 本地模式路径分隔符：从 browse_local 响应的 sep 字段初始化；Windows='\\'，POSIX='/'
let pathPlatform = 'windows';      // 本地模式运行平台：从 browse_local 响应的 platform 字段初始化

const IMAGE_EXTS = ['jpg','jpeg','png','gif','webp','bmp','svg','ico','tiff','tif','heic','avif'];
const VIDEO_EXTS = ['mp4','mkv','avi','mov','wmv','flv','webm','m4v','3gp','mpg','mpeg','ts','m2ts','mts','rmvb','rm','vob','asf','m3u8'];

// ============ 工具函数 ============
function isImage(name) { const ext = (name.split('.').pop() || '').toLowerCase(); return IMAGE_EXTS.indexOf(ext) !== -1; }
function isVideo(name) { const ext = (name.split('.').pop() || '').toLowerCase(); return VIDEO_EXTS.indexOf(ext) !== -1; }

function showAlert(message, type = 'success') {
    const tc = document.getElementById('toastContainer');
    if (!tc) { alert(message); return; }
    const div = document.createElement('div');
    div.className = `alert alert-${type} alert-dismissible fade show mb-1`;
    div.style.minWidth = '250px';
    div.style.boxShadow = '0 2px 8px rgba(0,0,0,0.15)';
    div.innerHTML = `<i class="bi bi-${type==='success'?'check-circle':type==='danger'?'x-circle':type==='warning'?'exclamation-triangle':'info-circle'} me-1"></i>${message}<button class="btn-close" data-bs-dismiss="alert"></button>`;
    tc.appendChild(div);
    setTimeout(() => { try { div.remove(); } catch(e){} }, 4000);
}

function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => showAlert('已复制到剪贴板')).catch(() => fallbackCopy(text));
    } else {
        fallbackCopy(text);
    }
}
function fallbackCopy(text) {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); showAlert('已复制到剪贴板'); } catch(e) { showAlert('复制失败', 'danger'); }
    document.body.removeChild(ta);
}

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ============ 页面初始化 ============
document.addEventListener('DOMContentLoaded', function() {
    try {
        console.log('图片导入页面初始化...');
        setupEventListeners();
        loadCategories();
        loadAlistAccounts();
        loadReplaceRules();
    } catch (e) {
        console.error('初始化失败:', e);
        showAlert('初始化失败: ' + e.message, 'danger');
    }
    window.addEventListener('resize', () => setTimeout(updateTabNavButtons, 100));
    document.addEventListener('mouseup', () => { stopTabScroll(); stopFileListScroll(); });
    document.addEventListener('touchend', () => { stopTabScroll(); stopFileListScroll(); });
    window.addEventListener('blur', () => { stopTabScroll(); stopFileListScroll(); });
});

function setupEventListeners() {
    document.getElementById('article-content').addEventListener('input', updatePreview);
    document.getElementById('article-title').addEventListener('input', () => { autoMatchCategory(); updatePvSummary(); });
    document.getElementById('article-title').addEventListener('keyup', autoMatchCategory);
    document.getElementById('article-title').addEventListener('change', autoMatchCategory);
    document.getElementById('album-description').addEventListener('input', updatePvSummary);
    document.getElementById('category-search').addEventListener('input', filterCategories);
    document.getElementById('file-search').addEventListener('input', filterFiles);
    document.getElementById('alist-account').addEventListener('change', switchAlistAccount);
    document.getElementById('toggle-categories').addEventListener('click', toggleCategories);
}

// ============ 分类树 ============
async function loadCategories() {
    try {
        const response = await fetch('/api/image_import/categories');
        const result = await response.json();
        if (!result.success) { showAlert('加载分类失败: ' + (result.message || ''), 'danger'); return; }
        renderCategoryTree(result.tree);
        // 分类加载完成后重新匹配一次，避免"标题先输入、分类后加载"导致匹配不上
        autoMatchCategory();
        updatePvSummary();
        showAlert('分类加载成功', 'success');
    } catch (e) {
        console.error('加载分类失败:', e);
        showAlert('加载分类失败: ' + e.message, 'danger');
    }
}

function renderCategoryTree(tree, parentElement = null, parentId = 0) {
    const container = parentElement || document.getElementById('category-tree');
    if (!parentElement) container.innerHTML = '';
    const categories = tree[parentId] || [];
    if (!categories.length) return;
    categories.forEach(cat => {
        const item = document.createElement('div');
        item.className = 'category-item';
        item.style.marginLeft = parentElement ? '20px' : '0px';
        item.innerHTML = `
            <div class="d-flex align-items-center">
                ${tree[cat.id] ? '<span class="expand-btn me-1" onclick="toggleCategory(this)">▶</span>' : '<span class="me-3"></span>'}
                <span class="category-name" data-id="${cat.id}" data-name="${escapeHtml(cat.name)}" onclick="selectCategory(${cat.id})" oncontextmenu="showCategoryContextMenu(event, ${cat.id}, '${escapeHtml(cat.name).replace(/'/g, "\\'")}')">${escapeHtml(cat.name)}</span>
            </div>
            <div class="children" style="display: none;"></div>
        `;
        container.appendChild(item);
        if (tree[cat.id]) renderCategoryTree(tree, item.querySelector('.children'), cat.id);
    });
}

function toggleCategory(btn) {
    const children = btn.parentElement.parentElement.querySelector('.children');
    if (children.style.display === 'none') { children.style.display = 'block'; btn.textContent = '▼'; }
    else { children.style.display = 'none'; btn.textContent = '▶'; }
}

function selectCategory(categoryId) {
    const el = document.querySelector(`.category-name[data-id="${categoryId}"]`);
    if (!el) return;
    if (selectedCategories.has(categoryId)) {
        selectedCategories.delete(categoryId);
        el.classList.remove('selected');
    } else {
        selectedCategories.add(categoryId);
        el.classList.add('selected');
        setTimeout(() => el.scrollIntoView({ behavior: 'smooth', block: 'center' }), 50);
    }
    updatePvSummary();
}

function updateSelectedCategories() {
    document.querySelectorAll('.category-name').forEach(el => el.classList.remove('selected'));
    selectedCategories.forEach(id => {
        const el = document.querySelector(`.category-name[data-id="${id}"]`);
        if (el) {
            el.classList.add('selected');
            const item = el.closest('.category-item');
            if (item && item.parentElement && item.parentElement.classList.contains('children')) {
                const parentItem = item.parentElement.parentElement;
                const children = parentItem.querySelector('.children');
                const expandBtn = parentItem.querySelector('.expand-btn');
                if (children && expandBtn) { children.style.display = 'block'; expandBtn.textContent = '▼'; }
            }
        }
    });
}

function toggleCategories() {
    const btn = document.getElementById('toggle-categories');
    const isExpanded = btn.textContent === '全部收起';
    document.querySelectorAll('.expand-btn').forEach(eb => {
        const children = eb.parentElement.parentElement.querySelector('.children');
        if (isExpanded) { children.style.display = 'none'; eb.textContent = '▶'; }
        else { children.style.display = 'block'; eb.textContent = '▼'; }
    });
    btn.textContent = isExpanded ? '全部展开' : '全部收起';
}

function filterCategories() {
    const keyword = document.getElementById('category-search').value.toLowerCase().trim();
    const allItems = document.querySelectorAll('.category-item');
    let matches = [];
    document.querySelectorAll('.category-name').forEach(n => n.style.backgroundColor = '');
    if (!keyword) {
        allItems.forEach(item => {
            item.style.display = 'block';
            const children = item.querySelector(':scope > .children');
            const expandBtn = item.querySelector(':scope > div .expand-btn');
            if (children && expandBtn) { children.style.display = 'none'; expandBtn.textContent = '▶'; }
        });
        window.categoryMatches = []; window.categoryMatchIndex = 0;
        updateCategoryNavButtons();
        return;
    }
    allItems.forEach(item => {
        item.style.display = 'block';
        const nameEl = item.querySelector(':scope > div .category-name');
        if (nameEl && nameEl.textContent.toLowerCase().includes(keyword)) {
            matches.push(item);
            let parent = item.parentElement;
            while (parent) {
                if (parent.classList.contains('category-item')) {
                    const children = parent.querySelector(':scope > .children');
                    const eb = parent.querySelector(':scope > div .expand-btn');
                    if (children && eb && children.contains(item)) { children.style.display = 'block'; eb.textContent = '▼'; }
                    break;
                }
                if (parent.classList.contains('children')) parent = parent.parentElement;
                else break;
            }
        }
    });
    window.categoryMatches = matches; window.categoryMatchIndex = 0;
    updateCategoryNavButtons();
    if (matches.length > 0) highlightCategoryMatch(0);
}

function updateCategoryNavButtons() {
    const prev = document.getElementById('category-prev'), next = document.getElementById('category-next');
    const matches = window.categoryMatches || [], idx = window.categoryMatchIndex || 0;
    prev.disabled = matches.length <= 1 || idx <= 0;
    next.disabled = matches.length <= 1 || idx >= matches.length - 1;
}

function highlightCategoryMatch(index) {
    const matches = window.categoryMatches || [];
    if (index < 0 || index >= matches.length) return;
    document.querySelectorAll('.category-name').forEach(n => {
        if (n.style.backgroundColor === 'rgb(255, 243, 205)' || n.style.backgroundColor === '#fff3cd') n.style.backgroundColor = '';
    });
    const cur = matches[index];
    const nameEl = cur.querySelector(':scope > div .category-name');
    if (nameEl) {
        nameEl.style.backgroundColor = '#fff3cd';
        cur.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    window.categoryMatchIndex = index;
    updateCategoryNavButtons();
}

function navigateCategorySearch(dir) {
    const matches = window.categoryMatches || [];
    if (matches.length <= 1) return;
    let idx = window.categoryMatchIndex || 0;
    let next = idx;
    if (dir === 'prev' && idx > 0) next = idx - 1;
    else if (dir === 'next' && idx < matches.length - 1) next = idx + 1;
    if (next !== idx) highlightCategoryMatch(next);
}

function autoMatchCategory() {
    const title = document.getElementById('article-title').value.trim();
    if (!title) { selectedCategories.clear(); updateSelectedCategories(); return; }
    const norm = normalizeText(title);
    selectedCategories.clear();
    let count = 0;
    const isSecondLevel = (el) => {
        const item = el.closest('.category-item');
        return item && item.parentElement && item.parentElement.classList.contains('children');
    };
    // 优先匹配二级分类（与 typecho_web 一致）
    document.querySelectorAll('.category-name').forEach(el => {
        if (!isSecondLevel(el)) return;
        const nc = normalizeText(el.textContent.trim());
        if (nc === norm || nc.includes(norm) || norm.includes(nc)) {
            const id = parseInt(el.getAttribute('data-id'));
            if (!isNaN(id)) { selectedCategories.add(id); count++; }
        }
    });
    // 未命中二级分类时降级匹配一级分类
    if (count === 0) {
        document.querySelectorAll('.category-name').forEach(el => {
            if (isSecondLevel(el)) return;
            const nc = normalizeText(el.textContent.trim());
            if (nc === norm || nc.includes(norm) || norm.includes(nc)) {
                const id = parseInt(el.getAttribute('data-id'));
                if (!isNaN(id)) { selectedCategories.add(id); count++; }
            }
        });
    }
    updateSelectedCategories();
    if (count > 0) flashSelected();
}

function flashSelected() {
    selectedCategories.forEach(id => {
        const el = document.querySelector(`.category-name[data-id="${id}"]`);
        if (!el) return;
        el.classList.add('match-flash');
        setTimeout(() => el.classList.remove('match-flash'), 600);
    });
}

// ============ 分类右键菜单（添加分类）—— 移植自 typecho_web ============
function handleCategoryContextMenu(event) {
    // 空白处右键 -> 添加一级分类
    if (!event.target.classList.contains('category-name')) {
        event.preventDefault();
        showCategoryContextMenu(event, null, null, 0);
    }
}

function showCategoryContextMenu(event, categoryId, categoryName, parentId) {
    event.preventDefault();
    event.stopPropagation();

    const existing = document.getElementById('category-context-menu');
    if (existing) existing.remove();

    const menu = document.createElement('div');
    menu.id = 'category-context-menu';
    menu.className = 'context-menu';
    menu.style.cssText = `position:fixed;top:${event.clientY}px;left:${event.clientX}px;`;

    const items = categoryId === null
        ? [{ text: '添加一级分类', action: () => addNewCategory(0) }]
        : [{ text: `添加子分类（"${categoryName}"下）`, action: () => addNewCategory(categoryId) }];

    items.forEach(it => {
        const mi = document.createElement('div');
        mi.className = 'context-menu-item';
        mi.textContent = it.text;
        mi.addEventListener('click', () => { it.action(); menu.remove(); });
        menu.appendChild(mi);
    });
    document.body.appendChild(menu);
    setTimeout(() => {
        document.addEventListener('click', function close(e) {
            if (!menu.contains(e.target)) { menu.remove(); document.removeEventListener('click', close); }
        });
    }, 0);
}

async function addNewCategory(parentId) {
    // 自定义输入对话框（与 typecho_web 一致，避免使用 prompt 影响视觉一致性）
    const name = await showCategoryInputDialog(parentId ? '请输入子分类名称：' : '请输入一级分类名称：');
    if (!name || !name.trim()) return;
    try {
        const resp = await fetch('/api/album_categories', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ name: name.trim(), parent_id: parentId })
        });
        const data = await resp.json();
        if (data.success) {
            showAlert('分类添加成功', 'success');
            await loadCategories();
        } else {
            showAlert('添加失败: ' + (data.message || ''), 'danger');
        }
    } catch (e) {
        showAlert('添加失败: ' + e.message, 'danger');
    }
}

function showCategoryInputDialog(message, defaultValue = '') {
    return new Promise((resolve) => {
        const dialog = document.createElement('div');
        dialog.style.cssText = `position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:#fff;padding:20px;border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,0.2);z-index:10000;min-width:300px;`;

        const msg = document.createElement('p');
        msg.textContent = message;
        msg.style.cssText = 'margin-bottom:15px;font-weight:600;';

        const input = document.createElement('input');
        input.type = 'text';
        input.value = defaultValue;
        input.style.cssText = 'width:100%;padding:8px;margin-bottom:15px;border:1px solid #ced4da;border-radius:4px;';

        const btnRow = document.createElement('div');
        btnRow.style.cssText = 'display:flex;justify-content:flex-end;gap:10px;';

        const cancel = document.createElement('button');
        cancel.textContent = '取消';
        cancel.style.cssText = 'padding:8px 16px;border:1px solid #ced4da;border-radius:4px;background:#f8f9fa;cursor:pointer;';

        const ok = document.createElement('button');
        ok.textContent = '确定';
        ok.style.cssText = 'padding:8px 16px;border:1px solid #007bff;border-radius:4px;background:#007bff;color:#fff;cursor:pointer;';

        cancel.addEventListener('click', () => { document.body.removeChild(dialog); resolve(null); });
        ok.addEventListener('click', () => { const v = input.value; document.body.removeChild(dialog); resolve(v); });
        input.addEventListener('keypress', e => { if (e.key === 'Enter') { const v = input.value; document.body.removeChild(dialog); resolve(v); } });

        btnRow.appendChild(cancel);
        btnRow.appendChild(ok);
        dialog.appendChild(msg);
        dialog.appendChild(input);
        dialog.appendChild(btnRow);
        document.body.appendChild(dialog);
        input.focus(); input.select();
    });
}

function normalizeText(text) {
    return (text || '').toLowerCase().replace(/[\s_\-\.]+/g, '');
}

// ============ 实时预览 ============
function updatePreview() {
    const content = document.getElementById('article-content').value;
    const previewEl = document.getElementById('preview-content');
    if (!content.trim()) { previewEl.innerHTML = '<p class="text-muted text-center">输入内容后此处实时显示渲染结果</p>'; updatePvSummary(); return; }
    let html;
    if (content.includes('<') && content.includes('>')) html = content;
    else html = markdownToHtml(content);
    previewEl.innerHTML = html;
    updatePvSummary();
}

function updatePvSummary() {
    const content = document.getElementById('article-content').value;
    const urls = extractUrls(content);
    const title = document.getElementById('article-title').value.trim();
    const summary = document.getElementById('pvSummary');
    const nP = urls.filter(u => isImage(u.name)).length;
    const nV = urls.filter(u => isVideo(u.name)).length;
    const nOther = urls.length - nP - nV;
    let html = '';
    if (urls.length === 0) html = `<i class="bi bi-bar-chart"></i> 图片&视频数量统计区`;
    else {
        const stats = (nP ? `<span class="pv-p">${nP}P</span>` : '') + (nV ? `<span class="pv-v">${nV}V</span>` : '');
        html = `<i class="bi bi-bar-chart"></i> 统计信息:        [${stats}${nOther?`<span class="text-warning">${nOther}?</span>`:''}] · 共 ${urls.length} 个媒体`;
    }
    if (selectedCategories.size > 0) html += ` · 已选 ${selectedCategories.size} 个分类`;
    summary.innerHTML = html;
    document.getElementById('publishBtn').disabled = !title || urls.length === 0;
}

function extractUrls(text) {
    // 健壮提取：支持 HTML src/href、Markdown 链接、纯文本 URL（每行一条或混排），去重保序
    const urls = [];
    const seen = new Set();
    const push = (u) => {
        u = (u || '').trim();
        if (!u) return;
        u = u.replace(/[)\].,;:]+$/, '');
        if (!u || seen.has(u)) return;
        seen.add(u);
        // basename 优先从 query 中 name= 取（本地预览 URL 无扩展名时用），否则取 URL 末尾文件名
        let name = '';
        try {
            const qmIdx = u.indexOf('?');
            if (qmIdx >= 0) {
                const qs = u.substring(qmIdx + 1);
                const m = qs.match(/(?:^|&)name=([^&]+)/);
                if (m) name = decodeURIComponent(m[1]);
            }
        } catch (e) {}
        if (!name) {
            const path = u.split('?')[0];
            name = path.split('/').pop() || u;
        }
        urls.push({ url: u, name });
    };
    if (!text) return urls;
    let m;
    // 1) HTML src/href 属性（<img src="..."> / <video src="...">）
    const srcRe = /(?:src|href)\s*=\s*["']([^"']+)["']/gi;
    while ((m = srcRe.exec(text)) !== null) push(m[1]);
    // 2) Markdown 链接（![alt](url) 或 [text](url)）
    const mdRe = /!?\[[^\]]*\]\(\s*(https?:\/\/[^)\s]+)/gi;
    while ((m = mdRe.exec(text)) !== null) push(m[1]);
    // 3) 纯文本 URL（每行一条或混排；括号内文件名如 (2).jpg 不被截断）
    const urlRe = /https?:\/\/[^\s"'<>]+/gi;
    while ((m = urlRe.exec(text)) !== null) push(m[0]);
    return urls;
}

function extractSortKey(url) {
    const name = (url.split('?')[0].split('/').pop()) || url;
    // 优先级 1: 括号内的数字 (NN)
    let m = name.match(/\((\d+)\)/);
    if (m) return [0, parseInt(m[1]), name];
    // 优先级 2: 文件名末尾的数字（带扩展名前缀）
    const dotIdx = name.lastIndexOf('.');
    const stem = dotIdx > 0 ? name.slice(0, dotIdx) : name;
    const nums = stem.match(/(\d+)/g);
    if (nums && nums.length) {
        const lastNum = nums[nums.length - 1];
        return [1, parseInt(lastNum), parseInt(lastNum).toString().length, name];
    }
    return [2, Infinity, 0, name];
}

// ============ 简单 Markdown 渲染 ============
function markdownToHtml(md) {
    if (!md) return '';
    // 抽图片 URL 行：把它们直接渲染成 img
    const lines = md.split(/\r?\n/);
    let html_out = '';
    let inPara = false;
    lines.forEach(line => {
        const trimmed = line.trim();
        if (!trimmed) { if (inPara) { html_out += '</p>'; inPara = false; } return; }
        const urlMatch = trimmed.match(/^(https?:\/\/\S+\.(?:jpg|jpeg|png|gif|webp|bmp|svg|ico|tiff|tif|heic|avif))\s*$/i);
        if (urlMatch) {
            if (inPara) { html_out += '</p>'; inPara = false; }
            html_out += `<img src="${escapeHtml(urlMatch[1])}" loading="lazy">`;
            return;
        }
        if (!inPara) { html_out += '<p>'; inPara = true; }
        html_out += escapeHtml(trimmed) + '<br>';
    });
    if (inPara) html_out += '</p>';
    return html_out;
}

// ============ 一键处理链接 ============
async function processLinks() {
    // 与 typecho_web 一致：每次从当前 OpenList 文件夹重新收集直链，而非依赖已有内容
    const includeVideos = document.getElementById('opt-include-videos').checked;
    const { items, folderName } = await gatherCurrentFolderItems();
    if (!items.length) { showAlert('当前文件夹没有可用的文件', 'warning'); return; }
    // 用 file.name 的扩展名判断类型（不再走 extractUrls 的纯文本 https?:// 正则——
    // 本地预览 URL 是相对路径会被原版完全吞掉，造成误报"没有可导入的图片"）
    const filtered = includeVideos ? items : items.filter(it => isImage(it.name));
    if (!filtered.length) { showAlert('当前文件夹没有可导入的图片', 'warning'); return; }
    // 用文件夹名设标题（仅当标题为空）+ 始终自动匹配分类（即使标题是之前留下的）
    if (folderName) {
        const titleInput = document.getElementById('article-title');
        titleInput.value = folderName;
        autoMatchCategory();
        updatePvSummary();
    }
    const imgUrls = filtered.filter(it => isImage(it.name));
    const vidUrls = includeVideos ? filtered.filter(it => isVideo(it.name)) : [];
    if (!imgUrls.length) { showAlert('没有图片 URL', 'warning'); return; }
    imgUrls.sort((a, b) => {
        const ka = extractSortKey(a.name), kb = extractSortKey(b.name);
        for (let i = 0; i < Math.min(ka.length, kb.length); i++) {
            if (ka[i] !== kb[i]) return ka[i] < kb[i] ? -1 : 1;
        }
        return 0;
    });
    // 首图独立 + 剩余双排（typecho_web format_images 风格）
    const first = imgUrls[0];
    const rest = imgUrls.slice(1);
    let html = `<table style="border-collapse:collapse;width:100%;">`;
    html += `<tr><td colspan="2" style="text-align:center;"><img src="${escapeHtml(first.url)}" style="max-width:800px;width:100%;" loading="lazy"></td></tr>`;
    for (let i = 0; i < rest.length; i += 2) {
        html += `<tr>`;
        const l = rest[i], r = rest[i + 1];
        html += `<td style="width:50%;padding:2px;"><img src="${escapeHtml(l.url)}" style="width:100%;display:block;" loading="lazy"></td>`;
        if (r) html += `<td style="width:50%;padding:2px;"><img src="${escapeHtml(r.url)}" style="width:100%;display:block;" loading="lazy"></td>`;
        else html += `<td style="width:50%;"></td>`;
        html += `</tr>`;
    }
    html += `</table>`;
    if (vidUrls.length) {
        html += `<p style="text-align:center;color:#666;">视频列表：</p>`;
        vidUrls.forEach(v => { html += `<p style="text-align:center;"><video src="${escapeHtml(v.url)}" controls style="max-width:800px;width:100%;"></video></p>`; });
    }
    document.getElementById('article-content').value = html;
    updatePreview();
    showAlert(`处理完成：首图 + ${rest.length} 张双排 + ${vidUrls.length} 个视频`);
}

async function processLinksDouble() {
    // 与 typecho_web 一致：每次从当前 OpenList 文件夹重新收集直链，而非依赖已有内容
    const includeVideos = document.getElementById('opt-include-videos').checked;
    const { items, folderName } = await gatherCurrentFolderItems();
    if (!items.length) { showAlert('当前文件夹没有可用的文件', 'warning'); return; }
    // 用 file.name 判类型，避开 extractUrls 对本地相对 URL 的吞链接问题
    const filtered = includeVideos ? items : items.filter(it => isImage(it.name));
    if (!filtered.length) { showAlert('当前文件夹没有可导入的图片', 'warning'); return; }
    // 用文件夹名设标题（仅当标题为空）+ 始终自动匹配分类（即使标题是之前留下的）
    if (folderName) {
        const titleInput = document.getElementById('article-title');
        titleInput.value = folderName;
        autoMatchCategory();
        updatePvSummary();
    }
    const imgUrls = filtered.filter(it => isImage(it.name));
    const vidUrls = includeVideos ? filtered.filter(it => isVideo(it.name)) : [];
    if (!imgUrls.length) { showAlert('没有图片 URL', 'warning'); return; }
    imgUrls.sort((a, b) => {
        const ka = extractSortKey(a.name), kb = extractSortKey(b.name);
        for (let i = 0; i < Math.min(ka.length, kb.length); i++) {
            if (ka[i] !== kb[i]) return ka[i] < kb[i] ? -1 : 1;
        }
        return 0;
    });
    let html = `<table style="border-collapse:collapse;width:100%;">`;
    for (let i = 0; i < imgUrls.length; i += 2) {
        html += `<tr>`;
        const l = imgUrls[i], r = imgUrls[i + 1];
        html += `<td style="width:50%;padding:2px;"><img src="${escapeHtml(l.url)}" style="width:100%;display:block;" loading="lazy"></td>`;
        if (r) html += `<td style="width:50%;padding:2px;"><img src="${escapeHtml(r.url)}" style="width:100%;display:block;" loading="lazy"></td>`;
        else html += `<td style="width:50%;"></td>`;
        html += `</tr>`;
    }
    html += `</table>`;
    if (vidUrls.length) {
        html += `<p style="text-align:center;color:#666;">视频列表：</p>`;
        vidUrls.forEach(v => { html += `<p style="text-align:center;"><video src="${escapeHtml(v.url)}" controls style="max-width:800px;width:100%;"></video></p>`; });
    }
    document.getElementById('article-content').value = html;
    updatePreview();
    showAlert(`纯双排处理完成：${imgUrls.length} 张图${vidUrls.length ? ' + ' + vidUrls.length + ' 个视频' : ''}`);
}

function clearContent() {
    if (!confirm('确认清空当前内容？')) return;
    document.getElementById('article-content').value = '';
    document.getElementById('preview-content').innerHTML = '<p class="text-muted text-center">输入内容后此处实时显示渲染结果</p>';
    updatePvSummary();
}

// ============ OpenList 账户管理 ============
const LAST_OPENLIST_ACCOUNT_KEY = 'imageImportLastOpenlistAccount';

// ============ 源切换（OpenList / 本地磁盘） ============
function setSourceMode(mode) {
    if (mode === sourceMode) return;
    sourceMode = mode;
    // 两行控制行互斥显隐：OpenList 模式显示账户/管理/切换；本地磁盘模式显示模式标签/提示/切换
    const openlistRow = document.getElementById('openlist-control-row');
    const localRow = document.getElementById('local-mode-row');
    if (mode === 'local') {
        openlistRow?.classList.add('source-mode-hidden');
        localRow?.classList.remove('source-mode-hidden');
    } else {
        openlistRow?.classList.remove('source-mode-hidden');
        localRow?.classList.add('source-mode-hidden');
    }
    // 重置文件列表（清空标签页，从新源重新加载）
    alistTabs = {};
    currentActiveTab = null;
    currentPath = (mode === 'local') ? '' : '/';
    fileList = [];
    const rootTabId = 'alist-tab-root';
    createAlistTab(rootTabId, mode === 'local' ? '本地磁盘' : '根目录', currentPath, true);
}

async function loadAlistAccounts() {
    try {
        const response = await fetch('/api/openlist/accounts');
        const data = await response.json();
        openlistAccounts = data.accounts || [];
        const select = document.getElementById('alist-account');
        select.innerHTML = '<option value="">选择 OpenList 账户</option>';
        openlistAccounts.forEach(acc => {
            const opt = document.createElement('option');
            opt.value = acc.id;
            opt.textContent = `${acc.name} (${acc.server_url})`;
            select.appendChild(opt);
        });
        if (openlistAccounts.length === 0) {
            document.getElementById('file-list').innerHTML = '<p class="text-muted text-center mt-3">请先配置 OpenList 账户</p>';
        } else {
            // 恢复上次选择的账户（仍在账户列表中时自动选中）
            const saved = localStorage.getItem(LAST_OPENLIST_ACCOUNT_KEY);
            if (saved && openlistAccounts.find(a => String(a.id) === String(saved))) {
                select.value = saved;
                switchAlistAccount();
            }
        }
    } catch (e) {
        console.error('加载 OpenList 账户失败:', e);
    }
}

function switchAlistAccount() {
    const select = document.getElementById('alist-account');
    const accId = select.value;
    if (!accId) return;
    currentAccount = openlistAccounts.find(a => a.id == accId);
    if (!currentAccount) return;
    // 记住本次选择
    try { localStorage.setItem(LAST_OPENLIST_ACCOUNT_KEY, accId); } catch (e) {}
    currentPath = '/';
    alistTabs = {};
    currentActiveTab = null;
    const rootTabId = 'alist-tab-root';
    createAlistTab(rootTabId, '根目录', '/', true);
}

async function manageAlistAccounts() {
    await loadAlistAccounts();
    renderOpenlistAccountList();
    const modal = new bootstrap.Modal(document.getElementById('openlistAccountModal'));
    modal.show();
}

function renderOpenlistAccountList() {
    const container = document.getElementById('openlist-account-list');
    container.innerHTML = '';
    if (!openlistAccounts.length) { container.innerHTML = '<p class="text-muted text-center">暂无账户，请点击"添加账户"</p>'; return; }
    openlistAccounts.forEach(acc => {
        const div = document.createElement('div');
        div.className = 'card mb-2';
        div.innerHTML = `
            <div class="card-body py-2">
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <h6 class="mb-1">${escapeHtml(acc.name)}</h6>
                        <small class="text-muted">${escapeHtml(acc.server_url)} · ${escapeHtml(acc.username || '')}</small>
                    </div>
                    <div>
                        <button class="btn btn-sm btn-outline-danger" onclick="deleteOpenlistAccount(${acc.id})">删除</button>
                    </div>
                </div>
            </div>`;
        container.appendChild(div);
    });
}

function addOpenlistAccount() {
    document.getElementById('openlist-account-form').style.display = 'block';
}

async function submitNewAccount() {
    const name = document.getElementById('new-acc-name').value.trim();
    const url = document.getElementById('new-acc-url').value.trim();
    const user = document.getElementById('new-acc-user').value.trim();
    const pwd = document.getElementById('new-acc-pwd').value;
    if (!name || !url || !user || !pwd) { showAlert('请填写完整账户信息', 'warning'); return; }
    try {
        const resp = await fetch('/api/openlist/accounts', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name, server_url: url, username: user, password: pwd})
        });
        const data = await resp.json();
        if (data.success) {
            showAlert('账户添加成功');
            document.getElementById('new-acc-name').value = '';
            document.getElementById('new-acc-url').value = '';
            document.getElementById('new-acc-user').value = '';
            document.getElementById('new-acc-pwd').value = '';
            document.getElementById('openlist-account-form').style.display = 'none';
            await loadAlistAccounts();
            renderOpenlistAccountList();
        } else {
            showAlert('添加失败: ' + (data.message || ''), 'danger');
        }
    } catch (e) {
        showAlert('添加失败: ' + e.message, 'danger');
    }
}

async function deleteOpenlistAccount(id) {
    if (!confirm('确定删除该账户？')) return;
    try {
        const resp = await fetch(`/api/openlist/accounts/${id}`, {method: 'DELETE'});
        const data = await resp.json();
        if (data.success) {
            showAlert('已删除');
            await loadAlistAccounts();
            renderOpenlistAccountList();
            if (currentAccount && currentAccount.id == id) { currentAccount = null; document.getElementById('file-list').innerHTML = '<p class="text-muted text-center mt-3">请选择 OpenList 账户</p>'; }
        } else { showAlert('删除失败: ' + (data.message || ''), 'danger'); }
    } catch (e) { showAlert('删除失败: ' + e.message, 'danger'); }
}

// ============ 多标签页 ============
function createAlistTab(tabId, tabName, path, switchTo = true) {
    // 本地模式按 path 去重（同一本地路径不重复开标签）；OpenList 模式按 (account, path) 去重
    for (let k in alistTabs) {
        const t = alistTabs[k];
        if (sourceMode === 'local') {
            if (t.path === path) { if (switchTo) switchToAlistTab(k); return; }
        } else {
            if (t.path === path && t.account && currentAccount && t.account.id === currentAccount.id) {
                if (switchTo) switchToAlistTab(k);
                return;
            }
        }
    }
    alistTabs[tabId] = { id: tabId, name: tabName, path: path, account: (sourceMode === 'openlist' ? currentAccount : null), files: [], scrollPosition: 0, selectedFile: null };
    renderAlistTabs();
    if (switchTo) switchToAlistTab(tabId);
    else loadTabFileList(tabId);
}

function renderAlistTabs() {
    const tabs = document.getElementById('alist-tabs');
    if (!tabs) return;
    tabs.innerHTML = '';
    if (Object.keys(alistTabs).length === 0 && currentAccount) {
        alistTabs['alist-tab-root'] = { id: 'alist-tab-root', name: '根目录', path: '/', account: currentAccount, files: [], scrollPosition: 0, selectedFile: null };
        currentActiveTab = 'alist-tab-root';
    }
    Object.values(alistTabs).forEach(tab => {
        const t = document.createElement('div');
        t.className = `alist-tab ${tab.id === currentActiveTab ? 'active' : ''}`;
        t.setAttribute('data-tab-id', tab.id);
        let dn = tab.name;
        if (dn.length > 6) dn = dn.substring(0, 6) + '...';
        t.innerHTML = `
            <span class="alist-tab-name" title="${escapeHtml(tab.name)}">${escapeHtml(dn)}</span>
            ${Object.keys(alistTabs).length > 1 ? `<button class="alist-tab-close" onclick="event.stopPropagation();closeAlistTab('${tab.id}')" title="关闭">×</button>` : ''}
        `;
        t.addEventListener('click', () => switchToAlistTab(tab.id));
        tabs.appendChild(t);
    });
    setTimeout(updateTabNavButtons, 10);
}

function switchToAlistTab(tabId) {
    if (!alistTabs[tabId]) return;
    saveCurrentTabScrollPosition();
    currentActiveTab = tabId;
    const tab = alistTabs[tabId];
    currentPath = tab.path;
    // 本地模式不修改 currentAccount；OpenList 模式才覆盖
    if (sourceMode === 'openlist') currentAccount = tab.account;
    renderAlistTabs();
    if (!tab.files || !tab.files.length) loadTabFileList(tabId);
    else { renderFileList(tab.files); restoreTabScrollPosition(tabId); }
}

function closeAlistTab(tabId) {
    if (Object.keys(alistTabs).length <= 1) return;
    let target = null;
    if (currentActiveTab === tabId) {
        const ids = Object.keys(alistTabs), idx = ids.indexOf(tabId);
        target = idx > 0 ? ids[idx - 1] : (ids.length > 1 ? ids[1] : null);
    }
    delete alistTabs[tabId];
    if (currentActiveTab === tabId && target) switchToAlistTab(target);
    else renderAlistTabs();
}

async function loadTabFileList(tabId) {
    const tab = alistTabs[tabId];
    if (!tab) return;
    // 本地模式不依赖 tab.account；OpenList 模式必须有 account
    if (sourceMode === 'openlist' && !tab.account) return;
    try {
        if (currentActiveTab === tabId) {
            document.getElementById('file-list').innerHTML = '<div class="text-center p-3"><div class="spinner-border spinner-border-sm text-primary"></div><br><small class="text-muted">加载中...</small></div>';
        }
        let url, body;
        if (sourceMode === 'local') {
            url = '/api/image_import/browse_local';
            body = {path: tab.path || '', include_videos: true};
        } else {
            url = '/api/image_import/browse_openlist';
            body = {account_id: tab.account.id, path: tab.path, include_videos: true};
        }
        const resp = await fetch(url, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body)
        });
        const data = await resp.json();
        if (!data.success) {
            if (currentActiveTab === tabId) document.getElementById('file-list').innerHTML = `<p class="text-danger text-center mt-3">${data.message || '加载失败'}</p>`;
            return;
        }
        // 本地模式：从响应里同步 sep 与 platform（首次响应决定，后续一致）
        if (sourceMode === 'local') {
            if (data.sep) pathSep = data.sep;
            if (data.platform) pathPlatform = data.platform;
        }
        tab.files = data.items;
        if (currentActiveTab === tabId) {
            renderFileList(data.items);
            restoreTabScrollPosition(tabId);
        }
    } catch (e) {
        if (currentActiveTab === tabId) document.getElementById('file-list').innerHTML = `<p class="text-danger text-center mt-3">网络错误: ${e.message}</p>`;
    }
}

function saveCurrentTabScrollPosition() {
    if (!currentActiveTab || !alistTabs[currentActiveTab]) return;
    const fl = document.getElementById('file-list');
    if (fl) alistTabs[currentActiveTab].scrollPosition = fl.scrollTop;
}

function restoreTabScrollPosition(tabId) {
    if (!alistTabs[tabId]) return;
    const fl = document.getElementById('file-list');
    if (!fl) return;
    setTimeout(() => { fl.scrollTop = alistTabs[tabId].scrollPosition || 0; updateScrollButtons(); }, 0);
}

// ============ 标签页滚动 ============
let tabScrollInterval = null, tabScrollTimeout = null;
function scrollTabs(dir) {
    const tabs = document.getElementById('alist-tabs');
    if (!tabs) return;
    const amount = 100, cur = tabs.scrollLeft;
    if (dir === 'prev') tabs.scrollLeft = Math.max(0, cur - amount);
    else { const max = tabs.scrollWidth - tabs.clientWidth; tabs.scrollLeft = Math.min(max, cur + amount); }
    setTimeout(updateTabNavButtons, 100);
}
function startTabScroll(dir) { event.preventDefault(); scrollTabs(dir); tabScrollTimeout = setTimeout(() => { tabScrollInterval = setInterval(() => scrollTabs(dir), 150); }, 500); }
function stopTabScroll() { if (tabScrollTimeout) clearTimeout(tabScrollTimeout); if (tabScrollInterval) clearInterval(tabScrollInterval); tabScrollTimeout = tabScrollInterval = null; }
function updateTabNavButtons() {
    const tabs = document.getElementById('alist-tabs'), nav = document.getElementById('alist-tabs-nav');
    const prev = document.getElementById('prev-tab-btn'), next = document.getElementById('next-tab-btn');
    if (!tabs || !nav || !prev || !next) return;
    const diff = tabs.scrollWidth - tabs.clientWidth;
    if (diff > 5) { nav.style.display = 'flex'; prev.disabled = tabs.scrollLeft <= 1; next.disabled = tabs.scrollLeft >= diff - 1; }
    else { nav.style.display = 'none'; tabs.scrollLeft = 0; }
}

// ============ 文件列表 ============
function renderFileList(files) {
    const container = document.getElementById('file-list');
    container.innerHTML = '';
    if (!files || !files.length) { container.innerHTML = '<p class="text-muted text-center mt-3">该目录为空</p>'; setTimeout(updateScrollButtons, 10); return; }
    files.forEach((file, index) => {
        const item = document.createElement('div');
        item.className = 'file-item';
        item.setAttribute('data-index', index);
        const isFolder = file.type === 1 || file.is_dir;
        const dn = isFolder ? `[文件夹] ${file.name}` : file.name;
        item.innerHTML = `<span class="${isFolder ? 'folder-item' : ''}">${escapeHtml(dn)}</span>`;
        item.addEventListener('click', () => {
            if (isFolder) {
                // 本地模式：优先用 file.path（后端 entry.path，是绝对路径）
                // 只有 file.path 缺失时才按 currentPath + file.name 拼接
                let newPath;
                if (sourceMode === 'local') {
                    if (file.path) {
                        newPath = file.path;
                    } else if (!currentPath) {
                        newPath = file.name;
                    } else {
                        const base = currentPath.replace(/[\\/]+$/, '');
                        newPath = base + pathSep + file.name;
                    }
                } else {
                    newPath = currentPath.replace(/\/$/, '') + '/' + file.name;
                }
                if (currentActiveTab && alistTabs[currentActiveTab]) {
                    saveCurrentTabScrollPosition();
                    alistTabs[currentActiveTab].path = newPath;
                    alistTabs[currentActiveTab].name = file.name;
                    alistTabs[currentActiveTab].files = [];
                    alistTabs[currentActiveTab].scrollPosition = 0;
                    renderAlistTabs();
                }
                currentPath = newPath;
                loadTabFileList(currentActiveTab);
            } else {
                copyFileLink(file);
            }
        });
        item.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            clearFileHighlight();
            item.classList.add('right-click-selected');
            showFileContextMenu(e, file);
        });
        container.appendChild(item);
    });
    setTimeout(() => {
        updateScrollButtons();
        const fl = document.getElementById('file-list');
        if (fl && !fl.hasScrollListener) {
            fl.addEventListener('scroll', () => { updateScrollButtons(); saveCurrentTabScrollPosition(); });
            fl.hasScrollListener = true;
        }
    }, 10);
}

function clearFileHighlight() {
    document.querySelectorAll('.file-item.right-click-selected').forEach(i => i.classList.remove('right-click-selected'));
}

function showFileContextMenu(event, file) {
    const existing = document.querySelector('.file-context-menu');
    if (existing) existing.remove();
    const menu = document.createElement('div');
    menu.className = 'file-context-menu context-menu';
    menu.style.cssText = `position:fixed;left:${event.clientX}px;top:${event.clientY}px;`;
    // 与 typecho_web 一致：文件夹右键显示"在新标签页中打开"，文件右键显示"复制链接"
    const isFolder = file.type === 1 || file.is_dir;
    const items = isFolder
        ? [{ text: '在新标签页中打开', action: () => openFolderInNewTab(file) }]
        : [{ text: '复制链接', action: () => copyFileLink(file) }];
    items.forEach(it => {
        const mi = document.createElement('div');
        mi.className = 'context-menu-item';
        mi.textContent = it.text;
        mi.addEventListener('click', () => { it.action(); menu.remove(); });
        menu.appendChild(mi);
    });
    document.body.appendChild(menu);
    setTimeout(() => { document.addEventListener('click', function close(e) { if (!menu.contains(e.target)) { menu.remove(); document.removeEventListener('click', close); } }); }, 0);
}

// 在新标签页中打开文件夹（后台加载，不切换当前标签页）
function openFolderInNewTab(folder) {
    let newPath;
    if (sourceMode === 'local') {
        if (folder.path) {
            newPath = folder.path;
        } else if (!currentPath) {
            newPath = folder.name;
        } else {
            const base = currentPath.replace(/[\\/]+$/, '');
            newPath = base + pathSep + folder.name;
        }
    } else {
        newPath = currentPath.replace(/\/$/, '') + '/' + folder.name;
    }
    const tabId = 'alist-tab-' + Date.now();
    createAlistTab(tabId, folder.name, newPath, false);
}

async function copyFileLink(file) {
    if (sourceMode === 'local') {
        // 本地模式：直接拼 preview URL，无需后端转直链
        const url = _localPreviewUrl(file);
        appendToContent(url);
        showAlert(`已复制本地预览链接：${file.name}`);
        return;
    }
    if (!currentAccount) return;
    const filePath = currentPath.replace(/\/$/, '') + '/' + file.name;
    try {
        const resp = await fetch('/api/image_import/file_link', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({account_id: currentAccount.id, file_path: filePath})
        });
        const data = await resp.json();
        if (data.error || !data.success) { showAlert('获取链接失败: ' + (data.message || data.error || ''), 'danger'); return; }
        // 追加到内容区而不是覆盖
        appendToContent(data.link);
        showAlert(`已复制直链：${file.name}`);
    } catch (e) { showAlert('复制失败: ' + e.message, 'danger'); }
}

function appendToContent(link) {
    const ta = document.getElementById('article-content');
    const cur = ta.value;
    if (cur && !cur.endsWith('\n')) ta.value = cur + '\n' + link + '\n';
    else ta.value = cur + link + '\n';
    updatePreview();
}

// 收集当前 OpenList 活动标签页/目录下所有文件的 URL 与文件名
// 返回 items: [{name, url}]（带 name 才能用 isImage/isVideo 按扩展名判类型，避开
// extractUrls 对纯文本 https?:// URL 的依赖——本地模式的 /api/local_import/preview 相对 URL
// 会被原版 extractUrls 完全忽略，导致所有本地预览链接被吞掉、"当前文件夹没有可导入的图片"误报）
async function gatherCurrentFolderItems() {
    let activeFileList = fileList, activePath = currentPath, activeAccount = currentAccount;
    if (currentActiveTab && alistTabs[currentActiveTab]) {
        const t = alistTabs[currentActiveTab];
        activeFileList = t.files || [];
        activePath = t.path;
        activeAccount = t.account;
    }
    // 本地模式：folderName 取路径最后一段（如 D:\Photos\Folder → Folder；驱动器根取驱动器字母）
    const folderName = sourceMode === 'local'
        ? _localFolderName(activePath)
        : (activePath && activePath !== '/' ? String(activePath).replace(/\/$/, '').split('/').pop() : '');
    if (sourceMode === 'openlist' && (!activeAccount || !activeFileList.length)) return { items: [], folderName, activePath };
    if (sourceMode === 'local' && !activeFileList.length) return { items: [], folderName, activePath };
    const items = [];
    for (const f of activeFileList) {
        if (f.type === 1 || f.is_dir) continue;
        if (sourceMode === 'local') {
            // 本地模式：直接拼 /api/local_import/preview?path=<encoded>&name=<basename>
            // 走服务端 send_file 流（admin 鉴权）；name= 用于服务端 _classify_url 识别扩展名
            items.push({ name: f.name, url: _localPreviewUrl(f) });
        } else {
            const fp = activePath.replace(/\/$/, '') + '/' + f.name;
            try {
                const resp = await fetch('/api/image_import/file_link', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({account_id: activeAccount.id, file_path: fp})
                });
                const data = await resp.json();
                if (data.success && data.link) items.push({ name: f.name, url: data.link });
            } catch (e) {}
        }
    }
    return { items, folderName, activePath };
}

// 本地预览 URL 拼接：path=<encoded>&name=<basename>
// 本地预览 URL 拼接：优先用 file.path（服务端 entry.path）；无 path 时按 pathSep 拼
function _localPreviewUrl(file) {
    let fp;
    if (file.path) {
        fp = file.path;
    } else {
        const base = currentPath ? currentPath.replace(/[\\/]+$/, '') : '';
        fp = base ? base + pathSep + file.name : file.name;
    }
    return '/api/local_import/preview?path=' + encodeURIComponent(fp) + '&name=' + encodeURIComponent(file.name);
}

// 本地模式 folderName：从绝对路径取最后一段；驱动器根 (D:\) 取驱动器字母
function _localFolderName(path) {
    if (!path) return '';
    const cleaned = String(path).replace(/[\\/]+$/, '');
    const isDriveRoot = /^[A-Za-z]:[\\/]?$/.test(cleaned);
    if (isDriveRoot) return cleaned.replace(/[:\\/]/g, '');
    const parts = cleaned.split(/[\\/]/).filter(p => p);
    return parts.length ? parts[parts.length - 1] : cleaned;
}

async function copyAllLinks() {
    const { items, folderName } = await gatherCurrentFolderItems();
    if (!items.length) { showAlert('没有可复制的文件', 'warning'); return; }
    appendToContent(items.map(it => it.url).join('\n'));
    // 自动用文件夹名作标题（仅当标题为空）+ 始终自动匹配分类
    if (folderName) {
        const titleInput = document.getElementById('article-title');
        titleInput.value = folderName;
        autoMatchCategory();
        updatePvSummary();
    }
    showAlert(`已追加 ${items.length} 个直链到内容区`);
}

function goUpDirectory() {
    // 本地模式：
    //   Windows (pathPlatform='windows')：currentPath 是 'X:\\foo\\bar' 或 'X:\\'；盘符根 → ''（驱动器列表）；其它上移一级
    //   POSIX (pathPlatform='linux'|'darwin')：currentPath 是 '/home/user/Pictures' 或 '/'；'/' 已是根无上级
    // OpenList 模式：currentPath 是 / 开头的路径，按 / 分割保持原行为
    if (sourceMode === 'local') {
        if (!currentPath) return;
        // POSIX：'/' 是文件系统根，无上级
        if (pathPlatform !== 'windows' && currentPath === '/') return;
        // Windows 盘符根（X:\\）→ 驱动器列表（''）
        if (pathPlatform === 'windows' && new RegExp('^[A-Za-z]:' + pathSep.replace('\\', '\\\\') + '$').test(currentPath)) {
            const newPath = '';
            if (currentActiveTab && alistTabs[currentActiveTab]) {
                saveCurrentTabScrollPosition();
                alistTabs[currentActiveTab].path = newPath;
                alistTabs[currentActiveTab].files = [];
                alistTabs[currentActiveTab].scrollPosition = 0;
                alistTabs[currentActiveTab].name = '本地磁盘';
            }
            currentPath = newPath;
            loadTabFileList(currentActiveTab);
            if (currentActiveTab) renderAlistTabs();
            return;
        }
        // 一般路径上移一级（按 pathSep 分割；兼容 [\\/] 混合）
        const parts = currentPath.split(/[\\/]/).filter(p => p.length > 0);
        // POSIX 根 '/' split 后是 ['']，filter 后是 []，特殊处理：保持 '/'
        if (pathPlatform !== 'windows' && currentPath.startsWith('/')) {
            const newPath = '/' + parts.join('/');
            if (newPath === '/') return;  // 已经在根
            if (currentActiveTab && alistTabs[currentActiveTab]) {
                saveCurrentTabScrollPosition();
                alistTabs[currentActiveTab].path = newPath;
                alistTabs[currentActiveTab].files = [];
                alistTabs[currentActiveTab].scrollPosition = 0;
                alistTabs[currentActiveTab].name = parts[parts.length - 1] || '本地磁盘';
            }
            currentPath = newPath;
            loadTabFileList(currentActiveTab);
            if (currentActiveTab) renderAlistTabs();
            return;
        }
        // Windows：上移一级到驱动盘根（X:\\）时回到驱动器列表
        parts.pop();
        const newPath = parts.join(pathSep);
        // 如果只剩盘符字母 'X:'，规范化为 'X:\\'
        const finalPath = /^([A-Za-z]):$/.test(newPath) ? newPath.replace(/^([A-Za-z]):$/, '$1' + pathSep) : (newPath || '');
        if (currentActiveTab && alistTabs[currentActiveTab]) {
            saveCurrentTabScrollPosition();
            alistTabs[currentActiveTab].path = finalPath;
            alistTabs[currentActiveTab].files = [];
            alistTabs[currentActiveTab].scrollPosition = 0;
            alistTabs[currentActiveTab].name = finalPath === '' ? '本地磁盘' : finalPath.split(/[\\/]/).pop();
        }
        currentPath = finalPath;
        loadTabFileList(currentActiveTab);
        if (currentActiveTab) renderAlistTabs();
        return;
    }
    // OpenList 模式（原逻辑保持不变）
    if (currentPath === '/' || currentPath === '') return;
    const parts = currentPath.replace(/\/$/, '').split('/'); parts.pop();
    const newPath = parts.join('/') || '/';
    if (currentActiveTab && alistTabs[currentActiveTab]) {
        saveCurrentTabScrollPosition();
        alistTabs[currentActiveTab].path = newPath;
        alistTabs[currentActiveTab].files = [];
        alistTabs[currentActiveTab].scrollPosition = 0;
        alistTabs[currentActiveTab].name = newPath === '/' ? '根目录' : newPath.split('/').pop();
    }
    currentPath = newPath;
    loadTabFileList(currentActiveTab);
    if (currentActiveTab) renderAlistTabs();
}

// ============ 文件搜索 ============
function filterFiles() {
    const kw = document.getElementById('file-search').value.toLowerCase().trim();
    const items = document.querySelectorAll('.file-item');
    searchMatches = []; searchIndex = 0;
    items.forEach(it => { it.style.backgroundColor = ''; it.style.display = 'block'; });
    if (!kw) return;
    items.forEach((it, idx) => { if (it.textContent.toLowerCase().includes(kw)) searchMatches.push(idx); });
    if (searchMatches.length > 0) { highlightSearchResult(); scrollToMatch(); }
}
function searchPrev() { if (!searchMatches.length) return; searchIndex = (searchIndex - 1 + searchMatches.length) % searchMatches.length; highlightSearchResult(); scrollToMatch(); }
function searchNext() { if (!searchMatches.length) return; searchIndex = (searchIndex + 1) % searchMatches.length; highlightSearchResult(); scrollToMatch(); }
function highlightSearchResult() {
    document.querySelectorAll('.file-item').forEach(i => i.style.backgroundColor = '');
    if (searchMatches.length > 0) {
        const cur = document.querySelector(`[data-index="${searchMatches[searchIndex]}"]`);
        if (cur) cur.style.backgroundColor = '#fff3cd';
    }
}
function scrollToMatch() {
    if (searchMatches.length === 0) return;
    const cur = document.querySelector(`[data-index="${searchMatches[searchIndex]}"]`);
    if (cur) cur.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

// ============ 文件列表滚动控制 ============
let fileListScrollInterval = null, fileListScrollTimeout = null;
function scrollFileListUp() { const fl = document.getElementById('file-list'); if (!fl) return; fl.scrollTop = Math.max(0, fl.scrollTop - 50); updateScrollButtons(); }
function scrollFileListDown() { const fl = document.getElementById('file-list'); if (!fl) return; const max = fl.scrollHeight - fl.clientHeight; fl.scrollTop = Math.min(max, fl.scrollTop + 50); updateScrollButtons(); }
function startFileListScroll(dir) { event.preventDefault(); if (dir === 'up') scrollFileListUp(); else scrollFileListDown(); fileListScrollTimeout = setTimeout(() => { fileListScrollInterval = setInterval(() => { if (dir === 'up') scrollFileListUp(); else scrollFileListDown(); }, 100); }, 500); }
function stopFileListScroll() { if (fileListScrollTimeout) clearTimeout(fileListScrollTimeout); if (fileListScrollInterval) clearInterval(fileListScrollInterval); fileListScrollTimeout = fileListScrollInterval = null; }
function updateScrollButtons() {
    const fl = document.getElementById('file-list'), up = document.getElementById('scroll-up-btn'), down = document.getElementById('scroll-down-btn');
    if (!fl || !up || !down) return;
    const scrollable = fl.scrollHeight > fl.clientHeight;
    if (!scrollable) { up.classList.add('hidden'); down.classList.add('hidden'); return; }
    up.classList.toggle('hidden', fl.scrollTop <= 0);
    down.classList.toggle('hidden', fl.scrollTop >= fl.scrollHeight - fl.clientHeight - 1);
}

// ============ 查找替换 ============
function showReplaceDialog() {
    if (replaceRules.length > 0) {
        document.getElementById('find-content').value = replaceRules[0].find || '';
        document.getElementById('replace-content').value = replaceRules[0].replace || '';
    } else {
        document.getElementById('find-content').value = '';
        document.getElementById('replace-content').value = '';
    }
    new bootstrap.Modal(document.getElementById('replaceModal')).show();
}
function saveReplaceRules() {
    const f = document.getElementById('find-content').value.trim();
    const r = document.getElementById('replace-content').value.trim();
    if (!f) { showAlert('请输入查找内容', 'warning'); return; }
    replaceRules = [{find: f, replace: r}];
    localStorage.setItem('replaceRules', JSON.stringify(replaceRules));
    showAlert('替换规则已保存');
    bootstrap.Modal.getInstance(document.getElementById('replaceModal')).hide();
}
function clearReplaceRules() {
    replaceRules = [];
    localStorage.removeItem('replaceRules');
    document.getElementById('find-content').value = '';
    document.getElementById('replace-content').value = '';
    showAlert('替换规则已清除');
}
function loadReplaceRules() {
    try {
        const saved = localStorage.getItem('replaceRules');
        if (saved) replaceRules = JSON.parse(saved);
    } catch (e) { replaceRules = []; }
}
function applyReplaceRules(content) {
    if (!content || !replaceRules.length) return content;
    let out = content;
    replaceRules.forEach(rule => {
        if (rule.find) out = out.replace(new RegExp(escapeRegExp(rule.find), 'g'), rule.replace || '');
    });
    return out;
}
function escapeRegExp(s) { return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

// ============ 一键导入为图集 ============
async function publishAlbum() {
    const title = document.getElementById('article-title').value.trim();
    const content = document.getElementById('article-content').value;
    if (!title) { showAlert('请填写图集标题', 'warning'); return; }
    if (!content.trim()) { showAlert('请输入内容', 'warning'); return; }

    const urls = extractUrls(content);
    if (!urls.length) { showAlert('未识别到任何图片/视频 URL', 'warning'); return; }

    const categoryIds = Array.from(selectedCategories);
    if (!categoryIds.length) {
        if (!confirm('未选择分类，将归入"未分类"。继续吗？')) return;
    }
    const description = document.getElementById('album-description').value.trim();
    // 复选框：是否导入视频
    const includeVideos = document.getElementById('opt-include-videos').checked;
    const firstAsCover = true;   // 默认用首图作封面
    const downloadLocal = false; // 视频不作本地下载

    const finalContent = applyReplaceRules(content);

    const btn = document.getElementById('publishBtn');
    btn.disabled = true; btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> 导入中...';
    const prog = document.getElementById('importProgress'); prog.style.display = 'block';
    document.getElementById('progressBar').style.width = '0%';
    document.getElementById('progressText').textContent = '提交任务...';

    const pollTimer = setInterval(async () => {
        try {
            const r = await fetch('/api/image_import/progress');
            const p = await r.json();
            if (p && p.total > 0) {
                const pct = Math.round(p.current / p.total * 100);
                document.getElementById('progressBar').style.width = pct + '%';
                document.getElementById('progressBar').textContent = pct + '%';
                document.getElementById('progressText').textContent = `已处理 ${p.current} / ${p.total}`;
            }
            if (p && p.done) clearInterval(pollTimer);
        } catch (e) {}
    }, 800);

    // 本地模式：走 /api/image_import/import_local（物理拷贝入库，更适合本地文件源）
    if (sourceMode === 'local') {
        const folderPath = currentPath || '';
        if (!folderPath) { clearInterval(pollTimer); showAlert('请先选择本地目录', 'warning'); btn.disabled = false; btn.innerHTML = '<i class="bi bi-cloud-arrow-up me-1"></i>一键导入'; return; }
        try {
            const resp = await fetch('/api/image_import/import_local', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    folder_path: folderPath,
                    album_title: title,
                    description,
                    category_id: categoryIds[0] || 0,
                    include_videos: includeVideos,
                })
            });
            const data = await resp.json();
            clearInterval(pollTimer);
            document.getElementById('progressBar').style.width = '100%';
            document.getElementById('progressBar').textContent = '100%';
            const result = document.getElementById('importResult');
            if (data.success) {
                result.innerHTML = `<div class="alert alert-success">
                    <i class="bi bi-check-circle"></i> 导入成功！图集 #${data.album_id} · 图片 ${data.images_imported} 张${data.videos_imported ? ' · 视频 ' + data.videos_imported + ' 个' : ''}
                    <a href="/admin/albums/edit/${data.album_id}" class="btn btn-sm btn-outline-primary ms-2">查看图集</a>
                    <a href="/album/${data.album_id}" class="btn btn-sm btn-outline-success ms-1" target="_blank">前台预览</a>
                </div>`;
                document.getElementById('article-content').value = '';
                document.getElementById('preview-content').innerHTML = '<p class="text-muted text-center">输入内容后此处实时显示渲染结果</p>';
                document.getElementById('album-description').value = '';
                selectedCategories.clear(); updateSelectedCategories();
                updatePvSummary();
                // 本地模式：导入成功后自动关闭当前目录标签（仅多标签时），便于连续选下一个目录
                if (currentActiveTab && Object.keys(alistTabs).length > 1) {
                    closeAlistTab(currentActiveTab);
                }
            } else {
                result.innerHTML = `<div class="alert alert-danger"><i class="bi bi-x-circle"></i> ${data.message || '导入失败'}</div>`;
            }
        } catch (e) {
            clearInterval(pollTimer);
            document.getElementById('importResult').innerHTML = `<div class="alert alert-danger">请求失败: ${e.message}</div>`;
        } finally {
            btn.disabled = false; btn.innerHTML = '<i class="bi bi-cloud-arrow-up me-1"></i>一键导入';
        }
        return;
    }

    // OpenList 模式：现有 /api/image_import/create 流程
    try {
        const resp = await fetch('/api/image_import/create', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                title, description, content: finalContent,
                category_id: categoryIds[0] || 0,
                category_ids: categoryIds,
                include_videos: includeVideos,
                download_local: downloadLocal,
                first_as_cover: firstAsCover,
                source: 'openlist',   // 图片导入工具处理的均为 OpenList 远端直链
            })
        });
        const data = await resp.json();
        clearInterval(pollTimer);
        document.getElementById('progressBar').style.width = '100%';
        document.getElementById('progressBar').textContent = '100%';
        const result = document.getElementById('importResult');
        if (data.success) {
            result.innerHTML = `<div class="alert alert-success">
                <i class="bi bi-check-circle"></i> 导入成功！图集 #${data.album_id} · ${data.stats || ''} · 图片 ${data.images_imported} 张${data.videos_imported ? ' · 视频 ' + data.videos_imported + ' 个' : ''}
                <a href="/admin/albums/edit/${data.album_id}" class="btn btn-sm btn-outline-primary ms-2">查看图集</a>
                <a href="/album/${data.album_id}" class="btn btn-sm btn-outline-success ms-1" target="_blank">前台预览</a>
            </div>`;
            // 与 typecho_web 一致：导入成功后自动关闭当前打开的 OpenList 文件列表标签页（仅当存在多个标签时）
            if (currentActiveTab && Object.keys(alistTabs).length > 1) {
                closeAlistTab(currentActiveTab);
            }
            // 清空准备下一批
            document.getElementById('article-content').value = '';
            document.getElementById('preview-content').innerHTML = '<p class="text-muted text-center">输入内容后此处实时显示渲染结果</p>';
            document.getElementById('album-description').value = '';
            selectedCategories.clear(); updateSelectedCategories();
            updatePvSummary();
        } else {
            result.innerHTML = `<div class="alert alert-danger"><i class="bi bi-x-circle"></i> ${data.message || '导入失败'}</div>`;
        }
    } catch (e) {
        clearInterval(pollTimer);
        document.getElementById('importResult').innerHTML = `<div class="alert alert-danger">请求失败: ${e.message}</div>`;
    } finally {
        btn.disabled = false; btn.innerHTML = '<i class="bi bi-cloud-arrow-up me-1"></i>一键导入';
    }
}
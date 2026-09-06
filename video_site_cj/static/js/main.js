(function() {
    'use strict';

    function initVideoPlayers() {
        var videos = document.querySelectorAll('video');
        videos.forEach(function(video) {
            var src = video.src || video.getAttribute('src');
            if (!src) return;

            var ext = src.split('.').pop().split('?')[0].toLowerCase();

            if (ext === 'm3u8') {
                if (window.Hls && Hls.isSupported()) {
                    var hls = new Hls();
                    hls.loadSource(src);
                    hls.attachMedia(video);
                } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
                    video.src = src;
                }
            } else if (ext === 'flv') {
                playFlv(video, src);
            }
        });
    }

    function playFlv(video, url) {
        fetch(url, { mode: 'cors' })
            .then(function(response) { return response.blob(); })
            .then(function(blob) {
                var blobUrl = URL.createObjectURL(blob);
                video.src = blobUrl;
            })
            .catch(function() {
                video.src = url;
            });
    }

    function confirmDelete(message) {
        return window.confirm(message || '确定要删除吗？');
    }

    function formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        var k = 1024;
        var sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        var i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function toast(message, type) {
        var toast = document.createElement('div');
        toast.className = 'toast toast-' + (type || 'info');
        toast.textContent = message;
        toast.style.cssText = 'position:fixed;top:80px;right:20px;padding:12px 20px;border-radius:8px;z-index:9999;background:' +
            (type === 'success' ? '#10b981' : type === 'error' ? '#ef4444' : '#3b82f6') +
            ';color:white;box-shadow:0 4px 12px rgba(0,0,0,0.15);transition:opacity 0.3s;';
        document.body.appendChild(toast);
        setTimeout(function() {
            toast.style.opacity = '0';
            setTimeout(function() { toast.remove(); }, 300);
        }, 3000);
    }

    document.addEventListener('DOMContentLoaded', function() {
        initVideoPlayers();

        // 处理已缓存的封面图片（onload 可能不会触发）
        var coverImgs = document.querySelectorAll('.video-cover img, .detail-cover-wrapper img');
        coverImgs.forEach(function(img) {
            if (img.complete && img.naturalWidth > 0) {
                if (img.closest('.detail-cover-wrapper')) {
                    window.adaptCoverOrientation(img, '.detail-cover-wrapper');
                } else {
                    window.adaptCoverOrientation(img, '.video-cover');
                }
            }
        });

        var searchForm = document.querySelector('form[action*="search"]');
        if (searchForm) {
            searchForm.addEventListener('submit', function(e) {
                e.preventDefault();
                var keyword = searchForm.querySelector('input[name="q"]').value.trim();
                if (keyword) {
                    window.location.href = '/?q=' + encodeURIComponent(keyword);
                }
            });
        }
    });

    window.VideoSite = {
        toast: toast,
        confirmDelete: confirmDelete,
        formatFileSize: formatFileSize
    };

    // 根据封面图实际宽高比自动调整卡片/封面方向
    // 可用于 .video-cover（列表卡片）和 .detail-cover-wrapper（详情页封面）
    window.adaptCoverOrientation = function(img, targetClass) {
        var target = targetClass ? img.closest(targetClass) : img.parentNode;
        if (!target) return;
        var w = img.naturalWidth || 0;
        var h = img.naturalHeight || 0;
        if (w === 0 || h === 0) return;
        target.classList.remove('cover-landscape', 'cover-portrait', 'cover-square');
        if (w > h) {
            target.classList.add('cover-landscape');
        } else if (h > w) {
            target.classList.add('cover-portrait');
        } else {
            target.classList.add('cover-square');
        }
    };
})();

import xml.etree.ElementTree as ET
import re

def parse_nfo_content(content):
    """
    解析 NFO 文件内容（XML 格式）
    返回字典包含: title, original_title, plot, rating, genre, year, thumbs, actors 等
    """
    result = {
        'title': '',
        'original_title': '',
        'plot': '',
        'rating': '',
        'genre': '',
        'year': '',
        'thumbs': [],
        'actors': [],
        'poster': '',
        'fanart': '',
        'episodenumber': '',
        'season': ''
    }
    
    try:
        if not content or not content.strip():
            return result
        
        root = ET.fromstring(content)
        
        # 处理根节点可能是 movie, tvshow, episodedetails 等
        # Title
        title_elem = root.find('title')
        if title_elem is not None and title_elem.text:
            result['title'] = title_elem.text.strip()
        
        original_title_elem = root.find('originaltitle')
        if original_title_elem is not None and original_title_elem.text:
            result['original_title'] = original_title_elem.text.strip()
        
        # Plot / 描述
        plot_elem = root.find('plot')
        if plot_elem is not None and plot_elem.text:
            result['plot'] = plot_elem.text.strip()
        
        # Rating
        rating_elem = root.find('rating')
        if rating_elem is not None and rating_elem.text:
            result['rating'] = rating_elem.text.strip()
        
        # Genre
        genre_elem = root.find('genre')
        if genre_elem is not None and genre_elem.text:
            result['genre'] = genre_elem.text.strip()
        
        # Year
        year_elem = root.find('year')
        if year_elem is not None and year_elem.text:
            result['year'] = year_elem.text.strip()
        
        # Episode number (for TV shows)
        ep_elem = root.find('episodenumber')
        if ep_elem is not None and ep_elem.text:
            result['episodenumber'] = ep_elem.text.strip()
        
        season_elem = root.find('season')
        if season_elem is not None and season_elem.text:
            result['season'] = season_elem.text.strip()
        
        # Thumbs / Poster
        for thumb in root.findall('thumb'):
            if thumb.text:
                result['thumbs'].append(thumb.text.strip())
                # 第一个 thumb 通常是海报
                if not result['poster']:
                    result['poster'] = thumb.text.strip()
        
        # 检查 fanart 节点
        fanart_elem = root.find('fanart')
        if fanart_elem is not None:
            for thumb in fanart_elem.findall('thumb'):
                if thumb.text and not result['fanart']:
                    result['fanart'] = thumb.text.strip()
        
        # Actors
        for actor in root.findall('actor'):
            actor_info = {}
            name_elem = actor.find('name')
            if name_elem is not None and name_elem.text:
                actor_info['name'] = name_elem.text.strip()
            role_elem = actor.find('role')
            if role_elem is not None and role_elem.text:
                actor_info['role'] = role_elem.text.strip()
            thumb_elem = actor.find('thumb')
            if thumb_elem is not None and thumb_elem.text:
                actor_info['thumb'] = thumb_elem.text.strip()
            if actor_info.get('name'):
                result['actors'].append(actor_info)
        
        return result
    
    except ET.ParseError as e:
        # 尝试修复常见的 XML 问题
        try:
            # 移除可能的 BOM 或特殊字符
            cleaned_content = re.sub(r'[^\x20-\x7E\u00A0-\uFFFF\n\r\t]', '', content)
            root = ET.fromstring(cleaned_content)
            
            title_elem = root.find('title')
            if title_elem is not None and title_elem.text:
                result['title'] = title_elem.text.strip()
            
            plot_elem = root.find('plot')
            if plot_elem is not None and plot_elem.text:
                result['plot'] = plot_elem.text.strip()
            
            return result
        except:
            pass
        
        return result
    except Exception as e:
        return result

def get_nfo_file_for_video(video_path, files_in_directory):
    """
    从目录文件列表中找到与视频对应的 NFO 文件
    支持两种命名模式:
    1. 同名: video.mkv -> video.nfo
    2. movie.nfo 或 tvshow.nfo (通用)
    """
    video_base = video_path.rsplit('/', 1)[-1] if '/' in video_path else video_path
    video_name_without_ext = video_base.rsplit('.', 1)[0] if '.' in video_base else video_base
    
    nfo_files = []
    for f in files_in_directory:
        name = f.get('name', '').lower()
        if name.endswith('.nfo'):
            nfo_files.append(f)
    
    # 优先匹配同名的 nfo
    for nfo in nfo_files:
        nfo_name = nfo.get('name', '').rsplit('.', 1)[0].lower()
        if nfo_name == video_name_without_ext.lower():
            return nfo
    
    # 检查是否有 movie.nfo 或 tvshow.nfo
    for nfo in nfo_files:
        nfo_name = nfo.get('name', '').lower()
        if nfo_name in ('movie.nfo', 'tvshow.nfo'):
            return nfo
    
    return None

def extract_nfo_metadata(nfo_data):
    """
    从解析的 NFO 数据中提取视频元数据
    返回可用于创建视频记录的字段
    """
    metadata = {}
    
    # 标题
    if nfo_data.get('title'):
        metadata['title'] = nfo_data['title']
    
    # 描述
    if nfo_data.get('plot'):
        metadata['description'] = nfo_data['plot']
    
    # 封面
    poster = nfo_data.get('poster', '')
    if poster:
        metadata['cover'] = poster
    elif nfo_data.get('thumbs'):
        metadata['cover'] = nfo_data['thumbs'][0]
    
    # 评分
    if nfo_data.get('rating'):
        metadata['rating'] = nfo_data['rating']
    
    # 类型
    if nfo_data.get('genre'):
        metadata['genre'] = nfo_data['genre']
    
    # 年份
    if nfo_data.get('year'):
        metadata['year'] = nfo_data['year']
    
    # 演员
    if nfo_data.get('actors'):
        metadata['actors'] = nfo_data['actors']
    
    # 集数信息
    if nfo_data.get('episodenumber'):
        try:
            metadata['episode_number'] = int(nfo_data['episodenumber'])
        except ValueError:
            pass
    
    return metadata

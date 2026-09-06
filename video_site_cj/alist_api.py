import requests
from urllib.parse import quote

# 禁用 HTTPS 证书警告（兼容自签名证书的外网 OpenList）
requests.packages.urllib3.disable_warnings()


class OpenListApi:
    def __init__(self, server_url, username, password):
        self.server_url = server_url.rstrip('/')
        self.username = username
        self.password = password
        self.token = None

    def _post(self, url, json_data=None, headers=None, timeout=15):
        """统一的 POST 请求封装，兼容 HTTPS 自签名证书"""
        return requests.post(url, json=json_data, headers=headers,
                             timeout=timeout, verify=False)

    def login(self):
        url = f"{self.server_url}/api/auth/login"
        try:
            resp = self._post(url, json_data={"username": self.username, "password": self.password}, timeout=10)
            resp.raise_for_status()
            body = resp.json()
            # 安全解析：兼容不同 OpenList 版本的响应结构
            data = body.get('data') if isinstance(body, dict) else None
            if data and isinstance(data, dict):
                token = data.get('token')
                if token:
                    self.token = token
                    return self.token
            # 兜底：有些 OpenList 返回结构不同
            if body.get('code') == 200:
                # 尝试从其他位置获取 token
                token = body.get('token') or (data.get('token') if isinstance(data, dict) else None)
                if token:
                    self.token = token
                    return self.token
            raise Exception(f"登录响应异常: {body}")
        except requests.exceptions.Timeout:
            raise Exception(f"连接OpenList服务器超时: {self.server_url}")
        except requests.exceptions.ConnectionError:
            raise Exception(f"无法连接到OpenList服务器: {self.server_url}")
        except requests.exceptions.RequestException as e:
            raise Exception(f"OpenList登录失败: {e}")

    def get_file_list(self, path="/", page=1, per_page=1000):
        url = f"{self.server_url}/api/fs/list"
        headers = {"Authorization": self.token}
        all_files = []
        current_page = 1

        try:
            while True:
                try:
                    resp = self._post(url,
                                      json_data={"path": path, "page": current_page, "per_page": per_page},
                                      headers=headers, timeout=15)
                    resp.raise_for_status()
                    body = resp.json()
                    data = body.get('data', None) if isinstance(body, dict) else None

                    if data is None or not isinstance(data, dict):
                        # token 失效或响应异常，重新登录
                        self.login()
                        headers = {"Authorization": self.token}
                        resp = self._post(url,
                                          json_data={"path": path, "page": current_page, "per_page": per_page},
                                          headers=headers, timeout=15)
                        resp.raise_for_status()
                        body = resp.json()
                        data = body.get('data', None) if isinstance(body, dict) else None
                        if data is None or not isinstance(data, dict):
                            break
                except requests.exceptions.Timeout:
                    raise Exception(f"获取文件列表超时: {self.server_url} (路径: {path})")
                except requests.exceptions.ConnectionError:
                    raise Exception(f"连接OpenList服务器失败: {self.server_url}")
                except requests.exceptions.RequestException as e:
                    raise Exception(f"获取文件列表失败: {e}")

                content = data.get('content', []) if isinstance(data, dict) else []
                if not content or len(content) == 0:
                    break

                all_files.extend(content)

                if len(content) < per_page:
                    break

                current_page += 1
                if current_page > 100:
                    break

            return all_files
        except Exception as e:
            print(f"加载文件列表失败: {e}")
            return []

    def get_file_link(self, file_path):
        encoded_path = "/".join([quote(p) for p in file_path.split("/") if p])
        url = f"{self.server_url}/d/{encoded_path}"
        return url

    def get_direct_link(self, file_path):
        url = f"{self.server_url}/api/fs/direct"
        headers = {"Authorization": self.token}
        try:
            resp = self._post(url, json_data={"path": file_path}, headers=headers, timeout=10)
            resp.raise_for_status()
            result = resp.json()
            if isinstance(result, dict) and result.get('code') == 200:
                data = result.get('data', {})
                if isinstance(data, dict) and data.get('url'):
                    return data['url']
            return self.get_file_link(file_path)
        except Exception:
            return self.get_file_link(file_path)

    def get_all_files_flat(self, path="/", video_extensions=None, _visited=None):
        if video_extensions is None:
            video_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.m3u8', '.asf', '.m4v', '.rm', '.asx', '.rmvb', '.webm', '.ts']

        if _visited is None:
            _visited = set()
        norm_path = path.rstrip('/')
        if norm_path in _visited:
            return []
        _visited.add(norm_path)

        all_videos = []
        try:
            files = self.get_file_list(path)
            for item in files:
                name = item.get('name', '')
                if item.get('is_dir'):
                    sub_path = path.rstrip('/') + '/' + name
                    sub_videos = self.get_all_files_flat(sub_path, video_extensions, _visited)
                    all_videos.extend(sub_videos)
                else:
                    lower_name = name.lower()
                    ext = '.' + lower_name.split('.')[-1] if '.' in lower_name else ''
                    if ext in video_extensions:
                        item['full_path'] = path.rstrip('/') + '/' + name
                        item['direct_url'] = self.get_file_link(item['full_path'])
                        all_videos.append(item)
        except Exception as e:
            print(f"递归加载文件失败: {e}")

        return all_videos

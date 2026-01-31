import os
import time
import json
import requests
from pathlib import Path
from urllib.parse import urlparse
import mimetypes

class DownloadManager:
    def __init__(self, config):
        """初始化下载管理器"""
        self.config = config
        self.session = requests.Session()
        
        # 配置会话
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.pixiv.net/"
        })
        
        # 配置代理
        if self.config.is_proxy_enabled():
            proxy_url = self.config.get_proxy_url()
            if proxy_url:
                self.session.proxies = {
                    "http": proxy_url,
                    "https": proxy_url
                }
                
        self.timeout = self.config.get_timeout()
        
    def download_image(self, url, illust_info):
        """下载图片"""
        try:
            # 检查是否已下载
            illust_id = illust_info["id"]
            if self._is_already_downloaded(illust_id):
                return {"success": False, "skipped": True, "message": "已存在"}
                
            # 创建保存路径
            save_path = self._get_save_path(illust_info)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 下载图片
            response = self.session.get(url, timeout=self.timeout, stream=True)
            response.raise_for_status()
            
            # 保存图片
            file_size = 0
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        file_size += len(chunk)
                        
            # 保存元数据
            metadata_path = self._save_metadata(illust_info)
            
            # 返回结果
            return {
                "success": True,
                "file_path": str(save_path),
                "metadata_path": str(metadata_path),
                "file_size": file_size,
                "message": "下载成功"
            }
            
        except requests.exceptions.Timeout:
            return {"success": False, "error": "下载超时"}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": f"网络错误: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": f"下载失败: {str(e)}"}
            
    def _is_already_downloaded(self, illust_id):
        """检查是否已下载"""
        # 检查数据库
        # 这里假设数据库管理器已经标记了已下载的作品
        # 实际实现中会调用数据库管理器的方法
        
        # 同时检查文件是否存在
        img_dir = self.config.get_image_dir()
        possible_files = [
            img_dir / f"{illust_id}.jpg",
            img_dir / f"{illust_id}.png",
            img_dir / f"{illust_id}.gif",
            img_dir / f"{illust_id}.jpeg"
        ]
        
        for file_path in possible_files:
            if file_path.exists():
                return True
                
        return False
        
    def _get_save_path(self, illust_info):
        """获取保存路径"""
        illust_id = illust_info["id"]
        user_id = illust_info["user"]["id"]
        illust_type = illust_info.get("type", "illust")
        
        # 根据作品类型确定扩展名
        url = illust_info["image_urls"]["large"]
        parsed = urlparse(url)
        filename = parsed.path.split("/")[-1]
        
        # 提取扩展名
        if "." in filename:
            ext = filename.split(".")[-1].split("?")[0]
        else:
            # 默认使用jpg
            ext = "jpg"
            
        # 创建目录结构: img/user_id/illust_id.ext
        user_dir = self.config.get_image_dir() / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        
        return user_dir / f"{illust_id}.{ext}"
        
    def _save_metadata(self, illust_info):
        """保存元数据"""
        illust_id = illust_info["id"]
        user_id = illust_info["user"]["id"]
        
        # 创建目录结构: metadata/user_id/illust_id.json
        user_dir = self.config.get_metadata_dir() / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        
        metadata_path = user_dir / f"{illust_id}.json"
        
        # 准备元数据
        metadata = {
            "illust_id": illust_id,
            "title": illust_info["title"],
            "caption": illust_info.get("caption", ""),
            "user": {
                "user_id": illust_info["user"]["id"],
                "name": illust_info["user"]["name"],
                "account": illust_info["user"]["account"],
                "profile_image_url": illust_info["user"].get("profile_image_urls", {}).get("medium", "")
            },
            "create_date": illust_info.get("create_date", ""),
            "page_count": illust_info.get("page_count", 1),
            "width": illust_info.get("width", 0),
            "height": illust_info.get("height", 0),
            "bookmark_count": illust_info.get("total_bookmarks", illust_info.get("bookmark_count", 0)),
            "view_count": illust_info.get("total_view", illust_info.get("view_count", 0)),
            "sanity_level": illust_info.get("sanity_level", 0),
            "x_restrict": illust_info.get("x_restrict", 0),
            "type": illust_info.get("type", "illust"),
            "tags": [tag.get("name", "") for tag in illust_info.get("tags", [])],
            "image_urls": illust_info.get("image_urls", {}),
            "tools": illust_info.get("tools", []),
            "download_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "original_url": f"https://www.pixiv.net/artworks/{illust_id}"
        }
        
        # 保存JSON文件
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
            
        return metadata_path
        
    def download_ugoira(self, illust_info, ugoira_info):
        """下载动图"""
        try:
            illust_id = illust_info["id"]
            
            # 检查是否已下载
            if self._is_already_downloaded(illust_id):
                return {"success": False, "skipped": True, "message": "已存在"}
                
            # 创建保存路径
            save_path = self._get_ugoira_save_path(illust_info)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 下载动图帧
            frames = ugoira_info.get("frames", [])
            zip_url = ugoira_info.get("zip_url", "")
            
            if not zip_url:
                return {"success": False, "error": "没有找到动图ZIP文件"}
                
            # 下载ZIP文件
            response = self.session.get(zip_url, timeout=self.timeout, stream=True)
            response.raise_for_status()
            
            # 保存ZIP文件
            zip_path = save_path.with_suffix(".zip")
            file_size = 0
            with open(zip_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        file_size += len(chunk)
                        
            # 保存元数据（包含帧信息）
            metadata = illust_info.copy()
            metadata["ugoira_frames"] = frames
            metadata["ugoira_zip_url"] = zip_url
            metadata_path = self._save_metadata(metadata)
            
            return {
                "success": True,
                "file_path": str(zip_path),
                "metadata_path": str(metadata_path),
                "file_size": file_size,
                "message": "动图下载成功",
                "is_ugoira": True,
                "frame_count": len(frames)
            }
            
        except Exception as e:
            return {"success": False, "error": f"动图下载失败: {str(e)}"}
            
    def _get_ugoira_save_path(self, illust_info):
        """获取动图保存路径"""
        illust_id = illust_info["id"]
        user_id = illust_info["user"]["id"]
        
        # 创建目录结构: img/user_id/ugoira/illust_id.zip
        ugoira_dir = self.config.get_image_dir() / str(user_id) / "ugoira"
        ugoira_dir.mkdir(parents=True, exist_ok=True)
        
        return ugoira_dir / f"{illust_id}.zip"
        
    def get_download_stats(self):
        """获取下载统计"""
        img_dir = self.config.get_image_dir()
        metadata_dir = self.config.get_metadata_dir()
        
        # 统计文件数量
        img_count = 0
        total_size = 0
        
        for root, dirs, files in os.walk(str(img_dir)):
            for file in files:
                file_path = Path(root) / file
                img_count += 1
                total_size += file_path.stat().st_size if file_path.exists() else 0
                
        metadata_count = 0
        for root, dirs, files in os.walk(str(metadata_dir)):
            metadata_count += len(files)
            
        return {
            "image_count": img_count,
            "metadata_count": metadata_count,
            "total_size": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2)
        }
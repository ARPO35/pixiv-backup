import os
import time
import json
import logging
import requests
from pathlib import Path
from urllib.parse import urlparse
import mimetypes

class DownloadManager:
    def __init__(self, config, stop_checker=None):
        """初始化下载管理器"""
        self.config = config
        self.session = requests.Session()
        self.stop_checker = stop_checker
        
        # 配置会话
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.pixiv.net/"
        })
        
        self.timeout = self.config.get_timeout()
        self.logger = logging.getLogger(__name__)

    def _normalize_event_value(self, value):
        text = str(value)
        text = text.replace("\r", " ").replace("\n", " ")
        text = " ".join(text.split())
        return text if text else "-"

    def _event_line(self, event, **fields):
        parts = [f"event={self._normalize_event_value(event)}"]
        for key, value in fields.items():
            parts.append(f"{self._normalize_event_value(key)}={self._normalize_event_value(value)}")
        return " ".join(parts)

    def _log_event(self, event, **fields):
        self.logger.info(self._event_line(event, **fields))

    def _should_stop(self):
        try:
            return bool(self.stop_checker and self.stop_checker())
        except Exception:
            return False

    def _ensure_parent_dir(self, file_path):
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
    def download_image(self, url, illust_info, page_index=None):
        """下载图片"""
        try:
            illust_id = illust_info["id"]
            if self._should_stop():
                return {"success": False, "stopped": True, "error": "stop_requested"}
            # 创建保存路径
            save_path = self._get_save_path(url, illust_info, page_index)
            self._ensure_parent_dir(save_path)
            if save_path.exists():
                self._log_event("file_skip", illust_id=illust_id, page_index=page_index if page_index is not None else "-", path=save_path, reason="file_exists")
                return {"success": False, "skipped": True, "message": "已存在", "file_path": str(save_path), "file_size": save_path.stat().st_size}

            self._log_event("file_download_start", illust_id=illust_id, page_index=page_index if page_index is not None else "-", url=url, path=save_path)
            
            # 下载图片
            response = self.session.get(url, timeout=self.timeout, stream=True)
            response.raise_for_status()
            
            # 保存图片
            file_size = 0
            tmp_path = Path(str(save_path) + ".part")
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            try:
                with open(tmp_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if self._should_stop():
                            raise RuntimeError("stop_requested")
                        if chunk:
                            f.write(chunk)
                            file_size += len(chunk)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, save_path)
            except Exception:
                tmp_path.unlink(missing_ok=True)
                raise
                        
            # 保存元数据
            metadata_path = self._save_metadata(illust_info)
            self._log_event("file_download_finish", illust_id=illust_id, page_index=page_index if page_index is not None else "-", status="success", path=save_path, file_size=file_size)
            
            # 返回结果
            return {
                "success": True,
                "file_path": str(save_path),
                "metadata_path": str(metadata_path),
                "file_size": file_size,
                "message": "下载成功"
            }
            
        except requests.exceptions.Timeout:
            err = f"page_index={page_index if page_index is not None else 0} image_url={url} 下载超时"
            self._log_event("file_download_finish", illust_id=illust_info.get("id", "-"), page_index=page_index if page_index is not None else "-", status="failed", error=err)
            return {"success": False, "error": err}
        except requests.exceptions.RequestException as e:
            err = f"page_index={page_index if page_index is not None else 0} image_url={url} 网络错误: {str(e)}"
            self._log_event("file_download_finish", illust_id=illust_info.get("id", "-"), page_index=page_index if page_index is not None else "-", status="failed", error=err)
            return {"success": False, "error": err}
        except Exception as e:
            if str(e) == "stop_requested":
                self._log_event("file_download_finish", illust_id=illust_info.get("id", "-"), page_index=page_index if page_index is not None else "-", status="stopped", error="stop_requested")
                return {"success": False, "stopped": True, "error": "stop_requested"}
            err = f"page_index={page_index if page_index is not None else 0} image_url={url} 下载失败: {str(e)}"
            self._log_event("file_download_finish", illust_id=illust_info.get("id", "-"), page_index=page_index if page_index is not None else "-", status="failed", error=err)
            return {"success": False, "error": err}
            
    def _is_already_downloaded(self, illust_id):
        """检查是否已下载"""
        # 检查数据库
        # 这里假设数据库管理器已经标记了已下载的作品
        # 实际实现中会调用数据库管理器的方法
        
        # 同时检查文件是否存在：img/<illust_id>/ 下任意文件
        illust_dir = self.config.get_image_dir() / str(illust_id)
        if not illust_dir.exists():
            return False
        return any(p.is_file() for p in illust_dir.iterdir())

    def _single_image_url(self, illust_info):
        single = illust_info.get("meta_single_page", {}) if isinstance(illust_info.get("meta_single_page"), dict) else {}
        image_url = single.get("original_image_url")
        if not image_url:
            image_url = illust_info.get("image_urls", {}).get("original") or illust_info.get("image_urls", {}).get("large")
        return image_url

    def _get_page_image_url(self, illust_info, page_index):
        meta_pages = illust_info.get("meta_pages") or []
        if isinstance(meta_pages, list) and page_index < len(meta_pages):
            page = meta_pages[page_index]
            image_urls = page.get("image_urls", {}) if isinstance(page, dict) else {}
            return image_urls.get("original") or image_urls.get("large")
        return None

    def is_illust_fully_downloaded(self, illust_info):
        """检查作品是否完整下载（多图按页检查）"""
        illust_id = int(illust_info["id"])
        illust_type = illust_info.get("type", "illust")

        if illust_type == "ugoira":
            zip_path = self._get_ugoira_save_path(illust_info).with_suffix(".zip")
            return zip_path.exists() and zip_path.is_file()

        page_count = int(illust_info.get("page_count", 1) or 1)
        if page_count > 1:
            for idx in range(page_count):
                image_url = self._get_page_image_url(illust_info, idx)
                if image_url:
                    expected = self._get_save_path(image_url, illust_info, page_index=idx)
                    if not expected.exists():
                        return False
                    continue

                # URL 不完整时按 p{idx}. 任意扩展名兜底
                illust_dir = self.config.get_image_dir() / str(illust_id)
                matches = list(illust_dir.glob(f"{illust_id}.p{idx}.*")) if illust_dir.exists() else []
                if not matches:
                    return False
            return True

        image_url = self._single_image_url(illust_info)
        if image_url:
            return self._get_save_path(image_url, illust_info).exists()

        illust_dir = self.config.get_image_dir() / str(illust_id)
        if not illust_dir.exists():
            return False
        return any(p.is_file() for p in illust_dir.glob(f"{illust_id}.*"))
        
    def _get_save_path(self, url, illust_info, page_index=None):
        """获取保存路径"""
        illust_id = illust_info["id"]
        
        # 根据URL确定扩展名
        parsed = urlparse(url)
        filename = parsed.path.split("/")[-1]
        
        # 提取扩展名
        if "." in filename:
            ext = filename.split(".")[-1].split("?")[0]
        else:
            # 默认使用jpg
            ext = "jpg"
            
        # 仅计算目录结构: img/illust_id/illust_id(.pN).ext
        illust_dir = self.config.get_image_dir() / str(illust_id)

        if page_index is not None:
            return illust_dir / f"{illust_id}.p{page_index}.{ext}"
        return illust_dir / f"{illust_id}.{ext}"
        
    def _save_metadata(self, illust_info):
        """保存元数据"""
        illust_id = illust_info["id"]

        # 创建目录结构: metadata/illust_id.json
        metadata_dir = self.config.get_metadata_dir()
        metadata_dir.mkdir(parents=True, exist_ok=True)

        metadata_path = metadata_dir / f"{illust_id}.json"
        
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
            "original_url": f"https://www.pixiv.net/artworks/{illust_id}",
            "is_bookmarked": bool(illust_info.get("is_bookmarked", False)),
            "is_following_author": bool(illust_info.get("is_following_author", False)),
        }
        
        # 保存JSON文件
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        self._log_event("metadata_saved", illust_id=illust_id, metadata_path=metadata_path)
            
        return metadata_path
        
    def download_ugoira(self, illust_info, ugoira_info):
        """下载动图"""
        try:
            illust_id = illust_info["id"]
            if self._should_stop():
                return {"success": False, "stopped": True, "error": "stop_requested"}
                
            # 创建保存路径
            save_path = self._get_ugoira_save_path(illust_info)
            self._ensure_parent_dir(save_path)
            zip_path = save_path.with_suffix(".zip")
            if zip_path.exists():
                self._log_event("file_skip", illust_id=illust_id, page_index="-", path=zip_path, reason="file_exists")
                return {"success": False, "skipped": True, "message": "已存在", "file_path": str(zip_path), "file_size": zip_path.stat().st_size}
            
            # 下载动图帧
            frames = ugoira_info.get("frames", [])
            zip_url, zip_source = self._resolve_ugoira_zip_url(ugoira_info)
            
            if not zip_url:
                available_keys = ",".join(sorted(list(ugoira_info.keys()))) if isinstance(ugoira_info, dict) else "-"
                err = f"没有找到动图ZIP文件(available_keys={available_keys})"
                self._log_event("file_download_finish", illust_id=illust_id, page_index="-", status="failed", error=err)
                return {"success": False, "error": err}
            self._log_event("file_download_start", illust_id=illust_id, page_index="-", url=zip_url, path=zip_path, zip_source=zip_source)
                
            # 下载ZIP文件
            response = self.session.get(zip_url, timeout=self.timeout, stream=True)
            response.raise_for_status()
            
            # 保存ZIP文件
            file_size = 0
            tmp_path = Path(str(zip_path) + ".part")
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            try:
                with open(tmp_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if self._should_stop():
                            raise RuntimeError("stop_requested")
                        if chunk:
                            f.write(chunk)
                            file_size += len(chunk)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, zip_path)
            except Exception:
                tmp_path.unlink(missing_ok=True)
                raise
                        
            # 保存元数据（包含帧信息）
            metadata = illust_info.copy()
            metadata["ugoira_frames"] = frames
            metadata["ugoira_zip_url"] = zip_url
            metadata_path = self._save_metadata(metadata)
            self._log_event("file_download_finish", illust_id=illust_id, page_index="-", status="success", path=zip_path, file_size=file_size, zip_source=zip_source)
            
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
            if str(e) == "stop_requested":
                self._log_event("file_download_finish", illust_id=illust_info.get("id", "-"), page_index="-", status="stopped", error="stop_requested")
                return {"success": False, "stopped": True, "error": "stop_requested"}
            self._log_event("file_download_finish", illust_id=illust_info.get("id", "-"), page_index="-", status="failed", error=f"动图下载失败: {str(e)}")
            return {"success": False, "error": f"动图下载失败: {str(e)}"}

    def _resolve_ugoira_zip_url(self, ugoira_info):
        if not isinstance(ugoira_info, dict):
            return "", "none"
        zip_url = ugoira_info.get("zip_url")
        if zip_url:
            return zip_url, "zip_url"
        zip_urls = ugoira_info.get("zip_urls")
        if isinstance(zip_urls, dict):
            for key in ("original", "medium", "large", "small"):
                value = zip_urls.get(key)
                if value:
                    return value, f"zip_urls.{key}"
        return "", "none"
            
    def _get_ugoira_save_path(self, illust_info):
        """获取动图保存路径"""
        illust_id = illust_info["id"]
        
        # 仅计算目录结构: img/illust_id/illust_id.zip
        ugoira_dir = self.config.get_image_dir() / str(illust_id)
        
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

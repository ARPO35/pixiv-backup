import sqlite3
import json
from pathlib import Path
from datetime import datetime

class DatabaseManager:
    def __init__(self, config):
        """初始化数据库管理器"""
        self.config = config
        self.db_path = self.config.get_database_path()
        self._init_database()
        
    def _init_database(self):
        """初始化数据库表结构"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        # 用户表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                account TEXT,
                profile_image_url TEXT,
                is_premium BOOLEAN,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 作品表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS illusts (
                illust_id INTEGER PRIMARY KEY,
                user_id INTEGER,
                title TEXT,
                caption TEXT,
                create_date TIMESTAMP,
                page_count INTEGER,
                width INTEGER,
                height INTEGER,
                bookmark_count INTEGER,
                view_count INTEGER,
                sanity_level INTEGER,
                x_restrict INTEGER,
                type TEXT,
                image_urls_json TEXT,
                tags_json TEXT,
                downloaded INTEGER DEFAULT 0,
                download_path TEXT,
                downloaded_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        # 下载历史表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS download_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                illust_id INTEGER,
                download_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                success BOOLEAN,
                file_size INTEGER,
                error_message TEXT,
                FOREIGN KEY (illust_id) REFERENCES illusts(illust_id)
            )
        ''')
        
        # 创建索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_illusts_user_id ON illusts(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_illusts_downloaded ON illusts(downloaded)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_illusts_type ON illusts(type)')

        # 兼容旧版本数据库结构，补齐缺失列
        self._ensure_column(conn, "illusts", "file_size", "INTEGER")
        self._ensure_column(conn, "download_history", "file_size", "INTEGER")
        
        conn.commit()
        conn.close()

    def _ensure_column(self, conn, table_name, column_name, column_def):
        """确保表中存在指定列（用于旧版本数据库迁移）"""
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = {row[1] for row in cursor.fetchall()}
        if column_name not in columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")
        
    def save_user(self, user_info):
        """保存用户信息"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO users 
            (user_id, name, account, profile_image_url, is_premium, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            user_info["id"],
            user_info["name"],
            user_info["account"],
            user_info.get("profile_image_urls", {}).get("medium", ""),
            user_info.get("is_premium", False),
            datetime.now().isoformat()
        ))
        
        conn.commit()
        conn.close()
        
    def save_illust(self, illust_info):
        """保存作品信息"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        # 保存用户信息
        if "user" in illust_info:
            self.save_user(illust_info["user"])
            
        # 准备数据
        image_urls_json = json.dumps(illust_info.get("image_urls", {}), ensure_ascii=False)
        tags_json = json.dumps([tag.get("name", "") for tag in illust_info.get("tags", [])], ensure_ascii=False)
        
        cursor.execute('''
            INSERT OR REPLACE INTO illusts 
            (illust_id, user_id, title, caption, create_date, page_count, 
             width, height, bookmark_count, view_count, sanity_level, 
             x_restrict, type, image_urls_json, tags_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            illust_info["id"],
            illust_info["user"]["id"],
            illust_info["title"],
            illust_info.get("caption", ""),
            illust_info.get("create_date", ""),
            illust_info.get("page_count", 1),
            illust_info.get("width", 0),
            illust_info.get("height", 0),
            illust_info.get("total_bookmarks", illust_info.get("bookmark_count", 0)),
            illust_info.get("total_view", illust_info.get("view_count", 0)),
            illust_info.get("sanity_level", 0),
            illust_info.get("x_restrict", 0),
            illust_info.get("type", "illust"),
            image_urls_json,
            tags_json,
            datetime.now().isoformat()
        ))
        
        conn.commit()
        conn.close()
        
    def mark_as_downloaded(self, illust_id, download_path, file_size=None):
        """标记作品为已下载"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE illusts 
            SET downloaded = 1, 
                download_path = ?,
                downloaded_at = ?,
                file_size = ?
            WHERE illust_id = ?
        ''', (
            str(download_path),
            datetime.now().isoformat(),
            file_size,
            illust_id
        ))
        
        # 记录下载历史
        cursor.execute('''
            INSERT INTO download_history 
            (illust_id, success, file_size)
            VALUES (?, ?, ?)
        ''', (
            illust_id,
            True,
            file_size
        ))
        
        conn.commit()
        conn.close()
        
    def record_download_error(self, illust_id, error_message):
        """记录下载错误"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO download_history 
            (illust_id, success, error_message)
            VALUES (?, ?, ?)
        ''', (
            illust_id,
            False,
            error_message
        ))
        
        conn.commit()
        conn.close()
        
    def is_downloaded(self, illust_id):
        """检查作品是否已下载"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute('SELECT downloaded FROM illusts WHERE illust_id = ?', (illust_id,))
        result = cursor.fetchone()
        conn.close()
        
        return result and result[0] == 1
        
    def get_illust_count(self):
        """获取作品总数"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM illusts')
        count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM illusts WHERE downloaded = 1')
        downloaded_count = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "total": count,
            "downloaded": downloaded_count,
            "pending": count - downloaded_count
        }
        
    def get_recent_downloads(self, limit=20):
        """获取最近的下载记录"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT i.illust_id, i.title, i.downloaded_at, u.name, u.account
            FROM illusts i
            JOIN users u ON i.user_id = u.user_id
            WHERE i.downloaded = 1
            ORDER BY i.downloaded_at DESC
            LIMIT ?
        ''', (limit,))
        
        results = cursor.fetchall()
        conn.close()
        
        return [
            {
                "illust_id": row[0],
                "title": row[1],
                "downloaded_at": row[2],
                "author_name": row[3],
                "author_account": row[4]
            }
            for row in results
        ]
        
    def get_download_stats(self):
        """获取下载统计"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        # 按类型统计
        cursor.execute('''
            SELECT type, COUNT(*) as count, 
                   SUM(downloaded) as downloaded_count
            FROM illusts
            GROUP BY type
        ''')
        
        type_stats = {}
        for row in cursor.fetchall():
            type_stats[row[0]] = {
                "total": row[1],
                "downloaded": row[2]
            }
            
        # 按日期统计（最近7天）
        cursor.execute('''
            SELECT DATE(downloaded_at) as date, COUNT(*) as count
            FROM illusts
            WHERE downloaded = 1 AND downloaded_at >= DATE('now', '-7 days')
            GROUP BY DATE(downloaded_at)
            ORDER BY date
        ''')
        
        daily_stats = {}
        for row in cursor.fetchall():
            daily_stats[str(row[0])] = row[1]
            
        conn.close()
        
        return {
            "by_type": type_stats,
            "daily": daily_stats,
            "total": self.get_illust_count()
        }
        
    def cleanup_old_records(self, days=30):
        """清理旧的下载历史记录"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute('''
            DELETE FROM download_history 
            WHERE download_time < DATE('now', ?)
        ''', (f'-{days} days',))
        
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        return deleted_count

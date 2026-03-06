import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class BookmarkOrderRebuilder:
    def __init__(self, config, api_client):
        self.config = config
        self.api = api_client
        self.output_dir = Path(self.config.get_output_dir())
        self.metadata_dir = self.config.get_metadata_dir()
        self.queue_path = self.config.get_data_dir() / "task_queue.json"
        self.scan_cursor_path = self.config.get_data_dir() / "scan_cursor.json"

    def _now_str(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _next_url_kwargs(self, next_url):
        parsed = urlparse(next_url)
        query_params = parse_qs(parsed.query)
        return {k: v[0] for k, v in query_params.items() if v}

    def _progress_line(self, enabled, label, current, total=None):
        if not enabled:
            return
        if total and total > 0:
            pct = (current / total) * 100
            sys.stdout.write(f"\r[{label}] {current}/{total} ({pct:.1f}%)")
        else:
            sys.stdout.write(f"\r[{label}] {current}")
        sys.stdout.flush()

    def _progress_done(self, enabled):
        if enabled:
            sys.stdout.write("\n")
            sys.stdout.flush()

    def _write_json_atomic(self, path, payload):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = Path(str(path) + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
        tmp_path.replace(path)

    def _fetch_bookmark_ids_by_restrict(self, user_id, restrict, show_progress=False, debug=False):
        ids_newest_first = []
        seen = set()
        next_url = None
        page_no = 0

        while True:
            page_no += 1
            try:
                if next_url:
                    kwargs = self._next_url_kwargs(next_url)
                    kwargs.pop("user_id", None)
                    kwargs.pop("restrict", None)
                    result = self.api.user_bookmarks_illust(user_id=int(user_id), restrict=restrict, **kwargs)
                else:
                    result = self.api.user_bookmarks_illust(user_id=int(user_id), restrict=restrict)
            except Exception as e:
                raise RuntimeError(f"拉取收藏失败(restrict={restrict}, page={page_no}): {e}")

            if not isinstance(result, dict):
                raise RuntimeError(f"收藏接口返回异常结构(restrict={restrict}, page={page_no})")
            if "illusts" not in result:
                raise RuntimeError(f"收藏接口缺少 illusts 字段(restrict={restrict}, page={page_no})")

            illusts = result.get("illusts") or []
            for illust in illusts:
                try:
                    illust_id = int(illust.get("id"))
                except Exception:
                    continue
                if illust_id in seen:
                    continue
                seen.add(illust_id)
                ids_newest_first.append(illust_id)

            if show_progress:
                self._progress_line(True, f"fetch:{restrict}", len(ids_newest_first))
            if debug:
                print(
                    f"\n[debug] restrict={restrict} page={page_no} "
                    f"page_size={len(illusts)} total={len(ids_newest_first)}"
                )

            next_url = result.get("next_url")
            if not next_url:
                break

        self._progress_done(show_progress)
        return ids_newest_first

    def _fetch_all_bookmark_ids(self, user_id, restrict, show_progress=False, debug=False):
        if restrict in ("public", "private"):
            return self._fetch_bookmark_ids_by_restrict(
                user_id=user_id,
                restrict=restrict,
                show_progress=show_progress,
                debug=debug,
            )
        if restrict == "both":
            public_ids = self._fetch_bookmark_ids_by_restrict(
                user_id=user_id,
                restrict="public",
                show_progress=show_progress,
                debug=debug,
            )
            private_ids = self._fetch_bookmark_ids_by_restrict(
                user_id=user_id,
                restrict="private",
                show_progress=show_progress,
                debug=debug,
            )
            merged = []
            seen = set()
            for pid in public_ids + private_ids:
                if pid in seen:
                    continue
                seen.add(pid)
                merged.append(pid)
            return merged
        raise ValueError(f"不支持的 restrict 值: {restrict}")

    def _build_order_map(self, ids_newest_first):
        # 最旧的收藏序号为 0，越新越大。
        order_map = {}
        for order, illust_id in enumerate(reversed(ids_newest_first)):
            order_map[illust_id] = order
        return order_map

    def _plan_metadata_changes(self, order_map, show_progress=False, debug=False):
        stats = {
            "scanned": 0,
            "changed": 0,
            "matched": 0,
            "unmatched": 0,
            "parse_failed": 0,
        }
        changed_payloads = {}
        unmatched_samples = []

        if not self.metadata_dir.exists():
            return stats, changed_payloads, unmatched_samples

        files = sorted(self.metadata_dir.glob("*.json"))
        total = len(files)
        for metadata_path in files:
            stats["scanned"] += 1
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                stats["parse_failed"] += 1
                continue

            try:
                illust_id = int(data.get("illust_id"))
            except Exception:
                try:
                    illust_id = int(metadata_path.stem)
                except Exception:
                    stats["parse_failed"] += 1
                    continue

            target_order = order_map.get(illust_id)
            if target_order is None:
                stats["unmatched"] += 1
                if len(unmatched_samples) < 10:
                    unmatched_samples.append(illust_id)
            else:
                stats["matched"] += 1

            before = json.dumps(data, ensure_ascii=False, sort_keys=True)
            if target_order is not None:
                data["bookmark_order"] = target_order
                data["is_bookmarked"] = True

            after = json.dumps(data, ensure_ascii=False, sort_keys=True)
            if before != after:
                stats["changed"] += 1
                changed_payloads[metadata_path] = data
                if debug and stats["changed"] <= 20:
                    print(
                        f"[debug] metadata changed: pid={illust_id} "
                        f"bookmark_order={data.get('bookmark_order')} "
                        f"is_bookmarked={data.get('is_bookmarked')}"
                    )

            if show_progress and stats["scanned"] % 100 == 0:
                self._progress_line(True, "metadata", stats["scanned"], total)

        self._progress_done(show_progress)
        return stats, changed_payloads, unmatched_samples

    def _plan_queue_changes(self, order_map, show_progress=False, debug=False):
        stats = {
            "scanned": 0,
            "changed": 0,
            "matched": 0,
            "unmatched": 0,
            "load_failed": 0,
        }

        if not self.queue_path.exists():
            return stats, None

        try:
            with open(self.queue_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            raise RuntimeError(f"读取任务队列失败: {self.queue_path} ({e})")

        items = payload.get("items", []) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            raise RuntimeError(f"任务队列格式异常: {self.queue_path} (items 非列表)")

        total = len(items)
        changed = False
        for item in items:
            stats["scanned"] += 1
            try:
                illust_id = int(item.get("illust_id"))
            except Exception:
                continue

            target_order = order_map.get(illust_id)
            if target_order is None:
                stats["unmatched"] += 1
            else:
                stats["matched"] += 1

            before = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if target_order is not None:
                item["bookmark_order"] = target_order
                item["is_bookmarked"] = True
                if isinstance(item.get("illust"), dict):
                    item["illust"]["bookmark_order"] = target_order
                    item["illust"]["is_bookmarked"] = True

            after = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if before != after:
                stats["changed"] += 1
                changed = True
                if debug and stats["changed"] <= 20:
                    print(
                        f"[debug] queue changed: pid={illust_id} "
                        f"bookmark_order={item.get('bookmark_order')} "
                        f"is_bookmarked={item.get('is_bookmarked')}"
                    )

            if show_progress and stats["scanned"] % 200 == 0:
                self._progress_line(True, "queue", stats["scanned"], total)

        self._progress_done(show_progress)
        if changed:
            if not isinstance(payload, dict):
                payload = {}
            payload["items"] = items
            payload["version"] = payload.get("version", 1)
            payload["updated_at"] = self._now_str()
            return stats, payload
        return stats, None

    def _load_scan_cursor_payload(self):
        if not self.scan_cursor_path.exists():
            return {
                "version": 1,
                "updated_at": self._now_str(),
                "bookmarks": {},
                "following": {
                    "authors": {},
                },
            }
        try:
            with open(self.scan_cursor_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}

        if not isinstance(data.get("bookmarks"), dict):
            data["bookmarks"] = {}
        if not isinstance(data.get("following"), dict):
            data["following"] = {"authors": {}}
        if not isinstance(data["following"].get("authors"), dict):
            data["following"]["authors"] = {}
        data["version"] = 1
        data["updated_at"] = self._now_str()
        return data

    def _plan_scan_cursor_change(self, max_bookmark_order):
        payload = self._load_scan_cursor_payload()
        payload["bookmarks"]["max_bookmark_order"] = int(max_bookmark_order)
        payload["bookmarks"]["updated_at"] = self._now_str()
        return payload

    def rebuild(self, restrict="both", dry_run=False, show_progress=False, debug=False):
        user_id = self.config.get_user_id()
        if not user_id:
            return {
                "success": False,
                "error": "未配置 user_id",
            }

        t0 = time.time()
        bookmark_ids = self._fetch_all_bookmark_ids(
            user_id=int(user_id),
            restrict=restrict,
            show_progress=show_progress,
            debug=debug,
        )
        order_map = self._build_order_map(bookmark_ids)
        max_order = max(order_map.values()) if order_map else -1

        metadata_stats, metadata_changes, metadata_unmatched_samples = self._plan_metadata_changes(
            order_map=order_map,
            show_progress=show_progress,
            debug=debug,
        )
        queue_stats, queue_payload = self._plan_queue_changes(
            order_map=order_map,
            show_progress=show_progress,
            debug=debug,
        )
        scan_cursor_payload = self._plan_scan_cursor_change(max_order)

        if not dry_run:
            for metadata_path, payload in metadata_changes.items():
                self._write_json_atomic(metadata_path, payload)
            if queue_payload is not None:
                self._write_json_atomic(self.queue_path, queue_payload)
            self._write_json_atomic(self.scan_cursor_path, scan_cursor_payload)

        return {
            "success": True,
            "restrict": restrict,
            "bookmarks_fetched": len(bookmark_ids),
            "max_bookmark_order": max_order,
            "metadata": metadata_stats,
            "queue": queue_stats,
            "metadata_unmatched_samples": metadata_unmatched_samples,
            "queue_updated": queue_payload is not None,
            "scan_cursor_updated": True,
            "dry_run": bool(dry_run),
            "elapsed_seconds": round(time.time() - t0, 2),
        }

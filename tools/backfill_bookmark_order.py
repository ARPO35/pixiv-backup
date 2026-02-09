#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pixivpy3 import AppPixivAPI


def load_refresh_token(output_dir: Path, token_file: str, explicit_token: str):
    if explicit_token:
        return explicit_token

    token_path = Path(token_file) if token_file else (output_dir / "data" / "token.json")
    if not token_path.exists():
        raise FileNotFoundError(f"token 文件不存在: {token_path}")

    with open(token_path, "r", encoding="utf-8") as f:
        token_data = json.load(f)
    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        raise ValueError(f"token 文件缺少 refresh_token 字段: {token_path}")
    return refresh_token


def next_url_kwargs(next_url: str):
    parsed = urlparse(next_url)
    query_params = parse_qs(parsed.query)
    return {k: v[0] for k, v in query_params.items() if v}


def fetch_all_bookmark_ids(api, user_id: int, restrict: str):
    ids_newest_first = []
    seen = set()
    next_url = None

    while True:
        if next_url:
            kwargs = next_url_kwargs(next_url)
            kwargs.pop("user_id", None)
            kwargs.pop("restrict", None)
            result = api.user_bookmarks_illust(user_id=user_id, restrict=restrict, **kwargs)
        else:
            result = api.user_bookmarks_illust(user_id=user_id, restrict=restrict)

        illusts = (result or {}).get("illusts") or []
        for illust in illusts:
            illust_id = int(illust.get("id"))
            if illust_id in seen:
                continue
            seen.add(illust_id)
            ids_newest_first.append(illust_id)

        next_url = (result or {}).get("next_url")
        if not next_url:
            break

    return ids_newest_first


def build_order_map(ids_newest_first):
    # 最旧的收藏序号为 0，越新越大。
    order_map = {}
    for order, illust_id in enumerate(reversed(ids_newest_first)):
        order_map[illust_id] = order
    return order_map


def rewrite_metadata(metadata_dir: Path, order_map, dry_run: bool):
    changed = 0
    scanned = 0
    missing = 0

    if not metadata_dir.exists():
        return scanned, changed, missing

    for metadata_path in metadata_dir.glob("*.json"):
        scanned += 1
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        try:
            illust_id = int(data.get("illust_id"))
        except Exception:
            illust_id = int(metadata_path.stem)

        target_order = order_map.get(illust_id)
        before = json.dumps(data, ensure_ascii=False, sort_keys=True)

        if target_order is None:
            missing += 1
            if data.get("bookmark_order", None) is not None:
                data["bookmark_order"] = None
            if bool(data.get("is_bookmarked", False)):
                data["is_bookmarked"] = False
        else:
            data["bookmark_order"] = target_order
            data["is_bookmarked"] = True

        after = json.dumps(data, ensure_ascii=False, sort_keys=True)
        if before == after:
            continue

        changed += 1
        if not dry_run:
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    return scanned, changed, missing


def rewrite_task_queue(queue_path: Path, order_map, dry_run: bool):
    if not queue_path.exists():
        return 0, 0

    with open(queue_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    items = payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return 0, 0

    scanned = 0
    changed = 0
    for item in items:
        scanned += 1
        try:
            illust_id = int(item.get("illust_id"))
        except Exception:
            continue

        target_order = order_map.get(illust_id)
        before = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if target_order is None:
            item["bookmark_order"] = None
            item["is_bookmarked"] = False
            if isinstance(item.get("illust"), dict):
                item["illust"]["bookmark_order"] = None
                item["illust"]["is_bookmarked"] = False
        else:
            item["bookmark_order"] = target_order
            item["is_bookmarked"] = True
            if isinstance(item.get("illust"), dict):
                item["illust"]["bookmark_order"] = target_order
                item["illust"]["is_bookmarked"] = True

        after = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if before != after:
            changed += 1

    if changed > 0 and not dry_run:
        payload["items"] = items
        with open(queue_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    return scanned, changed


def main():
    parser = argparse.ArgumentParser(description="全量回填 metadata/task_queue 的 bookmark_order 字段")
    parser.add_argument("--output-dir", required=True, help="备份输出目录，例如 /mnt/sda1/pixiv-backup")
    parser.add_argument("--user-id", type=int, required=True, help="Pixiv 用户 ID")
    parser.add_argument("--restrict", default="public", choices=["public", "private"], help="收藏可见性")
    parser.add_argument("--token-file", default="", help="token.json 路径，默认 <output_dir>/data/token.json")
    parser.add_argument("--refresh-token", default="", help="直接传 refresh_token（优先级高于 token-file）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不落盘")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser().resolve()
    metadata_dir = output_dir / "metadata"
    queue_path = output_dir / "data" / "task_queue.json"
    refresh_token = load_refresh_token(output_dir, args.token_file, args.refresh_token)

    api = AppPixivAPI()
    api.auth(refresh_token=refresh_token)

    bookmark_ids = fetch_all_bookmark_ids(api, user_id=args.user_id, restrict=args.restrict)
    order_map = build_order_map(bookmark_ids)

    meta_scanned, meta_changed, meta_missing = rewrite_metadata(metadata_dir, order_map, dry_run=args.dry_run)
    queue_scanned, queue_changed = rewrite_task_queue(queue_path, order_map, dry_run=args.dry_run)

    print(f"bookmarks_fetched={len(bookmark_ids)}")
    print(f"metadata_scanned={meta_scanned}")
    print(f"metadata_changed={meta_changed}")
    print(f"metadata_not_in_bookmark={meta_missing}")
    print(f"queue_scanned={queue_scanned}")
    print(f"queue_changed={queue_changed}")
    print(f"dry_run={args.dry_run}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import argparse
import json
import sys
import time
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


def progress_line(enabled: bool, label: str, current: int, total: int = None):
    if not enabled:
        return
    if total and total > 0:
        pct = (current / total) * 100
        sys.stdout.write(f"\r[{label}] {current}/{total} ({pct:.1f}%)")
    else:
        sys.stdout.write(f"\r[{label}] {current}")
    sys.stdout.flush()


def progress_done(enabled: bool):
    if enabled:
        sys.stdout.write("\n")
        sys.stdout.flush()


def fetch_bookmark_ids_by_restrict(api, user_id: int, restrict: str, show_progress: bool = False, debug: bool = False):
    ids_newest_first = []
    seen = set()
    next_url = None
    page_no = 0

    while True:
        page_no += 1
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

        if show_progress:
            progress_line(True, f"fetch:{restrict}", len(ids_newest_first))
        if debug:
            print(f"\n[debug] restrict={restrict} page={page_no} page_size={len(illusts)} total={len(ids_newest_first)}")

        next_url = (result or {}).get("next_url")
        if not next_url:
            break

    progress_done(show_progress)
    return ids_newest_first


def build_order_map(ids_newest_first):
    # 最旧的收藏序号为 0，越新越大。
    order_map = {}
    for order, illust_id in enumerate(reversed(ids_newest_first)):
        order_map[illust_id] = order
    return order_map


def rewrite_metadata(metadata_dir: Path, order_map, dry_run: bool, show_progress: bool = False, debug: bool = False):
    changed = 0
    scanned = 0
    missing = 0
    parse_failed = 0
    non_null_count = 0

    if not metadata_dir.exists():
        return {
            "scanned": scanned,
            "changed": changed,
            "missing": missing,
            "parse_failed": parse_failed,
            "non_null_count": non_null_count,
        }

    files = sorted(metadata_dir.glob("*.json"))
    total = len(files)

    for metadata_path in files:
        scanned += 1
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            parse_failed += 1
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

        if data.get("bookmark_order") is not None:
            non_null_count += 1

        after = json.dumps(data, ensure_ascii=False, sort_keys=True)
        if before == after:
            if show_progress and scanned % 100 == 0:
                progress_line(True, "metadata", scanned, total)
            continue

        changed += 1
        if debug and changed <= 20:
            print(
                f"[debug] metadata changed: pid={illust_id} "
                f"bookmark_order={data.get('bookmark_order')} is_bookmarked={data.get('is_bookmarked')}"
            )
        if not dry_run:
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        if show_progress and scanned % 100 == 0:
            progress_line(True, "metadata", scanned, total)

    progress_done(show_progress)
    return {
        "scanned": scanned,
        "changed": changed,
        "missing": missing,
        "parse_failed": parse_failed,
        "non_null_count": non_null_count,
    }


def rewrite_task_queue(queue_path: Path, order_map, dry_run: bool, show_progress: bool = False, debug: bool = False):
    if not queue_path.exists():
        return {
            "scanned": 0,
            "changed": 0,
            "matched": 0,
            "unmatched": 0,
        }

    with open(queue_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    items = payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return {
            "scanned": 0,
            "changed": 0,
            "matched": 0,
            "unmatched": 0,
        }

    scanned = 0
    changed = 0
    matched = 0
    unmatched = 0
    total = len(items)
    for item in items:
        scanned += 1
        try:
            illust_id = int(item.get("illust_id"))
        except Exception:
            continue

        target_order = order_map.get(illust_id)
        if target_order is None:
            unmatched += 1
        else:
            matched += 1
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
            if debug and changed <= 20:
                print(
                    f"[debug] queue changed: pid={illust_id} "
                    f"bookmark_order={item.get('bookmark_order')} is_bookmarked={item.get('is_bookmarked')}"
                )

        if show_progress and scanned % 200 == 0:
            progress_line(True, "queue", scanned, total)

    if changed > 0 and not dry_run:
        payload["items"] = items
        with open(queue_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    progress_done(show_progress)
    return {
        "scanned": scanned,
        "changed": changed,
        "matched": matched,
        "unmatched": unmatched,
    }


def fetch_all_bookmark_ids(api, user_id: int, restrict: str, show_progress: bool = False, debug: bool = False):
    if restrict in ("public", "private"):
        return fetch_bookmark_ids_by_restrict(
            api,
            user_id=user_id,
            restrict=restrict,
            show_progress=show_progress,
            debug=debug,
        )

    if restrict == "both":
        public_ids = fetch_bookmark_ids_by_restrict(
            api,
            user_id=user_id,
            restrict="public",
            show_progress=show_progress,
            debug=debug,
        )
        private_ids = fetch_bookmark_ids_by_restrict(
            api,
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


def main():
    parser = argparse.ArgumentParser(description="全量回填 metadata/task_queue 的 bookmark_order 字段")
    parser.add_argument("--output-dir", required=True, help="备份输出目录，例如 /mnt/sda1/pixiv-backup")
    parser.add_argument("--user-id", type=int, required=True, help="Pixiv 用户 ID")
    parser.add_argument("--restrict", default="public", choices=["public", "private", "both"], help="收藏可见性（both=public+private）")
    parser.add_argument("--token-file", default="", help="token.json 路径，默认 <output_dir>/data/token.json")
    parser.add_argument("--refresh-token", default="", help="直接传 refresh_token（优先级高于 token-file）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不落盘")
    parser.add_argument("--progress", action="store_true", help="显示进度条")
    parser.add_argument("--debug", action="store_true", help="打印调试信息（含前20条变更样例）")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser().resolve()
    metadata_dir = output_dir / "metadata"
    queue_path = output_dir / "data" / "task_queue.json"
    refresh_token = load_refresh_token(output_dir, args.token_file, args.refresh_token)

    api = AppPixivAPI()
    api.auth(refresh_token=refresh_token)

    t0 = time.time()
    bookmark_ids = fetch_all_bookmark_ids(
        api,
        user_id=args.user_id,
        restrict=args.restrict,
        show_progress=args.progress,
        debug=args.debug,
    )
    order_map = build_order_map(bookmark_ids)

    metadata_stats = rewrite_metadata(
        metadata_dir,
        order_map,
        dry_run=args.dry_run,
        show_progress=args.progress,
        debug=args.debug,
    )
    queue_stats = rewrite_task_queue(
        queue_path,
        order_map,
        dry_run=args.dry_run,
        show_progress=args.progress,
        debug=args.debug,
    )

    print(f"bookmarks_fetched={len(bookmark_ids)}")
    print(f"metadata_scanned={metadata_stats['scanned']}")
    print(f"metadata_changed={metadata_stats['changed']}")
    print(f"metadata_not_in_bookmark={metadata_stats['missing']}")
    print(f"metadata_parse_failed={metadata_stats['parse_failed']}")
    print(f"metadata_bookmark_order_non_null={metadata_stats['non_null_count']}")
    print(f"queue_scanned={queue_stats['scanned']}")
    print(f"queue_changed={queue_stats['changed']}")
    print(f"queue_matched_bookmark={queue_stats['matched']}")
    print(f"queue_unmatched_bookmark={queue_stats['unmatched']}")
    print(f"dry_run={args.dry_run}")
    print(f"elapsed_seconds={time.time() - t0:.2f}")


if __name__ == "__main__":
    main()

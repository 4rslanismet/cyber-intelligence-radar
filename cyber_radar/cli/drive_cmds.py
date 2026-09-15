#!/usr/bin/env python3
"""Drive Queue V1 CLI (bkz. docs/GOOGLE_DRIVE.md, src/drive_queue.py,
src/drive_worker.py). `cyber-radar-drive-sync.timer` normalde `run`
komutunu tetikler; diğer alt komutlar operasyonel görünürlük/manuel
müdahale içindir.

Kullanım:
    python3 -m scripts.drive_queue status
    python3 -m scripts.drive_queue scan
    python3 -m scripts.drive_queue run [--max-runtime-minutes N]
    python3 -m scripts.drive_queue retry <item_id>
    python3 -m scripts.drive_queue verify <item_id>
"""
from __future__ import annotations

import argparse
import json
import sys

from .. import drive_queue, drive_worker


def cmd_status(_args: argparse.Namespace) -> int:
    state = drive_queue.load_state()
    summary = drive_queue.pending_summary(state)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(
        f"bugün yüklenen: {state.get('bytes_uploaded_today', 0)} bayt, "
        f"{state.get('files_completed_today', 0)} dosya "
        f"(kalan bayt bütçesi: {drive_queue.remaining_byte_budget(state)}, "
        f"kalan dosya bütçesi: {drive_queue.remaining_file_budget(state)})"
    )
    return 0


def cmd_scan(_args: argparse.Namespace) -> int:
    state = drive_queue.load_state()
    added = drive_queue.scan_allowed_roots(state)
    drive_queue.save_state(state)
    print(f"{added} yeni dosya kuyruğa eklendi.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    result = drive_worker.run_worker(max_runtime_minutes=args.max_runtime_minutes)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["stop_reason"] != drive_worker.STOP_STATE_CORRUPTION else 1


def cmd_retry(args: argparse.Namespace) -> int:
    state = drive_queue.load_state()
    item = drive_queue.find_item(state, args.item_id)
    if item is None:
        print(f"item bulunamadı: {args.item_id}", file=sys.stderr)
        return 1
    item["status"] = drive_queue.STATUS_QUEUED
    item["attempts"] = 0
    item["last_error"] = None
    drive_queue.save_state(state)
    print(f"{args.item_id} yeniden kuyruğa alındı (status=queued, attempts=0).")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    state = drive_queue.load_state()
    item = drive_queue.find_item(state, args.item_id)
    if item is None:
        print(f"item bulunamadı: {args.item_id}", file=sys.stderr)
        return 1
    if not item.get("remote_file_id"):
        print(f"{args.item_id}: henüz Drive'a yüklenmemiş (remote_file_id yok).", file=sys.stderr)
        return 1
    from .. import gdrive

    remote = gdrive.get_file_metadata(item["remote_file_id"])
    ok = (
        remote.get("size") is not None
        and int(remote["size"]) == item["size"]
        and not remote.get("trashed", False)
    )
    print(json.dumps({"item_id": args.item_id, "remote": remote, "verified": ok}, indent=2, ensure_ascii=False))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Drive Queue V1 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Kuyruk özeti + günlük bütçe durumu").set_defaults(func=cmd_status)
    sub.add_parser("scan", help="Allowed-roots'u tarayıp yeni dosyaları kuyruğa ekler").set_defaults(func=cmd_scan)

    run_parser = sub.add_parser("run", help="Worker'ı bir kez çalıştırır (bkz. src/drive_worker.py)")
    run_parser.add_argument("--max-runtime-minutes", type=float, default=None)
    run_parser.set_defaults(func=cmd_run)

    retry_parser = sub.add_parser("retry", help="Belirli bir item'ı yeniden kuyruğa alır")
    retry_parser.add_argument("item_id")
    retry_parser.set_defaults(func=cmd_retry)

    verify_parser = sub.add_parser("verify", help="Belirli bir item'ı Drive'daki güncel haliyle karşılaştırır")
    verify_parser.add_argument("item_id")
    verify_parser.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

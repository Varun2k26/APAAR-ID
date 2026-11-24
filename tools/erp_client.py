#!/usr/bin/env python3
"""Sample institution-ERP client for APAAR Registry (standard library only).

Pushes a CSV of enrolments to the batch API with an API key, an Idempotency-Key (safe retries)
and gzip compression (low-bandwidth links), then prints the row-level report.

    python3 tools/erp_client.py --key ask_... data/demo/1_aarohan_new_admissions.csv
    python3 tools/erp_client.py --key ask_... --idempotency-key batch-7 file.csv   # re-run = replayed
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv_file")
    ap.add_argument("--base", default=os.environ.get("SPINE_URL", "http://localhost:8000"))
    ap.add_argument("--key", default=os.environ.get("SPINE_API_KEY"), help="institution API key (or SPINE_API_KEY)")
    ap.add_argument("--idempotency-key", help="defaults to a hash of the file, so re-sending the same file is a no-op")
    args = ap.parse_args()
    if not args.key:
        ap.error("an API key is required (--key or SPINE_API_KEY); create one under ERP integration")

    with open(args.csv_file, newline="", encoding="utf-8-sig") as f:
        records = [{k.strip().lower(): v for k, v in row.items()} for row in csv.DictReader(f)]
    raw = json.dumps({"records": records}).encode()
    idem = args.idempotency_key or "file-" + hashlib.sha256(raw).hexdigest()[:24]
    body = gzip.compress(raw)
    req = urllib.request.Request(f"{args.base}/api/v1/enrollments/batch", data=body, method="POST", headers={
        "Content-Type": "application/json", "Content-Encoding": "gzip", "X-API-Key": args.key, "Idempotency-Key": idem})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            rep = json.load(r)
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()}", file=sys.stderr)
        return 1
    print(f"submission #{rep['submission_id']}{' (replayed: already processed)' if rep.get('replayed') else ''}")
    print(f"  sent {len(raw):,} bytes as {len(body):,} gzip bytes")
    print(f"  total {rep['total']} | created {rep['created']} | updated {rep['updated']} | unchanged {rep['unchanged']}"
          f" | conflicts {rep['conflict']} | quarantined {rep['rejected']} | warnings {rep['warnings']}")
    for row in rep.get("rows", []):
        for f in row["findings"]:
            print(f"  row {row['row']:>4} {row['roll_no'] or '':<12} {f['severity']:<5} {f['code']}  {f['message']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

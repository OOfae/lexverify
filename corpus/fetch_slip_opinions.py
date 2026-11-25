"""Fetch a small, fixed corpus of public US Supreme Court slip opinions.

Why these: they are US Government works, in the public domain, published as PDFs
with stable URLs, and they contain the kind of language a legal analysis quotes.
Court filings from PACER/CourtListener are a better corpus for production use;
they need a token and carry redaction work, so this script deliberately starts
with the version anyone can rebuild with no key.

The script records the URL, fetch time and SHA-256 of every file it writes, so
the corpus can be audited rather than trusted.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

INDEX_URL = "https://www.supremecourt.gov/opinions/slipopinion/23"
DEST = Path(__file__).resolve().parent / "docs"
PROVENANCE = Path(__file__).resolve().parent / "provenance.json"
USER_AGENT = "lexverify-corpus/0.1 (research; contact: local)"


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main(limit: int = 8) -> int:
    print(f"index: {INDEX_URL}")
    page = fetch(INDEX_URL).decode("utf-8", errors="replace")
    links = sorted(set(re.findall(r"/opinions/23pdf/[^\"']+\.pdf", page)))[:limit]
    if not links:
        print("no PDF links found; the index layout may have changed", file=sys.stderr)
        return 1

    DEST.mkdir(parents=True, exist_ok=True)
    records = []
    for link in links:
        url = "https://www.supremecourt.gov" + link
        name = Path(link).name
        target = DEST / name
        if not target.exists():
            target.write_bytes(fetch(url))
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        records.append(
            {
                "file": name,
                "url": url,
                "sha256": digest,
                "bytes": target.stat().st_size,
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "licence": "US Government work, public domain (17 U.S.C. 105)",
            }
        )
        print(f"  {name:34s} {digest[:16]}… {target.stat().st_size:>8d} bytes")

    PROVENANCE.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    print(f"provenance: {PROVENANCE}")
    return 0


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    raise SystemExit(main(count))

"""Phase 7: download a real SNDlib dynamic traffic-matrix archive and extract the demand-matrix
files a real_traffic_dir scenario needs (src/simulate/real_traffic.py), into data/raw/ (gitignored).

    python scripts/fetch_sndlib_traffic.py --network abilene --limit 48
    python scripts/fetch_sndlib_traffic.py --network abilene --limit -1   # every matrix (48096 files, ~400MB)

Each SNDlib network with dynamic traffic publishes one archive of per-5-minute native-format
demand-matrix files (one network, one archive; this script only knows the real, verified URL for
Abilene -- pass --url for any other network's archive page at sndlib.put.poznan.pl). The archive
itself is large (Abilene's is ~47MB, 48096 files over 6 months), so by default this keeps only the
chronologically-first --limit files -- plenty for a demo scenario, since each file becomes one
simulation step (src/simulate/graph_sim.py's Scenario.steps must equal the file count).

This script needs real internet access and is meant to be run on your own machine, not in a
restricted sandbox. The base network file (e.g. abilene.txt) is not fetched here: there is no
project script for SNDlib network files yet (unlike scripts/fetch_topology_zoo.py for Topology
Zoo), so place it manually in data/raw/sndlib/networks/ -- download it from
https://sndlib.put.poznan.pl/<network>.overview.action.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cli import rel, run
from src.config import load_config, project_dir
from src.errors import TopologyError
from src.simulate.real_traffic import extract_matrix_files

#: Verified via the SNDlib site (sndlib.put.poznan.pl/<network>.overview.action); add more here as
#: they're confirmed real rather than guessed from the URL pattern.
ARCHIVE_URLS = {
    "abilene": "https://sndlib.put.poznan.pl/download/directed-abilene-zhang-5min-over-6months-ALL-native.tgz",
}
MAX_BYTES = 100 * 1024 * 1024


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as resp:
        data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise TopologyError(f"{url} is larger than {MAX_BYTES} bytes; refusing")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--network", default="abilene", help="SNDlib network name, e.g. abilene")
    parser.add_argument("--url", default=None, help="archive URL override, for a network not in ARCHIVE_URLS")
    parser.add_argument("--limit", type=int, default=48,
                        help="keep only the first N files in chronological order (-1 = keep all; "
                             "default 48 = 4 hours of 5-minute Abilene matrices)")
    parser.add_argument("--force", action="store_true", help="re-download even if the archive is cached")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", args.network):
        raise SystemExit(f"error: invalid network name '{args.network}'")

    url = args.url or ARCHIVE_URLS.get(args.network)
    if url is None:
        raise SystemExit(f"error: no known archive URL for '{args.network}'; pass --url "
                         f"(see https://sndlib.put.poznan.pl/{args.network}.overview.action)")

    cfg = load_config(args.config)
    raw_dir = project_dir(cfg, "raw_dir")
    cache = raw_dir / "sndlib" / "traffic-matrices" / f"{args.network}.tgz"
    dest_dir = raw_dir / "sndlib" / "traffic-matrices" / args.network

    if cache.is_file() and not args.force:
        print(f"using cached archive: {rel(cache)}")
        archive_bytes = cache.read_bytes()
    else:
        print(f"downloading {url}")
        try:
            archive_bytes = download(url)
        except (urllib.error.URLError, TimeoutError, TopologyError) as exc:
            raise TopologyError(f"download failed: {exc}") from exc
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(archive_bytes)
        print(f"  cached {rel(cache)} ({len(archive_bytes)} bytes)")

    limit = None if args.limit < 0 else args.limit
    written = extract_matrix_files(archive_bytes, dest_dir, limit)
    if not written:
        raise TopologyError(f"no demandMatrix-*.txt files found in {url}")
    print(f"extracted {len(written)} demand-matrix file(s) to {rel(dest_dir)}"
          + ("" if limit is None else f" (--limit {limit}; the archive has more)"))
    print(f"files: {written[0].name} .. {written[-1].name}")
    print(f"next: point a scenario's \"real_traffic_dir\" at {rel(dest_dir)} and \"topology\" at "
          f"your SNDlib {args.network} network file, with \"steps\": {len(written)}")
    return 0


if __name__ == "__main__":
    run(main)

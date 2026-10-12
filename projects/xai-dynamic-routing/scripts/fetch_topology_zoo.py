"""Phase 7: download one Internet Topology Zoo network into data/raw/ (gitignored) and validate it.

    python scripts/fetch_topology_zoo.py --name Geant2012
    python scripts/fetch_topology_zoo.py --name Abilene --source github

Sources (tried in this order with --source auto):
  zoo     http://www.topology-zoo.org/files/<name>.gml       (processed export, has coordinates)
  mirror  https://raw.githubusercontent.com/mroughan/InternetTopologyZoo/HEAD/gml/<name>.gml
          (the Zoo authors' long-term data store: the same GML export, with coordinates;
          used when topology-zoo.org is unreachable, fault F-017)
  github  https://raw.githubusercontent.com/sk2/topologyzoo/master/sources/<name>.graphml
          (the dataset author's source annotations; no coordinates, link speed as free text)
Files are a few KB. The data is CC BY 4.0: cite Knight et al., "The Internet Topology Zoo",
IEEE JSAC 29(9), 2011, when using it.
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
from src.topology.provenance import provenance_summary
from src.topology.zoo import load_zoo

SOURCES = {
    "zoo": ("http://www.topology-zoo.org/files/{name}.gml", ".gml", b"graph"),
    "mirror": ("https://raw.githubusercontent.com/mroughan/InternetTopologyZoo/HEAD/gml/{name}.gml", ".gml",
               b"graph"),
    "github": ("https://raw.githubusercontent.com/sk2/topologyzoo/master/sources/{name}.graphml",
               ".graphml", b"<graphml"),
}
MAX_BYTES = 5 * 1024 * 1024


def download(url: str, marker: bytes) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise TopologyError(f"{url} is larger than {MAX_BYTES} bytes; refusing")
    if marker not in data[:4000]:
        raise TopologyError(f"{url} did not return the expected file type")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", default="Geant2012", help="Topology Zoo network name, e.g. Geant2012, Abilene")
    parser.add_argument("--source", choices=["auto", "zoo", "mirror", "github"], default="auto")
    parser.add_argument("--force", action="store_true", help="re-download even if a file exists")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", args.name):
        raise SystemExit(f"error: invalid topology name '{args.name}'")

    cfg = load_config(args.config)
    raw_dir = project_dir(cfg, "raw_dir")
    order = ["zoo", "mirror", "github"] if args.source == "auto" else [args.source]
    existing = [raw_dir / f"{args.name}{SOURCES[s][1]}" for s in order
                if (raw_dir / f"{args.name}{SOURCES[s][1]}").is_file()]
    target = None
    if existing and not args.force:
        target = existing[0]
        print(f"already present: {rel(target)}")
    else:
        errors = []
        for source in order:
            url_tpl, suffix, marker = SOURCES[source]
            url = url_tpl.format(name=args.name)
            print(f"downloading {url}")
            try:
                data = download(url, marker)
            except (urllib.error.URLError, TimeoutError, TopologyError) as exc:
                print(f"  failed: {exc}")
                errors.append(f"{source}: {exc}")
                continue
            target = raw_dir / f"{args.name}{suffix}"
            target.write_bytes(data)
            print(f"  saved {rel(target)} ({len(data)} bytes)")
            break
        if target is None:
            raise TopologyError("all sources failed (" + "; ".join(errors) +
                                f"); place <name>.gml or <name>.graphml manually in {raw_dir}")

    graph = load_zoo(target, cfg)
    print(f"loaded {graph.graph['name']}: nodes={graph.number_of_nodes()} edges={graph.number_of_edges()} "
          f"components={graph.graph['components']}")
    print("metric provenance per edge (documented / estimated / synthetic / default):")
    for metric, counts in provenance_summary(graph).items():
        print(f"  {metric:<14} " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    print(f"next: python scripts/compare.py --topology {rel(target)}")
    return 0


if __name__ == "__main__":
    run(main)

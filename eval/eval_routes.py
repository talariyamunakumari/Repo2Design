"""Measure route-extraction precision/recall (no LLM needed).

Usage:  python -m eval.eval_routes eval/ground_truth.json
Ground truth lists routes exactly as written in the decorators/calls (no router prefixes).
"""
import json
import shutil
import sys

from app import ingest
from app.analyze import extract_routes, ext_of, SOURCE_EXT


def norm(p):
    return (p.rstrip("/") or "/")


def main(path):
    truth = json.load(open(path))
    tp = fp = fn = 0
    for item in truth:
        _, _, url = ingest.parse_repo_url(item["repo_url"])
        root = ingest.clone(url)
        try:
            found = set()
            for rel, text in ingest.load_files(root):
                if ext_of(rel) in SOURCE_EXT:
                    found |= {norm(r["path"]) for r in extract_routes(rel, text)}
        finally:
            shutil.rmtree(root, ignore_errors=True)
        expected = {norm(r) for r in item["routes"]}
        t, f_p, f_n = len(found & expected), len(found - expected), len(expected - found)
        tp, fp, fn = tp + t, fp + f_p, fn + f_n
        print(f"{item['repo_url']}: TP={t} FP={f_p} FN={f_n}")
        if f_p: print("  extra  :", sorted(found - expected)[:10])
        if f_n: print("  missing:", sorted(expected - found)[:10])
    p = tp / (tp + fp) if tp + fp else 0
    r = tp / (tp + fn) if tp + fn else 0
    print(f"\nPRECISION={p:.2%} RECALL={r:.2%}  (TP={tp} FP={fp} FN={fn})")


if __name__ == "__main__":
    main(sys.argv[1])

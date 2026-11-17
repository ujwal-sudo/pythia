"""Print one row per run: params, tokens/s, val loss at each eval."""
import json
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "runs/shapes")
for run in sorted(p for p in root.iterdir() if (p / "log.jsonl").exists()):
    rows = [json.loads(line) for line in (run / "log.jsonl").read_text().splitlines()]
    train = [r for r in rows if "loss" in r]
    val = [(r["step"], r["val_loss"]) for r in rows if "val_loss" in r]
    speed = sorted(r["tok_s"] for r in train[2:]) or [0]
    status = "done" if (run / "DONE").exists() else f"at step {train[-1]['step'] if train else 0}"
    print(f"{run.name:10s} {status:14s} median tok/s {speed[len(speed) // 2]:6d}  "
          + "  ".join(f"s{s}:{v:.3f}" for s, v in val))

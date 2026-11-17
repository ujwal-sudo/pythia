#!/usr/bin/env bash
# LR sweep for the chosen shape (C, now train.py's default), same budget as compare_shapes.sh.
#   bash scripts/experiments/lr_sweep.sh     (~3.5 h on an RTX 3050)
# lr 6e-4 is reused from runs/shapes/C_20x768 (identical config). Summary:
#   python scripts/experiments/summarize.py runs/lr
set -u
cd "$(dirname "$0")/../.."
COMMON=(--data data/tokenized/pythia-bpe-32k-v1 --seq-len 2048 --micro-batch 1 --grad-accum 16
        --max-steps 1500 --warmup 100 --schedule wsd --decay-frac 0.2
        --log-every 25 --eval-every 250 --eval-batches 40 --ckpt-every 0 --compile --seed 1337)
mkdir -p runs/lr
[ -e runs/lr/lr6e-4 ] || ln -s ../shapes/C_20x768 runs/lr/lr6e-4
for lr in 3e-4 1.2e-3; do
  out=runs/lr/lr$lr
  if [ -f "$out/DONE" ]; then echo "skip $lr (done)"; continue; fi
  rm -rf "$out"
  echo "=== lr=$lr start $(date -Is)"
  python -W ignore train.py "${COMMON[@]}" --lr "$lr" --out "$out"
  rc=$?
  [ $rc -eq 0 ] && touch "$out/DONE"
  echo "=== lr=$lr end $(date -Is) exit=$rc"
done

#!/usr/bin/env bash
# Shape comparison at equal params (~160M), equal tokens (~49M), same seed and data.
#   bash scripts/experiments/compare_shapes.sh      (from repo root; ~6 h on an RTX 3050)
# Results: runs/shapes/<name>/log.jsonl; summary: python scripts/experiments/summarize.py runs/shapes
set -u
cd "$(dirname "$0")/../.."
COMMON=(--data data/tokenized/pythia-bpe-32k-v1 --seq-len 2048 --micro-batch 1 --grad-accum 16
        --max-steps 1500 --warmup 100 --lr 6e-4 --schedule wsd --decay-frac 0.2
        --log-every 25 --eval-every 250 --eval-batches 40 --ckpt-every 0 --compile --seed 1337)
declare -A SHAPES=(
  [A_12x768]="--num-layers 12 --hidden-size 768 --n-q-heads 12 --n-kv-heads 2 --ffn-size 4320"
  [C_20x768]="--num-layers 20 --hidden-size 768 --n-q-heads 12 --n-kv-heads 4 --ffn-size 2304"
  [D_32x576]="--num-layers 32 --hidden-size 576 --n-q-heads 9 --n-kv-heads 3 --ffn-size 2048"
)
for name in A_12x768 C_20x768 D_32x576; do
  out=runs/shapes/$name
  if [ -f "$out/DONE" ]; then echo "skip $name (done)"; continue; fi
  rm -rf "$out"
  echo "=== $name start $(date -Is)"
  # shellcheck disable=SC2086
  python -W ignore train.py "${COMMON[@]}" ${SHAPES[$name]} --out "$out"
  rc=$?
  [ $rc -eq 0 ] && touch "$out/DONE"
  echo "=== $name end $(date -Is) exit=$rc"
done

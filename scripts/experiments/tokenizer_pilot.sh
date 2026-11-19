#!/usr/bin/env bash
# Tokenizer A/B: same shape C, lr, steps and source text; only the tokenizer differs.
#   bash scripts/experiments/tokenizer_pilot.sh      (~3.5 h on an RTX 3050)
# Compare val_bpb (bits per byte, tokenizer-independent), not val_loss (per token).
# pilot-D holds candidate D's shards and tokenizer.json (same documents as v1's two shards).
set -u
cd "$(dirname "$0")/../.."
COMMON=(--seq-len 2048 --micro-batch 1 --grad-accum 16 --max-steps 1500 --warmup 100 --lr 6e-4
        --schedule wsd --decay-frac 0.2 --log-every 25 --eval-every 250 --eval-batches 40
        --ckpt-every 0 --compile --seed 1337)
declare -A DATA=([v1]=data/tokenized/pythia-bpe-32k-v1 [D]=data/tokenized/pilot-D)
declare -A TOK=([v1]=tokenizer/pythia-bpe-32k-v1/tokenizer.json [D]=data/tokenized/pilot-D/tokenizer.json)
for name in D v1; do
  out=runs/tok/$name
  if [ -f "$out/DONE" ]; then echo "skip $name (done)"; continue; fi
  rm -rf "$out"
  echo "=== $name start $(date -Is)"
  python -W ignore train.py "${COMMON[@]}" --data "${DATA[$name]}" --tokenizer "${TOK[$name]}" --out "$out"
  rc=$?
  [ $rc -eq 0 ] && touch "$out/DONE"
  echo "=== $name end $(date -Is) exit=$rc"
done

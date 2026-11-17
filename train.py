"""Pretrain Pythia on uint16 token shards.

    python train.py --data data/tokenized/pythia-bpe-32k-v1 --out runs/smoke --max-steps 200
    python train.py ... --resume                  # continue from runs/<name>/ckpt.pt
    python train.py ... --overfit                 # one fixed batch: loss must go to ~0

Batches are random seq_len windows over the concatenated *.train.bin files
(documents are EOS-separated). Batch i is a pure function of (seed, i), so a
resumed run sees exactly the batches an uninterrupted run would.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path

import torch

from models import PythiaModel, count_parameters

MODEL_KEYS = ("hidden_size", "num_layers", "n_q_heads", "n_kv_heads", "ffn_size", "rope_theta")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", required=True, help="directory holding *.train.bin / *.val.bin")
    p.add_argument("--out", required=True)
    # model (defaults = Pythia-160M, shape C: won runs/shapes 2026-11-17)
    p.add_argument("--hidden-size", type=int, default=768)
    p.add_argument("--num-layers", type=int, default=20)
    p.add_argument("--n-q-heads", type=int, default=12)
    p.add_argument("--n-kv-heads", type=int, default=4)
    p.add_argument("--ffn-size", type=int, default=2304)
    p.add_argument("--rope-theta", type=float, default=1_000_000.0)
    p.add_argument("--seq-len", type=int, default=2048)
    # optimisation
    p.add_argument("--micro-batch", type=int, default=4)
    p.add_argument("--grad-accum", type=int, default=1)
    p.add_argument("--max-steps", type=int, default=1000)
    p.add_argument("--lr", type=float, default=6e-4)
    p.add_argument("--min-lr-ratio", type=float, default=0.1)
    p.add_argument("--warmup", type=int, default=100)
    p.add_argument("--schedule", choices=("wsd", "cosine"), default="wsd")
    p.add_argument("--decay-frac", type=float, default=0.15, help="wsd: final fraction spent decaying")
    p.add_argument("--weight-decay", type=float, default=0.1)
    p.add_argument("--beta2", type=float, default=0.95)
    p.add_argument("--grad-clip", type=float, default=1.0)
    # runtime
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    p.add_argument("--dtype", choices=("bf16", "fp16", "fp32"), default="bf16")
    p.add_argument("--attn-impl", default="auto")
    p.add_argument("--compile", action="store_true")
    p.add_argument("--grad-ckpt", action="store_true", help="recompute block activations to save memory")
    p.add_argument("--seed", type=int, default=1337)
    p.add_argument("--log-every", type=int, default=10)
    p.add_argument("--eval-every", type=int, default=200)
    p.add_argument("--eval-batches", type=int, default=20)
    p.add_argument("--ckpt-every", type=int, default=500, help="0 = never save (benchmarks)")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--overfit", action="store_true")
    return p.parse_args(argv)


class TokenData:
    """Concatenated uint16 shards; windows never straddle a shard boundary."""

    def __init__(self, files: list[Path], seq_len: int):
        if not files:
            raise FileNotFoundError("no token files found")
        self.seq_len = seq_len
        self.shards = [torch.from_file(str(f), shared=False, size=f.stat().st_size // 2, dtype=torch.uint16)
                       for f in files]
        self.shards = [s for s in self.shards if len(s) > seq_len]
        sizes = torch.tensor([len(s) - seq_len for s in self.shards], dtype=torch.float64)
        self.weights = sizes / sizes.sum()
        self.tokens = sum(len(s) for s in self.shards)

    def batch(self, n: int, gen: torch.Generator) -> torch.Tensor:
        which = torch.multinomial(self.weights, n, replacement=True, generator=gen)
        rows = []
        for w in which.tolist():
            shard = self.shards[w]
            start = int(torch.randint(len(shard) - self.seq_len, (1,), generator=gen))
            rows.append(shard[start:start + self.seq_len].to(torch.int64))
        return torch.stack(rows)


def lr_at(step: int, a) -> float:
    if step < a.warmup:
        return a.lr * (step + 1) / a.warmup
    floor = a.lr * a.min_lr_ratio
    if a.schedule == "cosine":
        t = (step - a.warmup) / max(1, a.max_steps - a.warmup)
        return floor + 0.5 * (a.lr - floor) * (1 + math.cos(math.pi * min(t, 1.0)))
    decay_start = int(a.max_steps * (1 - a.decay_frac))
    if step < decay_start:
        return a.lr
    t = (step - decay_start) / max(1, a.max_steps - decay_start)
    return floor + (a.lr - floor) * (1 - min(t, 1.0))  # linear cooldown


def make_optimizer(model, a, device):
    decay = [p for n, p in model.named_parameters() if p.dim() >= 2]
    no_decay = [p for n, p in model.named_parameters() if p.dim() < 2]  # RMSNorm weights
    groups = [{"params": decay, "weight_decay": a.weight_decay}, {"params": no_decay, "weight_decay": 0.0}]
    return torch.optim.AdamW(groups, lr=a.lr, betas=(0.9, a.beta2), eps=1e-8, fused=device.type == "cuda")


@torch.no_grad()
def evaluate(model, data, a, device, ctx) -> float:
    model.eval()
    gen = torch.Generator().manual_seed(0)  # same val windows every eval
    losses = []
    for _ in range(a.eval_batches):
        x = data.batch(a.micro_batch, gen).to(device)
        with ctx:
            losses.append(model(x, x)[1].item())
    model.train()
    return sum(losses) / len(losses)


def main(argv=None):
    a = parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    device = torch.device(a.device)
    torch.manual_seed(a.seed)
    if device.type == "cuda":
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True

    data_dir = Path(a.data)
    train = TokenData(sorted(data_dir.glob("*.train.bin")), a.seq_len)
    val_files = sorted(data_dir.glob("*.val.bin"))
    val = TokenData(val_files, a.seq_len) if val_files else None

    cfg = {k: getattr(a, k) for k in MODEL_KEYS}
    model = PythiaModel(max_seq_len=a.seq_len, attn_impl=a.attn_impl, **cfg).to(device)
    if a.grad_ckpt:
        from torch.utils.checkpoint import checkpoint
        for block in model.blocks:
            block.forward = (lambda f: lambda x, rope: checkpoint(f, x, rope, use_reentrant=False))(block.forward)
    opt = make_optimizer(model, a, device)
    pdtype = {"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}[a.dtype]
    ctx = (torch.autocast(device.type, dtype=pdtype) if a.dtype != "fp32"
           else torch.autocast(device.type, enabled=False))
    scaler = torch.amp.GradScaler(enabled=a.dtype == "fp16")
    fwd = torch.compile(model) if a.compile else model

    step, ckpt_path, log_path = 0, out / "ckpt.pt", out / "log.jsonl"
    if a.resume and ckpt_path.exists():
        state = torch.load(ckpt_path, map_location=device, weights_only=False)
        model.load_state_dict(state["model"])
        opt.load_state_dict(state["opt"])
        scaler.load_state_dict(state["scaler"])
        step = state["step"]
        print(f"resumed at step {step}")
    params = count_parameters(model)
    tokens_per_step = a.micro_batch * a.grad_accum * a.seq_len
    print(json.dumps({"params": params, "train_tokens": train.tokens, "tokens_per_step": tokens_per_step,
                      "device": str(device), "dtype": a.dtype}))
    (out / "args.json").write_text(json.dumps(vars(a), indent=2))

    def save():
        tmp = ckpt_path.with_suffix(".tmp")
        torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "scaler": scaler.state_dict(),
                    "step": step, "args": vars(a), "model_config": model.config}, tmp)
        os.replace(tmp, ckpt_path)  # never leave a half-written checkpoint

    fixed = train.batch(a.micro_batch, torch.Generator().manual_seed(a.seed)) if a.overfit else None
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats()
    log = log_path.open("a")
    t0 = time.time()
    while step < a.max_steps:
        lr = lr_at(step, a)
        for g in opt.param_groups:
            g["lr"] = lr
        gen = torch.Generator().manual_seed(a.seed * 1_000_003 + step)
        loss_sum = 0.0
        for _ in range(a.grad_accum):
            x = (fixed if fixed is not None else train.batch(a.micro_batch, gen)).to(device, non_blocking=True)
            with ctx:
                loss = fwd(x, x)[1] / a.grad_accum
            scaler.scale(loss).backward()
            loss_sum += loss.item()
        scaler.unscale_(opt)
        gnorm = torch.nn.utils.clip_grad_norm_(model.parameters(), a.grad_clip).item()
        scaler.step(opt)
        scaler.update()
        opt.zero_grad(set_to_none=True)
        step += 1
        if not math.isfinite(loss_sum):
            raise RuntimeError(f"non-finite loss at step {step}")

        if step % a.log_every == 0 or step == a.max_steps:
            dt = time.time() - t0
            rec = {"step": step, "loss": round(loss_sum, 4), "lr": lr, "grad_norm": round(gnorm, 3),
                   "tok_s": round(tokens_per_step * a.log_every / dt)}
            if device.type == "cuda":
                rec["mem_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 2)
            print(json.dumps(rec), flush=True)
            log.write(json.dumps(rec) + "\n")
            log.flush()
            t0 = time.time()
        if val is not None and (step % a.eval_every == 0 or step == a.max_steps):
            rec = {"step": step, "val_loss": round(evaluate(fwd, val, a, device, ctx), 4)}
            print(json.dumps(rec), flush=True)
            log.write(json.dumps(rec) + "\n")
            t0 = time.time()
        if a.ckpt_every and (step % a.ckpt_every == 0 or step == a.max_steps):
            save()
    log.close()


if __name__ == "__main__":
    main()

import json
import random
from array import array

import train

TINY = ["--hidden-size", "64", "--num-layers", "2", "--n-q-heads", "4", "--n-kv-heads", "2",
        "--ffn-size", "128", "--seq-len", "32", "--micro-batch", "4", "--device", "cpu",
        "--dtype", "fp32", "--warmup", "2", "--log-every", "1", "--eval-every", "1000", "--lr", "3e-3"]


def _data(tmp_path):
    rng = random.Random(0)
    for split, n in (("train", 20_000), ("val", 2_000)):
        (tmp_path / f"a.{split}.bin").write_bytes(array("H", (rng.randrange(32_000) for _ in range(n))).tobytes())
    return str(tmp_path)


def _losses(out):
    return [r["loss"] for r in map(json.loads, (out / "log.jsonl").read_text().splitlines()) if "loss" in r]


def test_overfit_one_batch(tmp_path):
    out = tmp_path / "o"
    train.main(TINY + ["--data", _data(tmp_path), "--out", str(out), "--max-steps", "60", "--overfit"])
    losses = _losses(out)
    assert losses[0] > 9.5 and losses[-1] < 2.0


def test_resume_matches_uninterrupted(tmp_path):
    data = _data(tmp_path)
    full, part = tmp_path / "full", tmp_path / "part"
    train.main(TINY + ["--data", data, "--out", str(full), "--max-steps", "6"])
    train.main(TINY + ["--data", data, "--out", str(part), "--max-steps", "3"])
    train.main(TINY + ["--data", data, "--out", str(part), "--max-steps", "6", "--resume"])
    assert _losses(full) == _losses(part)


def test_wsd_schedule():
    a = train.parse_args(["--data", "x", "--out", "y", "--max-steps", "100", "--warmup", "10", "--lr", "1.0"])
    assert train.lr_at(0, a) == 0.1 and train.lr_at(50, a) == 1.0
    assert abs(train.lr_at(100, a) - 0.1) < 1e-9 and train.lr_at(90, a) < 1.0


def test_byte_lengths_count_exact_bytes():
    from tokenizers import Tokenizer
    path = "tokenizer/pythia-bpe-32k-v1/tokenizer.json"
    table = train.byte_lengths(path)
    text = "def f(x):\n    return x * 2  # caf\u00e9 \u2603\n"
    ids = Tokenizer.from_file(path).encode(text + "<|endoftext|>", add_special_tokens=False).ids
    assert table[ids].sum().item() == len(text.encode("utf-8"))  # EOS counts 0 bytes


def test_val_bpb_logged(tmp_path):
    import torch
    out = tmp_path / "o"
    train.main(TINY + ["--data", _data(tmp_path), "--out", str(out), "--max-steps", "3",
                       "--tokenizer", "tokenizer/pythia-bpe-32k-v1/tokenizer.json"])
    rows = [r for r in map(json.loads, (out / "log.jsonl").read_text().splitlines()) if "val_bpb" in r]
    assert rows and 0 < rows[-1]["val_bpb"] < 100 and torch.isfinite(torch.tensor(rows[-1]["val_bpb"]))

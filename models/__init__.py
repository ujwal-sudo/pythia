"""Pythia-160M: decoder-only transformer.

20 layers, d_model 768, 12 Q heads / 4 KV heads (GQA), head_dim 64, SwiGLU FFN 2304,
pre-norm RMSNorm, RoPE (theta 1e6), tied embeddings. Attention backend falls back
flash -> sdpa -> eager.

Parameter counts (fp32, default config):
    total          162,233,088   (tied embedding counted once)
    non-embedding  137,657,088   (total - 32,000 x 768)
Always report both; see `count_parameters`.
"""

import math

import torch
import torch.nn as nn
import torch.nn.functional as F

try:  # optional; only used on CUDA with fp16/bf16
    from flash_attn import flash_attn_func
except ImportError:
    flash_attn_func = None

ATTN_IMPLS = ("auto", "flash", "sdpa", "eager")


class RMSNorm(nn.Module):
    """Root Mean Square Layer Normalization (statistics in fp32)."""

    def __init__(self, dim: int, eps: float = 1e-6):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x):
        xf = x.float()  # out-of-place: for fp32 input this is `x` itself, so never mutate it
        normed = xf * torch.rsqrt(xf.pow(2).mean(-1, keepdim=True) + self.eps)
        return normed.type_as(x) * self.weight


def rotate_half(x):
    """Half-split rotation: (x1, x2) -> (-x2, x1). Matches RoPE's cat(freqs, freqs) layout."""
    half = x.shape[-1] // 2
    return torch.cat((-x[..., half:], x[..., :half]), dim=-1)


def apply_rope(x, cos, sin):
    """x: (batch, heads, seq, head_dim); cos/sin: (seq, head_dim)."""
    xf = x.float()
    return (xf * cos + rotate_half(xf) * sin).type_as(x)


class RoPE(nn.Module):
    """Rotary position embedding tables for one head_dim, shared by every layer.

    shortcut: cos/sin are buffers, so model.to(bfloat16) would round them; train with
    fp32 weights + autocast (the plan) or revisit before pure-bf16 weights.
    """

    def __init__(self, head_dim: int, max_seq_len: int, theta: float = 1_000_000.0):
        super().__init__()
        assert head_dim % 2 == 0, "head_dim must be even for RoPE"
        inv_freq = 1.0 / (theta ** (torch.arange(0, head_dim, 2).float() / head_dim))
        freqs = torch.outer(torch.arange(max_seq_len).float(), inv_freq)
        emb = torch.cat((freqs, freqs), dim=-1)
        self.register_buffer("cos", emb.cos(), persistent=False)
        self.register_buffer("sin", emb.sin(), persistent=False)
        self.max_seq_len = max_seq_len

    def forward(self, x):
        seq = x.shape[-2]
        if seq > self.max_seq_len:
            raise ValueError(f"sequence length {seq} exceeds max_seq_len {self.max_seq_len}")
        return apply_rope(x, self.cos[:seq], self.sin[:seq])


class GQAAttention(nn.Module):
    """Causal grouped-query self-attention with RoPE on Q and K."""

    def __init__(self, hidden_size: int, n_q_heads: int, n_kv_heads: int, impl: str = "auto"):
        super().__init__()
        assert hidden_size % n_q_heads == 0, f"hidden_size {hidden_size} not divisible by n_q_heads {n_q_heads}"
        assert n_q_heads % n_kv_heads == 0, f"n_q_heads {n_q_heads} not divisible by n_kv_heads {n_kv_heads}"
        assert impl in ATTN_IMPLS, f"impl must be one of {ATTN_IMPLS}"
        self.n_q_heads = n_q_heads
        self.n_kv_heads = n_kv_heads
        self.head_dim = hidden_size // n_q_heads
        self.n_rep = n_q_heads // n_kv_heads
        self.impl = impl

        self.q_proj = nn.Linear(hidden_size, n_q_heads * self.head_dim, bias=False)
        self.k_proj = nn.Linear(hidden_size, n_kv_heads * self.head_dim, bias=False)
        self.v_proj = nn.Linear(hidden_size, n_kv_heads * self.head_dim, bias=False)
        self.o_proj = nn.Linear(n_q_heads * self.head_dim, hidden_size, bias=False)

    def _repeat_kv(self, x):
        """(b, n_kv, s, d) -> (b, n_q, s, d); query head i uses kv head i // n_rep."""
        if self.n_rep == 1:
            return x
        b, n_kv, s, d = x.shape
        return x[:, :, None].expand(b, n_kv, self.n_rep, s, d).reshape(b, n_kv * self.n_rep, s, d)

    def _resolve_impl(self, x):
        if self.impl == "flash" and flash_attn_func is None:
            raise RuntimeError("attn impl 'flash' requested but flash_attn is not installed")
        if self.impl != "auto":
            return self.impl
        if flash_attn_func is not None and x.is_cuda and x.dtype in (torch.float16, torch.bfloat16):
            return "flash"
        return "sdpa"

    def forward(self, x, rope):
        b, s, _ = x.shape
        q = self.q_proj(x).view(b, s, self.n_q_heads, self.head_dim).transpose(1, 2)
        k = self.k_proj(x).view(b, s, self.n_kv_heads, self.head_dim).transpose(1, 2)
        v = self.v_proj(x).view(b, s, self.n_kv_heads, self.head_dim).transpose(1, 2)
        q, k = rope(q), rope(k)

        impl = self._resolve_impl(x)
        if impl == "flash":  # untested until a CUDA + flash_attn machine is available
            out = flash_attn_func(q.transpose(1, 2), k.transpose(1, 2), v.transpose(1, 2), causal=True)
            out = out.reshape(b, s, -1)
        else:
            k, v = self._repeat_kv(k), self._repeat_kv(v)
            if impl == "sdpa":
                out = F.scaled_dot_product_attention(q, k, v, is_causal=True)
            else:  # eager reference
                scores = (q @ k.transpose(-2, -1)) / math.sqrt(self.head_dim)
                mask = torch.ones(s, s, dtype=torch.bool, device=x.device).triu(1)
                scores = scores.float().masked_fill(mask, float("-inf"))
                out = torch.softmax(scores, dim=-1).type_as(v) @ v
            out = out.transpose(1, 2).reshape(b, s, -1)
        return self.o_proj(out)


class SwiGLU(nn.Module):
    """down(silu(gate(x)) * up(x))."""

    def __init__(self, hidden_size: int, ffn_size: int):
        super().__init__()
        self.gate_proj = nn.Linear(hidden_size, ffn_size, bias=False)
        self.up_proj = nn.Linear(hidden_size, ffn_size, bias=False)
        self.down_proj = nn.Linear(ffn_size, hidden_size, bias=False)

    def forward(self, x):
        return self.down_proj(F.silu(self.gate_proj(x)) * self.up_proj(x))


class TransformerBlock(nn.Module):
    """Pre-norm block: x + attn(norm(x)), then x + ffn(norm(x))."""

    def __init__(self, hidden_size: int, n_q_heads: int, n_kv_heads: int, ffn_size: int, attn_impl: str = "auto"):
        super().__init__()
        self.norm1 = RMSNorm(hidden_size)
        self.attn = GQAAttention(hidden_size, n_q_heads, n_kv_heads, attn_impl)
        self.norm2 = RMSNorm(hidden_size)
        self.ffn = SwiGLU(hidden_size, ffn_size)

    def forward(self, x, rope):
        x = x + self.attn(self.norm1(x), rope)
        return x + self.ffn(self.norm2(x))


class PythiaModel(nn.Module):
    """Decoder-only LM with tied input/output embeddings."""

    def __init__(self, vocab_size: int = 32_000, hidden_size: int = 768, num_layers: int = 20,
                 n_q_heads: int = 12, n_kv_heads: int = 4, ffn_size: int = 2304,
                 max_seq_len: int = 2048, rope_theta: float = 1_000_000.0, attn_impl: str = "auto"):
        super().__init__()
        self.config = dict(
            vocab_size=vocab_size, hidden_size=hidden_size, num_layers=num_layers,
            n_q_heads=n_q_heads, n_kv_heads=n_kv_heads, ffn_size=ffn_size,
            head_dim=hidden_size // n_q_heads, max_seq_len=max_seq_len,
            rope_theta=rope_theta, attn_impl=attn_impl,
        )
        self.embed = nn.Embedding(vocab_size, hidden_size)
        self.rope = RoPE(hidden_size // n_q_heads, max_seq_len, rope_theta)
        self.blocks = nn.ModuleList(
            TransformerBlock(hidden_size, n_q_heads, n_kv_heads, ffn_size, attn_impl) for _ in range(num_layers)
        )
        self.norm = RMSNorm(hidden_size)
        self.lm_head = nn.Linear(hidden_size, vocab_size, bias=False)
        self.lm_head.weight = self.embed.weight  # tie

        self.apply(self._init_weights)
        # GPT-2 style: scale residual-branch output projections by 1/sqrt(2 * layers)
        for name, p in self.named_parameters():
            if name.endswith(("o_proj.weight", "down_proj.weight")):
                nn.init.normal_(p, mean=0.0, std=0.02 / math.sqrt(2 * num_layers))

    @staticmethod
    def _init_weights(module):
        if isinstance(module, (nn.Linear, nn.Embedding)):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def set_attn_impl(self, impl: str):
        assert impl in ATTN_IMPLS
        for block in self.blocks:
            block.attn.impl = impl

    def forward(self, idx, targets=None):
        """idx: (batch, seq) token ids. Returns (logits, loss).

        If `targets` is given it must be the SAME tokens as `idx` (not pre-shifted):
        the loss shifts internally (logits[:, :-1] vs targets[:, 1:]).
        """
        x = self.embed(idx)
        for block in self.blocks:
            x = block(x, self.rope)
        logits = self.lm_head(self.norm(x))

        loss = None
        if targets is not None:
            loss = F.cross_entropy(
                logits[:, :-1].reshape(-1, logits.size(-1)),
                targets[:, 1:].reshape(-1),
            )
        return logits, loss


def count_parameters(model) -> dict:
    """Parameter counts. `parameters()` already counts the tied embedding once.

    Returns total, embedding (vocab x hidden) and non_embedding (= total - embedding).
    Report both total and non_embedding; never collapse them into one number.
    """
    total = sum(p.numel() for p in model.parameters())
    embedding = model.embed.weight.numel()
    return {"total": total, "embedding": embedding, "non_embedding": total - embedding}

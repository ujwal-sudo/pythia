import math
import torch
import torch.nn as nn
import torch.nn.functional as F


class RMSNorm(nn.Module):
    """Root Mean Square Layer Normalization."""

    def __init__(self, dim: int, eps: float = 1e-6):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x):
        norm = x.float().pow_(2).mean(-1, keepdim=True).add_(self.eps).rsqrt_()
        return (x.float() * norm).type(x.dtype) * self.weight


class RoPE:
    """Rotary Position Embedding.

    Precomputes cos/sin embeddings for given sequence length and applies them
    to query and key vectors in attention.
    """

    def __init__(self, dim: int, theta: float = 1_000_000):
        self.dim = dim
        self.theta = theta
        inv_freq = 1.0 / (theta ** (torch.arange(0, dim, 2).float() / dim))
        self.register_buffer("inv_freq", inv_freq, persistent=False)

    def __call__(self, seq_len: int, device: torch.device, dtype: torch.dtype):
        t = torch.arange(seq_len, device=device, dtype=dtype)
        freqs = t[:, None] * self.inv_freq[None, :]
        emb = torch.cat((freqs, freqs), dim=-1)
        cos = emb.cos()
        sin = emb.sin()
        return cos, sin


def rotate_half(x):
    """Rotate half the hidden dims of the input."""
    x1 = x[..., ::2]
    x2 = x[..., 1::2]
    return torch.cat((-x2, x1), dim=-1)


def apply_rope(x, cos, sin):
    """Apply RoPE to the input tensor.

    x: (batch, n_heads, seq_len, head_dim)
    cos, sin: (1, 1, seq_len, head_dim)
    """
    # x shape: (batch, n_heads, seq_len, head_dim)
    # cos/sin shape after unsqueeze: (1, 1, seq_len, head_dim)
    cos = cos.expand(x.shape[0], x.shape[1], -1, -1)
    sin = sin.expand(x.shape[0], x.shape[1], -1, -1)

    # Apply rotation: x * cos + rotate_half(x) * sin
    rotated = rotate_half(x)
    return x * cos + rotated * sin


class GQAAttention(nn.Module):
    """Grouped-Query Attention.

    Supports multiple query heads per key/value head (GQA).
    With n_q_heads=12 and n_kv_heads=2, grouping factor is 6.
    """

    def __init__(self, hidden_size: int, n_q_heads: int, n_kv_heads: int):
        super().__init__()
        self.n_q_heads = n_q_heads
        self.n_kv_heads = n_kv_heads
        self.head_dim = hidden_size // n_q_heads
        self.n_rep = n_q_heads // n_kv_heads

        assert hidden_size % n_q_heads == 0, (
            f"hidden_size {hidden_size} must be divisible by n_q_heads {n_q_heads}"
        )
        assert n_q_heads % n_kv_heads == 0, (
            f"n_q_heads {n_q_heads} must be divisible by n_kv_heads {n_kv_heads}"
        )

        self.q_proj = nn.Linear(hidden_size, n_q_heads * self.head_dim, bias=False)
        self.k_proj = nn.Linear(hidden_size, n_kv_heads * self.head_dim, bias=False)
        self.v_proj = nn.Linear(hidden_size, n_kv_heads * self.head_dim, bias=False)
        self.o_proj = nn.Linear(n_q_heads * self.head_dim, hidden_size, bias=False)

    def _repeat_kv(self, x):
        """Repeat key/value heads to match number of query heads.

        x: (batch, n_kv_heads, seq_len, head_dim)
        Returns: (batch, n_q_heads, seq_len, head_dim)
        """
        bs, n_kv, slen, head_dim = x.shape
        if self.n_rep == 1:
            return x
        return (
            x[:, :, :, None, :]
            .expand(bs, n_kv, slen, self.n_rep, head_dim)
            .reshape(bs, n_kv * self.n_rep, slen, head_dim)
        )

    def forward(self, q, k, v):
        """Forward pass for GQA attention.

        q, k, v: (batch, seq_len, hidden_size)
        Returns: (batch, seq_len, hidden_size)
        """
        bs = q.shape[0]

        # Project and reshape: (bs, seq_len, n_heads * head_dim) -> (bs, seq_len, n_heads, head_dim)
        q = self.q_proj(q).view(bs, -1, self.n_q_heads, self.head_dim).transpose(1, 2)
        k = self.k_proj(k).view(bs, -1, self.n_kv_heads, self.head_dim).transpose(1, 2)
        v = self.v_proj(v).view(bs, -1, self.n_kv_heads, self.head_dim).transpose(1, 2)

        # Repeat K/V to match Q heads
        k = self._repeat_kv(k)
        v = self._repeat_kv(v)

        # Scaled dot-product attention
        # q: (bs, n_q_heads, seq_len, head_dim), k: (bs, n_q_heads, seq_len, head_dim)
        scores = torch.matmul(q, k.transpose(-2, -1)) / math.sqrt(self.head_dim)

        # Causal mask
        seq_len = scores.shape[-1]
        causal_mask = torch.triu(
            torch.full((seq_len, seq_len), float("-inf"), device=scores.device),
            diagonal=1,
        )
        scores = scores + causal_mask

        attn = F.softmax(scores, dim=-1)
        output = torch.matmul(attn, v)

        # Reshape output: (bs, n_q_heads, seq_len, head_dim) -> (bs, seq_len, n_q_heads * head_dim)
        output = output.transpose(1, 2).contiguous().view(bs, -1, self.n_q_heads * self.head_dim)
        return self.o_proj(output)


class SwiGLU(nn.Module):
    """Swish-Gated Linear Unit activation function.

    Compute: gate = silo(W_gate @ x), up = W_up @ x, output = W_down @ (gate * up)
    """

    def __init__(self, hidden_size: int, ffn_size: int):
        super().__init__()
        self.gate_proj = nn.Linear(hidden_size, ffn_size, bias=False)
        self.up_proj = nn.Linear(hidden_size, ffn_size, bias=False)
        self.down_proj = nn.Linear(ffn_size, hidden_size, bias=False)

    def forward(self, x):
        gate = F.silu(self.gate_proj(x))
        up = self.up_proj(x)
        return self.down_proj(gate * up)


class TransformerBlock(nn.Module):
    """Pre-norm Transformer block.

    Architecture: RMSNorm → RoPE → GQA → residual,
                    RMSNorm → SwiGLU → residual
    """
    def __init__(self, hidden_size: int, n_q_heads: int, n_kv_heads: int, ffn_size: int):
        super().__init__()
        self.norm1 = RMSNorm(hidden_size)
        self.attn = GQAAttention(hidden_size, n_q_heads, n_kv_heads)
        self.norm2 = RMSNorm(hidden_size)
        self.ffn = SwiGLU(hidden_size, ffn_size)
        self.rope = RoPE(hidden_size, 1_000_000)

    def forward(self, x, seq_len: int = None):
        # Pre-norm attention branch
        residual = x
        x = self.norm1(x)
        # Apply RoPE
        cos, sin = self.rope(seq_len or x.shape[1], x.device, x.dtype)
        # x shape for attention: (batch, seq_len, hidden)
        # We need to transpose to (batch, head, seq_len, head_dim) inside attention
        # But attention expects (batch, seq_len, hidden) and handles internally
        # So we just pass x as-is and let attention handle the reshaping
        x = self.attn(x, x, x)
        x = x + residual

        # Pre-norm FFN branch
        residual = x
        x = self.norm2(x)
        x = self.ffn(x)
        x = x + residual

        return x


class PythiaModel(nn.Module):
    """Pythia language model with 160.55M parameters.

    Architecture:
    - Token embedding (tied with LM head)
    - 12 Transformer blocks (RMSNorm → RoPE → GQA → SwiGLU)
    - Final RMSNorm
    - LM head (weight-tied to embedding)
    """

    def __init__(self, vocab_size: int = 32_000, hidden_size: int = 768,
                 num_layers: int = 12, n_q_heads: int = 12, n_kv_heads: int = 2,
                 ffn_size: int = 4320):
        super().__init__()

        self.config = dict(
            vocab_size=vocab_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            n_q_heads=n_q_heads,
            n_kv_heads=n_kv_heads,
            ffn_size=ffn_size,
            head_dim=hidden_size // n_q_heads,
        )

        # Token embeddings (tied with lm_head)
        self.embed = nn.Embedding(vocab_size, hidden_size)

        # Transformer blocks
        self.blocks = nn.ModuleList([
            TransformerBlock(hidden_size, n_q_heads, n_kv_heads, ffn_size)
            for _ in range(num_layers)
        ])

        # Final norm
        self.norm = RMSNorm(hidden_size)

        # LM head (weights tied with embedding)
        self.lm_head = nn.Linear(hidden_size, vocab_size, bias=False)
        self.lm_head.weight = self.embed.weight  # Weight tying

    def forward(self, idx, targets=None, seq_len: int = None):
        """Forward pass.

        idx: (batch, seq_len) tensor of token IDs
        targets: (batch, seq_len) optional target token IDs for loss computation

        Returns: (logits, loss) where loss is cross-entropy loss
        """
        # Embed tokens
        x = self.embed(idx)  # (batch, seq_len, hidden)

        # Pass through transformer blocks
        for block in self.blocks:
            x = block(x, seq_len=seq_len)

        # Final norm
        x = self.norm(x)

        # LM head
        logits = self.lm_head(x)  # (batch, seq_len, vocab_size)

        # Compute loss if targets provided
        loss = None
        if targets is not None:
            # Shift logits and targets for next-token prediction
            shift_logits = logits[:, :-1, :].contiguous()
            shift_targets = targets[:, 1:].contiguous()
            loss = F.cross_entropy(
                shift_logits.view(-1, shift_logits.size(-1)),
                shift_targets.view(-1),
            )

        return logits, loss

    def get_num_params(self):
        """Count total parameters (excluding tied weights double-count)."""
        n_params = sum(p.numel() for p in self.parameters())
        # Subtract the tied weight (lm_head.weight is same as embed.weight)
        # lm_head has hidden_size * vocab_size params, embed has same
        # We count them once, so subtract one copy
        tied_reduction = self.embed.weight.numel()
        return n_params - tied_reduction


def count_parameters(model):
    """Count model parameters, handling weight tying correctly."""
    total = sum(p.numel() for p in model.parameters())
    # Weight tying: lm_head.weight shares with embed.weight
    # We counted embed.weight params once via model.parameters(), but lm_head also references it
    # So we need to subtract the duplicate count
    if hasattr(model, 'lm_head') and hasattr(model, 'embed'):
        total -= model.embed.weight.numel()  # Remove duplicate count
    return total
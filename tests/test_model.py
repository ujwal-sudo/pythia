import math
import unittest

import torch

from models import (
    PythiaModel, GQAAttention, RMSNorm, RoPE, apply_rope, count_parameters, flash_attn_func,
)

TINY = dict(vocab_size=101, hidden_size=96, num_layers=2, n_q_heads=6, n_kv_heads=2,
            ffn_size=160, max_seq_len=64)


def tiny(**kw):
    torch.manual_seed(0)
    return PythiaModel(**{**TINY, **kw}).eval()


class Shapes(unittest.TestCase):
    def test_logits_and_loss_shapes(self):
        m = tiny()
        idx = torch.randint(0, 101, (3, 17))
        logits, loss = m(idx, idx)
        self.assertEqual(logits.shape, (3, 17, 101))
        self.assertEqual(loss.shape, ())

    def test_init_loss_near_log_vocab(self):
        m = PythiaModel(**{**TINY, "vocab_size": 32000}).eval()
        idx = torch.randint(0, 32000, (4, 32))
        _, loss = m(idx, idx)
        self.assertTrue(10.0 < loss.item() < 11.0, loss.item())


class ParamCounts(unittest.TestCase):
    def test_full_config_counts(self):
        with torch.device("meta"):
            m = PythiaModel()
        c = count_parameters(m)
        self.assertEqual(c["total"], 160_549_632)
        self.assertEqual(c["embedding"], 32_000 * 768)
        self.assertEqual(c["non_embedding"], 135_973_632)
        self.assertEqual(c["total"] - c["embedding"], c["non_embedding"])

    def test_tied_weights_are_same_tensor(self):
        m = tiny()
        self.assertIs(m.lm_head.weight, m.embed.weight)
        self.assertEqual(m.lm_head.weight.data_ptr(), m.embed.weight.data_ptr())
        self.assertEqual(len([n for n, _ in m.named_parameters() if "lm_head" in n]), 0)  # deduplicated


class Causality(unittest.TestCase):
    def test_future_token_cannot_change_past_logits(self):
        m = tiny()
        a = torch.randint(0, 101, (1, 20))
        b = a.clone()
        b[0, 12] = (b[0, 12] + 1) % 101
        with torch.no_grad():
            la, lb = m(a)[0], m(b)[0]
        self.assertTrue(torch.allclose(la[:, :12], lb[:, :12], atol=1e-5))
        self.assertFalse(torch.allclose(la[:, 12:], lb[:, 12:], atol=1e-5))


class Rope(unittest.TestCase):
    def test_relative_position_property(self):
        d = 16
        rope = RoPE(d, 64)
        q, k = torch.randn(d), torch.randn(d)
        qs = q.expand(1, 1, 64, d).clone()
        ks = k.expand(1, 1, 64, d).clone()
        rq, rk = rope(qs)[0, 0], rope(ks)[0, 0]
        dot = lambda m, n: (rq[m] @ rk[n]).item()  # noqa: E731
        self.assertAlmostEqual(dot(3, 1), dot(40, 38), places=4)
        self.assertAlmostEqual(dot(9, 9), dot(0, 0), places=4)
        self.assertNotAlmostEqual(dot(3, 1), dot(5, 1), places=3)

    def test_position_zero_identity_and_norm_preserved(self):
        rope = RoPE(16, 32)
        x = torch.randn(2, 3, 32, 16)
        r = rope(x)
        self.assertTrue(torch.allclose(r[:, :, 0], x[:, :, 0], atol=1e-6))
        self.assertTrue(torch.allclose(r.norm(dim=-1), x.norm(dim=-1), atol=1e-5))

    def test_rope_is_applied_in_the_model(self):
        # With ONE layer and no positional info, the last position only sees embeddings, so it is
        # invariant to the order of the prefix; (with 2+ layers causal masking alone breaks that).
        m = tiny(num_layers=1)
        a = torch.tensor([[5, 6, 7, 8]])
        b = torch.tensor([[6, 5, 7, 8]])
        with torch.no_grad():
            la, lb = m(a)[0][:, -1], m(b)[0][:, -1]
        self.assertFalse(torch.allclose(la, lb, atol=1e-4))

    def test_buffers_not_persisted_and_length_checked(self):
        m = tiny()
        self.assertFalse([k for k in m.state_dict() if k.endswith(("cos", "sin"))])
        with self.assertRaises(ValueError):
            m(torch.zeros(1, 65, dtype=torch.long))


class GQA(unittest.TestCase):
    def test_head_mapping(self):
        attn = GQAAttention(96, 6, 2)  # n_rep = 3
        kv = torch.arange(2.0).view(1, 2, 1, 1).expand(1, 2, 4, 16).contiguous()
        rep = attn._repeat_kv(kv)
        self.assertEqual(rep.shape, (1, 6, 4, 16))
        self.assertEqual(rep[0, :, 0, 0].tolist(), [0, 0, 0, 1, 1, 1])

    def test_matches_native_gqa_sdpa(self):
        attn = GQAAttention(96, 6, 2)
        q = torch.randn(2, 6, 10, 16)
        k, v = torch.randn(2, 2, 10, 16), torch.randn(2, 2, 10, 16)
        ref = torch.nn.functional.scaled_dot_product_attention(q, k, v, is_causal=True, enable_gqa=True)
        got = torch.nn.functional.scaled_dot_product_attention(
            q, attn._repeat_kv(k), attn._repeat_kv(v), is_causal=True)
        self.assertTrue(torch.allclose(ref, got, atol=1e-5))


class Backends(unittest.TestCase):
    def test_eager_and_sdpa_match(self):
        m = tiny()
        idx = torch.randint(0, 101, (2, 24))
        outs = {}
        for impl in ("eager", "sdpa", "auto"):
            m.set_attn_impl(impl)
            with torch.no_grad():
                outs[impl] = m(idx)[0]
        self.assertTrue(torch.allclose(outs["eager"], outs["sdpa"], atol=1e-4))
        self.assertTrue(torch.allclose(outs["auto"], outs["sdpa"], atol=1e-6))  # CPU: auto -> sdpa

    def test_flash_request_without_package_fails_loudly(self):
        if flash_attn_func is not None:
            self.skipTest("flash_attn installed")
        m = tiny(attn_impl="flash")
        with self.assertRaises(RuntimeError):
            m(torch.zeros(1, 4, dtype=torch.long))

    @unittest.skipUnless(flash_attn_func is not None and torch.cuda.is_available(), "needs CUDA + flash_attn")
    def test_flash_matches_sdpa(self):
        m = tiny().cuda().bfloat16()
        idx = torch.randint(0, 101, (2, 24), device="cuda")
        m.set_attn_impl("sdpa")
        a = m(idx)[0]
        m.set_attn_impl("flash")
        b = m(idx)[0]
        self.assertTrue(torch.allclose(a.float(), b.float(), atol=5e-2))


class Norm(unittest.TestCase):
    def test_rmsnorm_does_not_mutate_input(self):
        x = torch.randn(4, 8)
        before = x.clone()
        out = RMSNorm(8)(x)
        self.assertTrue(torch.equal(x, before))
        self.assertTrue(torch.allclose(out.pow(2).mean(-1), torch.ones(4), atol=1e-3))


class Training(unittest.TestCase):
    def test_gradients_reach_every_parameter(self):
        m = tiny().train()
        idx = torch.randint(0, 101, (2, 16))
        _, loss = m(idx, idx)
        loss.backward()
        missing = [n for n, p in m.named_parameters() if p.grad is None or not torch.isfinite(p.grad).all()]
        self.assertEqual(missing, [])

    def test_can_overfit_one_batch(self):
        torch.manual_seed(1)
        m = PythiaModel(**{**TINY, "num_layers": 2}).train()
        idx = torch.randint(0, 101, (4, 32))
        opt = torch.optim.AdamW(m.parameters(), lr=3e-3)
        first = None
        for _ in range(150):
            _, loss = m(idx, idx)
            first = first if first is not None else loss.item()
            opt.zero_grad()
            loss.backward()
            opt.step()
        self.assertLess(loss.item(), 0.3 * first)


if __name__ == "__main__":
    unittest.main()

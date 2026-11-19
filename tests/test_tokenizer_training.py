import random
import unittest
import tempfile
from pathlib import Path

from tokenizers import Tokenizer
from tokenizers.pre_tokenizers import ByteLevel

from scripts.corpus import tokenizer as tk

NASTY = [
    "def f(x):\n    return x  # ok\n",
    "\tindent\r\nwindows\x00nul\x7f",
    "héllo wörld ünïcode 日本語 🐍 ¡ ÿ ÿ",
    "<|endoftext|> literal <|fim_middle|> <|reserved_005|>",
    "    " * 40 + "deep",
    "",
]


class TokenizerTraining(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        sample = root / "sample.txt"
        # Deliberately ASCII-only: rare bytes must still be in the vocab.
        rng = random.Random(0)
        words = ["".join(rng.choices("abcdefghijklmnopqrstuvwxyz_", k=rng.randint(2, 9))) for _ in range(4000)]
        sample.write_text("\n".join(
            f"def {rng.choice(words)}({rng.choice(words)}):\n    return {rng.choice(words)}"
            for _ in range(20000)))
        cls.info = tk.train(vocab_size=1024, sample_path=sample, out_dir=root / "tok")
        cls.tok = Tokenizer.from_file(cls.info["path"])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_vocab_size_exact(self):
        self.assertEqual(self.tok.get_vocab_size(), 1024)

    def test_special_ids_fixed(self):
        ids = {t: self.tok.token_to_id(t) for t in tk.NAMED_SPECIALS}
        self.assertEqual(
            ids,
            {"<|pad|>": 0, "<|bos|>": 1, "<|endoftext|>": 2,
             "<|fim_prefix|>": 3, "<|fim_middle|>": 4, "<|fim_suffix|>": 5},
        )

    def test_128_special_slots_then_bytes(self):
        self.assertEqual(len(tk.SPECIAL_TOKENS), tk.N_SPECIAL_SLOTS)
        self.assertEqual(self.tok.token_to_id("<|reserved_121|>"), 127)
        self.assertIsNone(self.tok.token_to_id("<|reserved_122|>"))

    def test_all_256_bytes_present(self):
        vocab = self.tok.get_vocab()
        self.assertEqual([c for c in ByteLevel.alphabet() if c not in vocab], [])

    def test_roundtrip_byte_exact(self):
        for text in NASTY:
            ids = self.tok.encode(text).ids
            self.assertEqual(self.tok.decode(ids, skip_special_tokens=False), text, repr(text))

    def test_report_has_hash(self):
        self.assertEqual(len(self.info["sha256"]), 64)


class PreTokenizer(unittest.TestCase):
    def split(self, text):
        return [w.replace("Ġ", " ").replace("Ċ", "\n") for w, _ in tk.pre_tokenizer().pre_tokenize_str(text)]

    def test_digits_split_singly_keeping_space(self):
        self.assertEqual(self.split("x = 2024"), ["x", " =", " 2", "0", "2", "4"])

    def test_underscores_join_following_letters(self):
        self.assertEqual(self.split("get_user(__init__)"), ["get", "_user", "(", "__init", "__", ")"])
        self.assertEqual(self.split("self._cache"), ["self", ".", "_cache"])

    def test_newline_and_indent_kept_together_for_merges(self):
        self.assertEqual(self.split("if x:\n    return"), ["if", " x", ":", "\n   ", " return"])

    def test_frozen_v2_uses_this_regex(self):
        import json
        root = Path(__file__).resolve().parents[1] / "tokenizer" / "pythia-bpe-32k-v2"
        pre = json.loads((root / "tokenizer.json").read_text())["pre_tokenizer"]["pretokenizers"]
        self.assertEqual(pre[0]["pattern"]["Regex"], tk.PRETOKENIZER_REGEX)
        self.assertFalse(pre[1]["use_regex"])


if __name__ == "__main__":
    unittest.main()

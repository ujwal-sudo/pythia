import unittest

import struct
from tokenizers import Tokenizer

from scripts.corpus import tokenize_corpus as tc


def rec(text, url, rid="r"):
    return {"text": text, "meta": {"source_url": url, "record_id": rid}}


class TokenizeCorpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tok = Tokenizer.from_file(str(tc.TOK_DIR / "tokenizer.json"))

    def test_tokenizer_hash_verified(self):
        self.assertEqual(len(tc._load_tokenizer()[1]), 64)

    def test_val_is_repo_level_and_deterministic(self):
        flags = {tc.is_val(rec("x", f"owner/repo{i}")) for i in range(2000)}
        self.assertEqual(flags, {True, False})
        self.assertEqual(tc.is_val(rec("a", "o/r")), tc.is_val(rec("b", "o/r")))
        frac = sum(tc.is_val(rec("x", f"o/r{i}")) for i in range(20000)) / 20000
        self.assertAlmostEqual(frac, tc.VAL_PERMILLE / 1000, delta=0.003)

    def test_eos_after_each_doc_and_roundtrip(self):
        train_urls = [u for u in (f"o/r{i}" for i in range(500)) if not tc.is_val(rec("", u))][:2]
        texts = ["def a():\n    return 1\n", "héllo 🐍\r\n\t"]
        recs = [rec(t, u, f"id{i}") for i, (t, u) in enumerate(zip(texts, train_urls))]
        train, val, excluded, docs = tc.encode_records(self.tok, recs)
        self.assertEqual((len(val), excluded, docs), (0, [], {"train": 2, "val": 0}))
        eos = self.tok.token_to_id(tc.EOS)
        self.assertEqual(train.count(eos), 2)
        self.assertEqual(train[-1], eos)
        cut = train.index(eos)
        self.assertEqual(self.tok.decode(list(train[:cut])), texts[0])

    def test_special_string_docs_excluded_not_parsed(self):
        bad = rec("x = '<|endoftext|>'", "o/r", "bad")
        good = rec("y = 1", "o/r", "good")
        train, val, excluded, docs = tc.encode_records(self.tok, [bad, good])
        self.assertEqual(excluded, ["bad"])
        eos = self.tok.token_to_id(tc.EOS)
        self.assertEqual((train + val).count(eos), 1)

    def test_uint16_bytes(self):
        blob = tc._to_bytes([0, 1, 31999])
        self.assertEqual(list(struct.unpack("<3H", blob)), [0, 1, 31999])
        with self.assertRaises(ValueError):
            tc._to_bytes([70000])


if __name__ == "__main__":
    unittest.main()

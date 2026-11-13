import os
import json
import random
from collections import Counter


class SimpleTokenizer:
    """
    A simple BPE-like tokenizer targeting 32K vocabulary.
    In practice, would use tiktoken or trained BPE, but this is a functional baseline.
    """
    def __init__(self, vocab_size: int = 32_000, special_tokens: list = None):
        self.vocab_size = vocab_size
        self.special_tokens = special_tokens or ["<pad>", "<unk>", "<bos>", "<eos>", "[MIDDLE]"]
        
        # Build vocabulary
        self._build_vocab()
        
        # Token to ID and ID to token
        self.token_to_id = {}
        self.id_to_token = {}
        self._init_special()
        
        # Add remaining tokens based on character n-grams
        self._add_regular_tokens()
    
    def _init_special(self):
        init_idx = 0
        for token in self.special_tokens:
            idx = init_idx
            self.token_to_id[token] = idx
            self.id_to_token[idx] = token
            init_idx += 1
    
    def _add_regular_tokens(self):
        # Add common English characters and character combinations
        # This creates a simple vocabulary around the target size
        freq_chars = self._get_frequent_chars()
        
        # Add individual characters first
        for i, ch in enumerate(freq_chars):
            token = ch
            if token not in self.token_to_id and len(self.token_to_id) < self.vocab_size:
                idx = len(self.token_to_id)
                self.token_to_id[token] = idx
                self.id_to_token[idx] = token
        
        # Add frequent bigrams
        bigrams = self._get_frequent_bigrams(freq_chars)
        for bg in bigrams:
            if bg not in self.token_to_id and len(self.token_to_id) < self.vocab_size:
                idx = len(self.token_to_id)
                self.token_to_id[bg] = idx
                self.id_to_token[idx] = bg
        
        # Fill rest with byte-level tokens
        while len(self.token_to_id) < self.vocab_size:
            # Use increasing byte values
            byte_val = len(self.token_to_id)
            token = f"<byte:{byte_val}>"
            self.token_to_id[token] = byte_val
            self.id_to_token[byte_val] = token
    
    def _get_frequent_chars(self):
        # English letter frequency
        return sorted("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()_+-=[]{}|;':\",./<>?`~ ", key=lambda c: -1)[:200]
    
    def _get_frequent_bigrams(self, chars):
        common = ["th", "he", "in", "er", "an", "re", "ti", "en", "on", "at", "sh", "ch", "ou", "ing", "comp", "ation"]
        return [c for c in common if len(c) > 0][:100]
    
    def encode(self, text: str, add_special: bool = False) -> list[int]:
        """Convert text to token IDs."""
        # Simple: split by spaces and map to vocab, fallback to char-level
        tokens = []
        words = text.split()
        
        for word in words:
            # Try exact match first
            if word in self.token_to_id:
                tokens.append(self.token_to_id[word])
            else:
                # Fall back to character-level
                for ch in word:
                    ch_token = ch if ch in self.token_to_id else "<unk>"
                    tokens.append(self.token_to_id.get(ch_token, self.token_to_id.get("<unk>", 1)))
        
        if add_special:
            bos_id = self.token_to_id.get("<bos>", 0)
            eos_id = self.token_to_id.get("<eos>", 2)
            tokens = [bos_id] + tokens + [eos_id]
        
        return tokens
    
    def decode(self, token_ids: list[int]) -> str:
        """Convert token IDs back to text."""
        tokens = []
        for tid in token_ids:
            if tid in self.id_to_token:
                tok = self.id_to_token[tid]
                if tok in self.special_tokens:
                    if tok == "<eos>":
                        tokens.append(" ")
                    elif tok == "<bos>":
                        pass  # skip bos
                    elif tok == "<pad>":
                        pass  # skip pad
                    else:
                        tokens.append(tok)
                else:
                    tokens.append(tok)
            else:
                tokens.append("<unk>")
        return "".join(tokens).strip()
    
    def __len__(self):
        return self.vocab_size


def train_tokenizer_from_corpus(corpus_path: str, vocab_size: int = 32_000, 
                                output_path: str = None) -> SimpleTokenizer:
    """
    Train a simple tokenizer from a corpus file.
    In practice would use sentencepiece or tiktoken training.
    """
    # Read corpus
    with open(corpus_path, 'r', encoding='utf-8') as f:
        text = f.read()
    
    # Get all words
    words = text.split()
    
    # Count character frequencies
    char_counts = Counter(text)
    frequent_chars = [ch for ch, _ in char_counts.most_common(200)]
    
    # Build tokenizer
    tokenizer = SimpleTokenizer(vocab_size=vocab_size)
    
    # Simple mapping: frequent chars get IDs, rest mapped to <unk>
    # In practice: train BPE, WordPiece, or use tiktoken
    
    return tokenizer
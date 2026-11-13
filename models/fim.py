import random
import torch
from torch.utils.data import Dataset


def apply_fim(text: str, fim_ratio: float = 0.5) -> tuple[str, str, str]:
    """
    Apply Fill-in-the-Middle masking to text.
    
    Returns: (prefix, middle, suffix)
    The model will see prefix + [MASK] + suffix and try to predict middle.
    """
    if not text or fim_ratio <= 0 or fim_ratio >= 1:
        return text, "", ""
    
    # Tokenize roughly by words
    words = text.split()
    if len(words) < 3:
        return text, "", ""
    
    # Determine how many middle words to mask
    n_middle = max(1, int(len(words) * fim_ratio))
    n_middle = min(n_middle, len(words) - 2)  # Keep at least first and last
    
    # Choose middle section
    middle_start = 1  # Always keep first word visible
    middle_end = len(words) - n_middle
    
    if middle_end <= middle_start:
        middle_end = middle_start + 1
    
    prefix_words = words[:middle_start]
    middle_words = words[middle_start:middle_end]
    suffix_words = words[middle_end:]
    
    prefix = " ".join(prefix_words)
    middle = " ".join(middle_words)
    suffix = " ".join(suffix_words)
    
    # Replace middle with mask token
    masked_text = prefix + " [MIDDLE] " + suffix
    
    return masked_text, prefix, middle


class FIMDataset(Dataset):
    def __init__(self, text_paths: list[str], tokenizer, fim_ratio: float = 0.5, 
                 max_seq_len: int = 512, vocab_size: int = 32000):
        self.tokenizer = tokenizer
        self.fim_ratio = fim_ratio
        self.max_seq_len = max_seq_len
        self.vocab_size = vocab_size
        
        self.examples = []
        for path in text_paths:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self.examples.append(line)
    
    def __len__(self):
        return len(self.examples)
    
    def __getitem__(self, idx):
        text = self.examples[idx]
        masked_text, prefix, middle = apply_fim(text, self.fim_ratio)
        
        # Tokenize
        tokens = self.tokenizer.encode(masked_text)
        
        # Truncate/pad to max_seq_len
        if len(tokens) > self.max_seq_len:
            tokens = tokens[:self.max_seq_len]
        
        # Create label: same as input for causal LM, but for FIM we need different handling
        # For FIM: input is masked_text, target is the original text positions
        # Simplified: treat as standard next-token prediction on masked text
        
        # Pad to max_seq_len
        padding_len = self.max_seq_len - len(tokens)
        tokens_ids = tokens + [0] * padding_len  # 0 is pad token
        
        # For FIM: we create labels where the middle section is the target
        # and the rest is what the model sees
        labels = tokens_ids[:]  # Start with same as input
        
        # Mark prefix+suffix positions as valid, middle as target
        # Actually for simplicity in this implementation:
        # - input: masked_text tokens
        # - target: original text tokens at middle positions
        
        return {
            'input_ids': torch.tensor(tokens_ids, dtype=torch.long),
            'labels': torch.tensor(labels[:self.max_seq_len], dtype=torch.long),
            'attention_mask': torch.ones(self.max_seq_len, dtype=torch.long),
            'prefix': prefix,
            'middle': middle,
        }
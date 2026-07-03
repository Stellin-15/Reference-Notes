# ============================================================
# L04: Tokenization — Byte-Pair Encoding (BPE) From Scratch
# ============================================================
# WHAT: How raw text becomes the integer token IDs a transformer actually
#       consumes, implemented as real BPE (the algorithm behind GPT's,
#       LLaMA's, and most modern LLM tokenizers).
# WHY: Tokenization is the FIRST place your model's assumptions about the
#      world get baked in — vocabulary size directly trades off against
#      embedding table size (a real memory/quantization concern later),
#      and tokenization artifacts (e.g. numbers being split oddly) explain
#      a huge fraction of "why does the model get this simple thing wrong."
# LEVEL: Foundation (Phase 2 of 8 — Building an LLM From Scratch)
# ============================================================

"""
CONCEPT OVERVIEW:
BPE starts from the smallest possible vocabulary (individual bytes or
characters) and iteratively merges the MOST FREQUENT adjacent pair into a
new single token, repeating until reaching a target vocabulary size. This
produces a vocabulary that represents common words/subwords as single
tokens (efficient) while still being able to represent ANY string by
falling back to individual bytes/characters (no "unknown token" problem —
this is exactly why byte-level BPE, used by GPT-2 onward, can tokenize
literally any input, including code, emoji, and other languages it never
explicitly trained a merge rule for).

The embedding table's size is `vocab_size * d_model` — this is often one
of the LARGEST parameter tensors in a small-to-mid model, and it's stored
at the SAME precision as everything else. A 50K-vocab, 4096-dim model has
a 200M-parameter embedding table alone — this becomes directly relevant
when you later decide which tensors are worth quantizing aggressively
(embeddings are usually quantized more conservatively than MLP weights,
because embedding lookup error propagates through the entire model).

PRODUCTION/RESEARCH USE CASE:
When you build the actual training pipeline in L06, the tokenizer you
build here converts your raw text corpus into the integer sequences that
become training batches — get this wrong (e.g. inconsistent whitespace
handling) and your loss curves will look fine while your model quietly
learns bad habits (extra token overhead per word, broken number handling).

COMMON MISTAKES:
- Implementing word-level tokenization instead of subword — this creates
  a huge "unknown word" problem and a much larger vocabulary than needed.
- Forgetting that BPE MERGES are learned once (during training) and then
  APPLIED deterministically at inference — the merge rules, not just the
  final vocabulary, must be saved and reused exactly.
- Not handling byte-level fallback — a character-level (not byte-level)
  BPE tokenizer will fail or need an <unk> token for text outside its
  training distribution (e.g. an emoji never seen during merge-rule
  learning); byte-level BPE never has this problem since every possible
  byte value (0-255) is a valid base token.
"""

from collections import Counter, defaultdict


# ------------------------------------------------------------------
# 1. BPE training: learn merge rules from a corpus
# ------------------------------------------------------------------
def get_word_frequencies(corpus: str) -> dict[tuple[str, ...], int]:
    """
    Splits the corpus into words, and represents each word as a tuple of
    individual characters plus an end-of-word marker. The end-of-word
    marker (`</w>`) is essential — without it, BPE can't distinguish
    "er" at the end of a word (e.g. "faster") from "er" mid-word (e.g.
    "herbal"), which produces linguistically confused merges.
    """
    words = corpus.split()
    word_freqs: dict[tuple[str, ...], int] = defaultdict(int)
    for word in words:
        chars = tuple(word) + ("</w>",)
        word_freqs[chars] += 1
    return word_freqs


def get_pair_frequencies(word_freqs: dict[tuple[str, ...], int]) -> Counter:
    """Counts how often each ADJACENT symbol pair occurs across the corpus."""
    pairs = Counter()
    for word, freq in word_freqs.items():
        for i in range(len(word) - 1):
            pairs[(word[i], word[i + 1])] += freq
    return pairs


def merge_pair(
    pair: tuple[str, str], word_freqs: dict[tuple[str, ...], int]
) -> dict[tuple[str, ...], int]:
    """Replaces every occurrence of `pair` with a single merged symbol."""
    new_word_freqs = {}
    merged_symbol = "".join(pair)
    for word, freq in word_freqs.items():
        new_word = []
        i = 0
        while i < len(word):
            # Look for the pair starting at position i
            if i < len(word) - 1 and (word[i], word[i + 1]) == pair:
                new_word.append(merged_symbol)
                i += 2
            else:
                new_word.append(word[i])
                i += 1
        new_word_freqs[tuple(new_word)] = freq
    return new_word_freqs


def train_bpe(corpus: str, num_merges: int) -> list[tuple[str, str]]:
    """
    Runs the core BPE training loop: repeatedly find the most frequent
    adjacent pair and merge it, recording the merge rules IN ORDER — the
    order matters, because at inference time merges must be applied in
    the exact same sequence they were learned.
    """
    word_freqs = get_word_frequencies(corpus)
    merges: list[tuple[str, str]] = []

    for _ in range(num_merges):
        pairs = get_pair_frequencies(word_freqs)
        if not pairs:
            break
        best_pair = max(pairs, key=pairs.get)   # most frequent adjacent pair
        word_freqs = merge_pair(best_pair, word_freqs)
        merges.append(best_pair)

    return merges


# ------------------------------------------------------------------
# 2. BPE encoding: apply learned merges to new text
# ------------------------------------------------------------------
def encode_word(word: str, merges: list[tuple[str, str]]) -> list[str]:
    """
    Applies the LEARNED merge rules, IN THE ORDER THEY WERE LEARNED, to a
    new word. This determinism is critical: the same word must always
    tokenize to the same sequence of tokens, both during training data
    prep and at inference time on user input.
    """
    symbols = list(word) + ["</w>"]
    for pair in merges:
        i = 0
        new_symbols = []
        while i < len(symbols):
            if i < len(symbols) - 1 and (symbols[i], symbols[i + 1]) == pair:
                new_symbols.append("".join(pair))
                i += 2
            else:
                new_symbols.append(symbols[i])
                i += 1
        symbols = new_symbols
    return symbols


def tokenize(text: str, merges: list[tuple[str, str]]) -> list[str]:
    return [tok for word in text.split() for tok in encode_word(word, merges)]


# ------------------------------------------------------------------
# 3. Vocabulary size vs embedding table cost — the concrete tradeoff
# ------------------------------------------------------------------
def embedding_table_params(vocab_size: int, d_model: int) -> int:
    return vocab_size * d_model


def embedding_table_bytes(vocab_size: int, d_model: int, bytes_per_param: float) -> int:
    return int(embedding_table_params(vocab_size, d_model) * bytes_per_param)


def vocab_size_tradeoff_demo():
    d_model = 4096
    for vocab_size in (8_000, 32_000, 50_000, 128_000):
        params = embedding_table_params(vocab_size, d_model)
        fp16_mb = embedding_table_bytes(vocab_size, d_model, 2) / 1e6
        int4_mb = embedding_table_bytes(vocab_size, d_model, 0.5) / 1e6
        print(f"vocab={vocab_size:>7,}  params={params:>13,}  "
              f"FP16={fp16_mb:>8.1f} MB   INT4={int4_mb:>8.1f} MB")
    # A LARGER vocabulary means FEWER tokens per sentence (good for
    # sequence length / compute), but a LARGER embedding table (bad for
    # memory) — this is a real design tradeoff every tokenizer author
    # makes, and it's the same tradeoff you'll revisit when deciding how
    # aggressively to quantize the embedding layer in Phase 3-4.


if __name__ == "__main__":
    corpus = "low lower lowest new newer newest wide wider widest"
    merges = train_bpe(corpus, num_merges=10)
    print("Learned merges, in order:")
    for i, m in enumerate(merges):
        print(f"  {i+1}. {m}")

    test_text = "lower widest"
    print(f"\nTokenizing '{test_text}':")
    print(tokenize(test_text, merges))

    print()
    vocab_size_tradeoff_demo()

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
LLaMA uses a 32K SentencePiece BPE vocabulary; GPT-4-class models use a
much larger ~100K+ vocabulary specifically because a larger vocabulary
compresses common multi-lingual and code text into fewer tokens, directly
reducing the sequence length (and therefore the O(seq_len^2) attention
cost from L03) needed to represent the same information — a tokenizer
design decision that has a real, measurable effect on inference cost
before you've touched a single weight's precision.
"""

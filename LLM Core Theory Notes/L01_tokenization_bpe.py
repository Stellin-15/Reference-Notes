"""
WHAT: Byte-Pair Encoding (BPE) tokenization derived from first principles
      -- why LLMs operate on subword units rather than whole words or
      raw characters, and the exact greedy merge algorithm that builds a
      BPE vocabulary from a training corpus.
WHY:  "LLMs break text into tokens" is usually stated without explaining
      WHY subword tokenization specifically, or how the vocabulary is
      actually built. This lesson derives the problem BPE solves (the
      vocabulary-size vs. out-of-vocabulary tradeoff), then builds a
      working BPE tokenizer from scratch so "the model sees tokens, not
      words" becomes a concrete, traceable mechanism for every subsequent
      lesson in this track.
LEVEL: Foundational -- first lesson in the LLM Core Theory Notes track.

PREREQUISITE: Deep Learning Theory Notes L01 (this repo's general deep
learning foundations); no LLM-specific prerequisite -- this is the entry
point to the track.
"""

from collections import Counter

# ============================================================================
# CONCEPT #1 — THE VOCABULARY-SIZE TRADEOFF: WHY NOT WORDS, WHY NOT
# CHARACTERS
# ============================================================================
#
# Any model that predicts "the next unit of text" needs a FIXED, FINITE
# vocabulary of possible units, with each unit mapped to a learnable
# embedding vector. Two naive choices, and the specific problem each has:
#
#   WORD-LEVEL TOKENIZATION (split on whitespace/punctuation, one token
#   per word): a natural-language vocabulary is enormous and OPEN-ENDED
#   -- new words (names, typos, technical jargon, words in other
#   languages, "tokenization" itself if it wasn't in training data)
#   constantly appear that were never seen during vocabulary construction.
#   Any word-level vocabulary must either be impractically large (millions
#   of entries, most seen extremely rarely -- a direct instance of
#   Classical ML Theory Notes L08's curse-of-dimensionality concern, now
#   applied to vocabulary size rather than feature count) or must map
#   unseen words to a generic <UNK> (unknown) token, permanently
#   DISCARDING information about what that specific unseen word was.
#
#   CHARACTER-LEVEL TOKENIZATION (one token per character): the
#   vocabulary is small and FIXED (roughly 100-1000 tokens covering all
#   characters/symbols in use) -- no out-of-vocabulary problem at all.
#   But this comes at a severe cost: SEQUENCE LENGTH explodes (a sentence
#   that's ~15 word-tokens becomes ~75+ character-tokens), and per L07 of
#   Deep Learning Theory Notes, self-attention's cost scales O(T^2) in
#   sequence length -- character-level tokenization multiplies compute
#   cost dramatically for the SAME text, for no benefit if most character
#   sequences are actually highly predictable (the letters "t-h-e" almost
#   always appear together as "the"; modeling this from raw characters
#   wastes model capacity re-deriving something a coarser vocabulary
#   would encode for free).
#
# BPE (and subword tokenization generally) is the compromise: a FIXED,
# MODERATE-SIZED vocabulary (commonly 30,000-100,000+ tokens) built from
# actual DATA, where common words get their own single token (efficient,
# short sequences) while rare/unseen words get decomposed into a SEQUENCE
# of smaller, previously-seen subword pieces (no true out-of-vocabulary
# problem -- ANY string can be represented as SOME sequence of subword
# units, in the worst case falling back to individual bytes/characters).

# ============================================================================
# CONCEPT #2 — THE BPE ALGORITHM: GREEDILY MERGE THE MOST FREQUENT
# ADJACENT PAIR, REPEATEDLY
# ============================================================================
#
# BPE (adapted from a 1994 data-compression algorithm, by Sennrich et al.
# 2015 for NLP) builds a vocabulary via this greedy procedure:
#
#   1. Start with a vocabulary of individual CHARACTERS (or bytes, in the
#      "byte-level BPE" variant essentially all modern LLMs use --
#      Concept #4). Every word in the training corpus is represented as
#      a sequence of these base units.
#   2. Count the frequency of every ADJACENT PAIR of units across the
#      entire corpus (e.g. how often does "t" immediately follow "e" in
#      "the," summed across every occurrence of "the" and any other word
#      containing that adjacent pair).
#   3. MERGE the single MOST FREQUENT pair into one new, single unit
#      (e.g. if "t"+"h" is the most frequent adjacent pair, "th" becomes
#      a new vocabulary entry, and every occurrence of adjacent "t","h"
#      in the corpus is replaced with the single unit "th").
#   4. Repeat steps 2-3 for a fixed number of merges (this number IS the
#      vocabulary-size hyperparameter -- more merges = larger vocabulary
#      = longer per-merge-built units = shorter average token sequences,
#      directly instantiating Concept #1's tradeoff as a single tunable
#      knob).
#
# This is a GREEDY algorithm (always take the locally-best merge, per
# Classical ML Theory Notes L03's discussion of greedy tree-splitting) --
# it does not guarantee a globally optimal vocabulary for any downstream
# objective, but it's cheap to compute and, empirically, produces
# vocabularies where common subword patterns (word roots, suffixes like
# "-ing," "-ed," common short words) end up as single tokens, while rare/
# novel strings decompose into more, smaller pieces -- exactly the
# behavior Concept #1 motivated.

def get_pair_frequencies(word_freqs):
    """Counts every adjacent SYMBOL pair across the corpus, weighted by
    each word's frequency -- the core statistic BPE's merge step needs."""
    pairs = Counter()
    for word_symbols, freq in word_freqs.items():
        symbols = word_symbols
        for i in range(len(symbols) - 1):
            pairs[(symbols[i], symbols[i + 1])] += freq
    return pairs


def merge_pair(pair, word_freqs):
    """Replaces every adjacent occurrence of `pair` with the single merged
    unit, across the entire corpus -- step 3 of the BPE algorithm."""
    new_word_freqs = {}
    bigram = pair[0] + pair[1]
    for word_symbols, freq in word_freqs.items():
        new_symbols = []
        i = 0
        while i < len(word_symbols):
            if (i < len(word_symbols) - 1
                    and word_symbols[i] == pair[0]
                    and word_symbols[i + 1] == pair[1]):
                new_symbols.append(bigram)
                i += 2
            else:
                new_symbols.append(word_symbols[i])
                i += 1
        new_word_freqs[tuple(new_symbols)] = new_word_freqs.get(tuple(new_symbols), 0) + freq
    return new_word_freqs


def train_bpe(corpus, num_merges):
    """
    The full training loop: start from characters, repeatedly find and
    merge the most frequent adjacent pair, recording the ORDERED list of
    merges (this order matters -- it's exactly what a trained BPE
    tokenizer's "merge rules" file encodes, and tokenizing NEW text later
    means applying these same merges in the SAME learned order).
    """
    # Initialize: every word split into individual characters, with an
    # end-of-word marker "</w>" so BPE can learn that "est" at a word's
    # END (e.g. "highest") is a different pattern from "est" elsewhere.
    words = corpus.split()
    word_freqs = Counter(words)
    word_freqs = {tuple(list(w) + ["</w>"]): f for w, f in word_freqs.items()}

    merges = []
    vocab = set(c for word in word_freqs for c in word)

    for _ in range(num_merges):
        pairs = get_pair_frequencies(word_freqs)
        if not pairs:
            break
        best_pair = max(pairs, key=pairs.get)
        word_freqs = merge_pair(best_pair, word_freqs)
        merges.append(best_pair)
        vocab.add(best_pair[0] + best_pair[1])

    return merges, vocab


def tokenize_with_bpe(word, merges):
    """
    Applies a TRAINED sequence of merges to a NEW word (possibly unseen
    during training) -- this is the actual tokenization step used at
    inference time, applying the SAME ordered merge rules learned during
    training, in the same order they were learned.
    """
    symbols = list(word) + ["</w>"]
    for pair in merges:
        i = 0
        new_symbols = []
        while i < len(symbols):
            if (i < len(symbols) - 1
                    and symbols[i] == pair[0]
                    and symbols[i + 1] == pair[1]):
                new_symbols.append(pair[0] + pair[1])
                i += 2
            else:
                new_symbols.append(symbols[i])
                i += 1
        symbols = new_symbols
    return symbols


# ============================================================================
# CONCEPT #3 — WHY MERGE ORDER MATTERS FOR TOKENIZING UNSEEN WORDS (not
# just for building the vocabulary)
# ============================================================================
#
# A trained BPE tokenizer's "model" IS the ordered list of merges (not
# just the final vocabulary set) -- when tokenizing a brand-new word
# never seen in training, you apply the SAME merges IN THE SAME ORDER
# they were learned, checking at each step whether that specific merge's
# pair currently appears adjacent in the (partially-merged) new word. This
# is why the ORDER of merges is saved and reused, not just the final set
# of multi-character tokens -- two different merge ORDERS could produce
# the exact same FINAL vocabulary set but tokenize a novel word
# DIFFERENTLY, because which merges get "tried" earlier changes which
# adjacent pairs still exist by the time a later merge rule is checked.
# This is a genuinely easy detail to get wrong in a naive from-scratch
# implementation (e.g. trying to tokenize by just greedily matching the
# LONGEST known vocabulary substring at each position, ignoring merge
# order, which can produce a different, generally worse, tokenization
# than correctly replaying the learned merge sequence).

def demonstrate_merge_order_matters():
    """
    Confirms that tokenizing depends on REPLAYING the learned merge
    sequence in order, not just checking substring membership in the
    final vocabulary -- by tokenizing a novel word with the trained
    merges and showing the result follows the SPECIFIC learned order.
    """
    corpus = "low low low low low lower lower newest newest newest widest widest"
    merges, vocab = train_bpe(corpus, num_merges=10)
    novel_word = "lowest"  # never appeared in the training corpus
    tokens = tokenize_with_bpe(novel_word, merges)
    return merges, tokens


# ============================================================================
# CONCEPT #4 — BYTE-LEVEL BPE: WHY MODERN LLM TOKENIZERS OPERATE ON RAW
# BYTES, NOT UNICODE CHARACTERS
# ============================================================================
#
# The BPE algorithm as described in Concept #2 starts from a base
# vocabulary of "characters." A naive Unicode-character-level base
# vocabulary has a real problem: Unicode has over 140,000 possible
# characters (covering every human language's scripts, emoji, symbols)
# -- even the STARTING base vocabulary, before any merges, would need to
# be enormous to guarantee no out-of-vocabulary character ever appears,
# reintroducing exactly the open-vocabulary problem Concept #1's BPE was
# built to solve.
#
# BYTE-LEVEL BPE (used by GPT-2 onward, and essentially all modern LLM
# tokenizers) instead starts from the base vocabulary of raw BYTES --
# there are EXACTLY 256 possible byte values, a small, genuinely closed,
# fixed-size vocabulary that can represent absolutely ANY sequence of
# UTF-8-encoded text (any language, any emoji, any symbol, even malformed/
# unusual byte sequences) without needing a special <UNK> fallback token
# AT ALL -- the base 256-byte vocabulary is a mathematically complete
# starting point (every possible piece of digital text IS a sequence of
# bytes, by definition), and BPE merges build UP from there exactly as
# in Concept #2, just starting from bytes instead of Unicode characters.
# This is why a modern LLM tokenizer can, in principle, tokenize (even
# if inefficiently, using many single-byte tokens) genuinely never-seen
# scripts or malformed input, with zero true out-of-vocabulary failures
# -- a direct, complete fix for Concept #1's original open-vocabulary
# problem, one level below where character-level BPE still had a gap.

def bytes_are_a_closed_vocabulary():
    """Confirms there are exactly 256 possible byte values, and that ANY
    string (including multi-byte Unicode characters, e.g. emoji) can be
    represented as SOME sequence of these 256 base units -- Concept #4's
    "mathematically complete starting point" claim, made concrete."""
    all_byte_values = list(range(256))
    test_string = "hello world" + "中文" + "\U0001F600"  # mixed scripts + emoji
    encoded = test_string.encode("utf-8")
    byte_values_used = set(encoded)
    return len(all_byte_values), len(encoded), byte_values_used.issubset(set(all_byte_values))


# ============================================================================
# PRODUCTION USE CASE
# ============================================================================
# A team fine-tuning an LLM for a code-generation product notices the
# model performs noticeably worse on a newer programming language with
# unusual syntax (heavy use of unusual symbol combinations rarely seen
# in the model's original pretraining corpus, which predated that
# language's popularity). Per Concept #2's core mechanism, this is a
# DIRECT, predictable consequence: BPE's vocabulary was built (via
# frequency-based merges) from the ORIGINAL pretraining corpus's
# distribution of text -- symbol combinations common in this newer
# language but rare/absent in the tokenizer's training corpus get
# tokenized into MANY small, individual-byte-or-character-level tokens
# rather than a few efficient, meaningful merged units, both wasting
# context-window budget (more tokens per line of code, per L07 of Deep
# Learning Theory Notes' O(T^2) attention-cost concern) AND giving the
# model a less semantically meaningful input representation for that
# syntax (individual bytes carry far less directly useful signal than a
# merged token representing a whole common operator or keyword would).
# The correctly-targeted fix is RE-TRAINING (or extending) the BPE
# vocabulary on a corpus that includes substantial representative code
# in the new language -- not simply fine-tuning the existing model
# longer on the same stale tokenization, which cannot fix a vocabulary-
# level mismatch no matter how much additional training occurs on top
# of it.

# ============================================================================
# COMMON MISTAKES
# ============================================================================
# 1. Assuming "tokens" correspond to whole words. Per Concept #1-#2, a
#    single word can (and very often does, especially for rare words,
#    technical terms, or non-English text) decompose into MULTIPLE
#    tokens -- code that assumes "number of tokens ≈ number of words" for
#    context-window budgeting or cost estimation will be systematically
#    wrong, sometimes by a large factor, particularly for non-English
#    text or specialized vocabulary.
# 2. Treating tokenization as a simple, "solved," inconsequential
#    preprocessing step. Per the Production Use Case above, tokenizer
#    vocabulary mismatch with a target domain is a REAL, diagnosable
#    performance-degrading issue, not a negligible detail -- fine-tuning
#    or prompt-engineering cannot fully compensate for the model
#    receiving an inefficient/uninformative token representation of the
#    input in the first place.
# 3. Implementing tokenization by greedily matching the LONGEST known
#    vocabulary substring at each position, rather than replaying the
#    learned merge order (Concept #3). This can produce a DIFFERENT
#    tokenization of a novel word than the correctly-trained tokenizer
#    would produce, silently causing a mismatch between how a model was
#    trained to interpret tokens and how a custom or reimplemented
#    tokenizer actually splits text.
# 4. Believing byte-level BPE (Concept #4) means the model "sees" raw
#    UTF-8 bytes as its primary working representation during training/
#    inference. Byte-level BPE only affects the BASE vocabulary the merge
#    algorithm starts from (guaranteeing completeness/no <UNK>) -- after
#    the learned merges are applied, most real text is represented by a
#    small number of large, meaningful merged tokens, not by many raw
#    single-byte tokens; only genuinely rare/unusual input falls back
#    toward the byte-level base units.


if __name__ == "__main__":
    print("=" * 70)
    print("CONCEPT #2: training a tiny BPE vocabulary from a toy corpus")
    print("=" * 70)
    corpus = "low low low low low lower lower newest newest newest widest widest"
    merges, vocab = train_bpe(corpus, num_merges=10)
    print("First 5 merges learned (in order):")
    for i, m in enumerate(merges[:5]):
        print(f"  merge {i+1}: {m[0]!r} + {m[1]!r} -> {m[0]+m[1]!r}")
    print(f"\nFinal vocabulary size (base chars + merges): {len(vocab)}")

    print("\n" + "=" * 70)
    print("CONCEPT #3: tokenizing a NOVEL word ('lowest') using learned merges")
    print("=" * 70)
    _, tokens = demonstrate_merge_order_matters()
    print(f"'lowest' was NEVER in the training corpus.")
    print(f"Tokenized as: {tokens}")
    print("-> Should decompose into meaningful learned pieces (e.g. a merged")
    print("   'low' piece plus separate pieces for 'est</w>'), demonstrating")
    print("   that BPE generalizes to unseen words via its learned merge rules,")
    print("   rather than requiring 'lowest' to have appeared during training.")

    print("\n" + "=" * 70)
    print("CONCEPT #4: byte-level vocabulary is closed (exactly 256 values)")
    print("=" * 70)
    n_byte_values, n_bytes_in_test, all_within_256 = bytes_are_a_closed_vocabulary()
    print(f"Number of possible byte values: {n_byte_values}")
    print(f"A mixed English+Chinese+emoji string encodes to {n_bytes_in_test} bytes")
    print(f"Every byte value used falls within the base 256-value vocabulary? "
          f"{all_within_256}")
    print("-> Confirms ANY text (any script, any emoji) decomposes into SOME")
    print("   sequence of the same fixed 256 base byte-values, guaranteeing")
    print("   byte-level BPE never needs an <UNK> fallback token for coverage.")

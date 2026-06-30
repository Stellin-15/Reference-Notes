# ============================================================
# L06: PyTorch — CNNs and NLP (Transformers, LSTM, HuggingFace)
# ============================================================
# WHAT: Covers computer vision (CNNs, transfer learning) and
#       NLP (LSTM, Transformer, Hugging Face fine-tuning) in
#       PyTorch. Two very different domains, but the same
#       Module / forward() / DataLoader / optimizer pattern.
# WHY:  CNNs and NLP are the two most commercially deployed
#       deep learning domains. Understanding both at architecture
#       level lets you debug poor training, choose the right
#       model, and adapt pretrained models to new problems.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    CNNs exploit spatial locality and translation invariance —
    a cat looks like a cat wherever it is in the image. The
    key insight: share weights across spatial positions (conv
    filter). This is orders of magnitude more parameter-efficient
    than a fully connected layer over the flattened image.

    NLP requires handling variable-length sequences and long-range
    dependencies. LSTMs use gating (forget/input/output gates)
    to carry information across many steps. Transformers replace
    recurrence with self-attention (O(n^2) in sequence length
    but fully parallelizable). Attention is now dominant for NLP.

    Hugging Face makes it practical to fine-tune BERT/GPT/T5
    on domain-specific tasks without training from scratch.

PRODUCTION USE CASE:
    - Transfer learning: ResNet/EfficientNet pretrained on
      ImageNet → fine-tuned on medical imaging (X-rays, pathology).
      Accuracy comparable to radiologists with <10k labeled examples.
    - BERT fine-tuned on customer support tickets for intent
      classification. Replaces hand-crafted keyword rules.
    - DistilBERT for sentiment analysis in real-time product review
      pipeline — 6x faster than BERT, 97% of BERT accuracy.

COMMON MISTAKES:
    1. Not normalizing input images with ImageNet mean/std when
       using pretrained models — the pretrained weights expect
       normalized input and will produce garbage otherwise.
    2. Forgetting to freeze backbone weights for early fine-tuning
       epochs — randomly initialized head will corrupt pretrained
       features with large gradients.
    3. Using the same LR for pretrained backbone and new head —
       use differential LR: 1e-5 for backbone, 1e-3 for head.
    4. Not packing padded sequences for LSTM — padding tokens
       are fed through LSTM cells unnecessarily, degrading the
       final hidden state.
    5. Using BERT's [CLS] token output without fine-tuning —
       pretrained [CLS] is trained for NSP (next sentence prediction),
       not your task. You must fine-tune at least the head.
    6. Forgetting to call tokenizer with truncation=True and
       max_length — sequences longer than 512 crash BERT.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence, pad_sequence
import torch.optim as optim
import math

# ============================================================
# SECTION 1: CNN FOR IMAGE CLASSIFICATION
# ============================================================
# WHAT: Convolutional Neural Networks learn hierarchical spatial
#       features. Early layers detect edges and textures; deeper
#       layers detect objects and semantic content.
# WHY:  The key operations and their roles:
#       Conv2d — shared weight filter slides over the image.
#                Detects the same feature at any spatial location.
#       BatchNorm2d — normalize activations per channel per mini-batch.
#                     Stabilizes training, decouples layer scale from LR.
#       ReLU — non-linearity. Simple, fast, avoids vanishing gradient.
#       MaxPool2d — spatial downsampling. Reduces resolution, adds
#                   translation invariance within pool window.

class ConvBlock(nn.Module):
    """
    Standard building block: Conv2d → BatchNorm2d → ReLU.
    Optionally followed by MaxPool2d.
    Reason this order matters:
      - BN before activation (normalize → activate) is the standard.
      - Some papers do BN after activation — both work, but BN-first
        is more common and slightly more stable.
    """
    def __init__(self, in_channels: int, out_channels: int,
                 kernel_size: int = 3, stride: int = 1,
                 padding: int = 1, pool: bool = True):
        super().__init__()
        self.conv = nn.Conv2d(
            in_channels, out_channels,
            kernel_size=kernel_size,
            stride=stride,
            padding=padding,   # 'same' padding: output spatial size = input
            bias=False         # bias is redundant when followed by BN
        )
        # BatchNorm2d: normalizes across the batch for each channel.
        # Has learnable affine params (weight/bias) to rescale.
        # Also maintains running_mean/running_var for inference mode.
        self.bn = nn.BatchNorm2d(out_channels)
        self.relu = nn.ReLU(inplace=True)  # inplace saves memory
        # MaxPool: halves spatial dims (stride=2, kernel=2).
        self.pool = nn.MaxPool2d(2, 2) if pool else nn.Identity()

    def forward(self, x):
        return self.pool(self.relu(self.bn(self.conv(x))))


class SimpleCNN(nn.Module):
    """
    CNN for MNIST: input shape (N, 1, 28, 28) → 10 classes.
    Architecture: Conv → Conv → Flatten → FC → FC → Softmax (implicit in CE loss).
    """
    def __init__(self, num_classes: int = 10):
        super().__init__()

        # Block 1: 1 → 32 channels, 28×28 → 14×14 (after pool)
        self.block1 = ConvBlock(in_channels=1, out_channels=32, pool=True)

        # Block 2: 32 → 64 channels, 14×14 → 7×7 (after pool)
        self.block2 = ConvBlock(in_channels=32, out_channels=64, pool=True)

        # Global Average Pooling: 64 × 7 × 7 → 64 × 1 × 1 → 64.
        # WHY GAP over flatten:
        #   - Flatten: 64×7×7 = 3136 params per channel → huge FC layer.
        #   - GAP: averages each channel → 64 values. No params!
        #   - More regularized, better generalization, smaller model.
        #   - Used in ResNet, EfficientNet, MobileNet.
        self.gap = nn.AdaptiveAvgPool2d(1)  # output size (1, 1) regardless of input

        self.classifier = nn.Sequential(
            nn.Dropout(0.5),
            nn.Linear(64, 128),
            nn.ReLU(),
            nn.Linear(128, num_classes)
            # No Softmax here — nn.CrossEntropyLoss applies log-softmax internally.
        )

    def forward(self, x):
        # x: (N, 1, 28, 28)
        x = self.block1(x)  # (N, 32, 14, 14)
        x = self.block2(x)  # (N, 64, 7, 7)
        x = self.gap(x)     # (N, 64, 1, 1)
        x = x.squeeze(-1).squeeze(-1)  # (N, 64) — remove spatial dims
        return self.classifier(x)  # (N, 10)


# ============================================================
# SECTION 2: TRANSFER LEARNING
# ============================================================
# WHAT: Pretrained model (trained on ImageNet: 1.2M images, 1000 classes)
#       is used as a feature extractor. Only the final classification
#       head is replaced and trained for the new task.
# WHY:  ImageNet features are general: edges, textures, shapes are
#       universal. Fine-tuning leverages this — you get powerful
#       features with just hundreds or thousands of labeled examples.
#       Training from scratch with that data would wildly overfit.

try:
    import torchvision.models as models
    from torchvision.models import ResNet50_Weights

    def build_transfer_model(num_classes: int, freeze_backbone: bool = True):
        """
        ResNet-50 fine-tuned for a custom classification task.
        Strategy:
          Phase 1 (epochs 1-5): freeze backbone, train only head.
                   High LR for head (1e-3). Fast convergence.
          Phase 2 (epochs 6-20): unfreeze backbone, fine-tune all.
                   Low LR for backbone (1e-5), slightly higher for head (1e-4).
        """
        # Modern API: weights= instead of pretrained=True (deprecated).
        # IMAGENET1K_V2 is the better-performing set of weights.
        model = models.resnet50(weights=ResNet50_Weights.IMAGENET1K_V2)

        if freeze_backbone:
            # Freeze all parameters — they will not be updated.
            # This protects expensive pretrained features during head training.
            for param in model.parameters():
                param.requires_grad = False

        # ResNet-50's final layer: model.fc = Linear(2048, 1000)
        # Replace with our task's number of classes.
        # model.fc is NOT frozen — it's the new trainable head.
        in_features = model.fc.in_features  # 2048 for ResNet-50
        model.fc = nn.Sequential(
            nn.Dropout(0.3),
            nn.Linear(in_features, 512),
            nn.ReLU(),
            nn.Linear(512, num_classes)
        )
        # model.fc has requires_grad=True by default (new module).
        return model

    def unfreeze_backbone(model, layers_to_unfreeze: int = 2):
        """
        Gradually unfreeze the last N layer groups of ResNet.
        Called after initial head training converges.
        Use a very small LR for backbone (1e-5 or lower).
        """
        # ResNet-50 layer groups: layer4, layer3, layer2, layer1, conv1.
        children = list(model.children())
        for child in children[-layers_to_unfreeze:]:
            for param in child.parameters():
                param.requires_grad = True

    def get_differential_lr_params(model, backbone_lr: float = 1e-5,
                                    head_lr: float = 1e-3):
        """
        Return parameter groups with different LRs for backbone vs head.
        Pass this list to optimizer instead of model.parameters().
        """
        backbone_params = [p for name, p in model.named_parameters()
                           if 'fc' not in name and p.requires_grad]
        head_params = [p for name, p in model.named_parameters()
                       if 'fc' in name and p.requires_grad]
        return [
            {'params': backbone_params, 'lr': backbone_lr},
            {'params': head_params, 'lr': head_lr},
        ]

    TORCHVISION_AVAILABLE = True
except ImportError:
    TORCHVISION_AVAILABLE = False
    print("torchvision not installed — skipping transfer learning section.")


# ============================================================
# SECTION 3: TEXT PREPROCESSING AND EMBEDDING
# ============================================================
# WHAT: Convert raw text to integer token indices, then to
#       dense vector representations (embeddings).
# WHY:  Neural networks work on continuous vectors, not strings.
#       Embeddings capture semantic relationships — "king" and
#       "queen" are close in embedding space. They're learned
#       jointly with the task or initialized from pretrained
#       word vectors (GloVe, Word2Vec, FastText).

class Vocabulary:
    """Map tokens to indices and back. The standard NLP preprocessing step."""
    PAD_TOKEN = '<PAD>'  # index 0 — used for sequence padding
    UNK_TOKEN = '<UNK>'  # index 1 — unknown/out-of-vocab words
    SOS_TOKEN = '<SOS>'  # index 2 — start of sequence
    EOS_TOKEN = '<EOS>'  # index 3 — end of sequence

    def __init__(self):
        self.token2idx = {
            self.PAD_TOKEN: 0,
            self.UNK_TOKEN: 1,
            self.SOS_TOKEN: 2,
            self.EOS_TOKEN: 3,
        }
        self.idx2token = {v: k for k, v in self.token2idx.items()}

    def build(self, texts: list, min_freq: int = 2):
        """Build vocab from a list of tokenized texts."""
        from collections import Counter
        counter = Counter(token for text in texts for token in text.split())
        for token, freq in counter.items():
            if freq >= min_freq and token not in self.token2idx:
                idx = len(self.token2idx)
                self.token2idx[token] = idx
                self.idx2token[idx] = token

    def encode(self, text: str, max_len: int = None) -> torch.Tensor:
        """Convert text string to tensor of indices."""
        tokens = text.split()
        if max_len:
            tokens = tokens[:max_len]
        indices = [self.token2idx.get(t, 1) for t in tokens]  # 1 = UNK
        return torch.tensor(indices, dtype=torch.long)

    def __len__(self):
        return len(self.token2idx)


class TextDataset(Dataset):
    """Dataset for sequence classification (e.g., sentiment analysis)."""
    def __init__(self, texts: list, labels: list, vocab: Vocabulary,
                 max_len: int = 128):
        self.encodings = [vocab.encode(t, max_len) for t in texts]
        self.labels = labels

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        return self.encodings[idx], torch.tensor(self.labels[idx])


def text_collate_fn(batch):
    """Pad variable-length text sequences to the max length in the batch."""
    sequences, labels = zip(*batch)
    padded = pad_sequence(sequences, batch_first=True, padding_value=0)
    lengths = torch.tensor([len(s) for s in sequences])
    return padded, torch.stack(labels), lengths


# ============================================================
# SECTION 4: LSTM FOR SEQUENCE CLASSIFICATION
# ============================================================
# WHAT: Long Short-Term Memory networks process sequences
#       step-by-step. The cell state (c_t) carries long-term
#       memory; gating controls what to forget/store/output.
# WHY:  LSTMs handle vanishing gradients better than vanilla RNNs
#       via the forget gate. They're still used when:
#       - Sequence length is short (<500 tokens).
#       - Computational budget is tight (cheaper than Transformer).
#       - Streaming / online inference (process one token at a time).
#       For longer sequences or when accuracy is paramount, use
#       Transformers.

class LSTMClassifier(nn.Module):
    """
    Bidirectional LSTM for text classification.
    Bidirectional: reads text both forward and backward.
    Final representation: concatenate forward and backward final states.
    """
    def __init__(self, vocab_size: int, embed_dim: int = 128,
                 hidden_size: int = 256, num_layers: int = 2,
                 num_classes: int = 2, dropout: float = 0.3,
                 pad_idx: int = 0):
        super().__init__()

        # Embedding layer: lookup table mapping token index → dense vector.
        # padding_idx=0 ensures the PAD token's embedding is always zero
        # and its gradient is not updated.
        self.embedding = nn.Embedding(
            vocab_size, embed_dim, padding_idx=pad_idx
        )

        # nn.LSTM arguments:
        #   input_size: embedding dimension
        #   hidden_size: number of LSTM units (per direction)
        #   num_layers: stack multiple LSTMs (deeper = more capacity)
        #   batch_first: input/output shape (batch, seq, features)
        #   bidirectional: run forward and backward in parallel
        #   dropout: applied BETWEEN LSTM layers (not after last layer)
        self.lstm = nn.LSTM(
            input_size=embed_dim,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            bidirectional=True,   # 2× the output size
            dropout=dropout if num_layers > 1 else 0.0,
        )

        # Bidirectional: hidden state is (2 * hidden_size).
        lstm_output_size = hidden_size * 2

        self.classifier = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(lstm_output_size, 128),
            nn.ReLU(),
            nn.Linear(128, num_classes)
        )

    def forward(self, x: torch.Tensor, lengths: torch.Tensor):
        """
        x: (batch, seq_len) — padded token indices
        lengths: (batch,) — actual sequence lengths before padding
        """
        # (batch, seq_len, embed_dim)
        embedded = self.embedding(x)

        # pack_padded_sequence: tells LSTM to skip padded positions.
        # Computationally equivalent to running LSTM on each unpadded
        # sequence separately, but in a single batched CUDA call.
        # enforce_sorted=False: no need to sort by length.
        packed = pack_padded_sequence(
            embedded, lengths.cpu(), batch_first=True, enforce_sorted=False
        )

        # packed_output: packed representation of all hidden states.
        # h_n: (num_layers * num_directions, batch, hidden_size) — final hidden.
        # c_n: same shape — final cell state (long-term memory).
        packed_output, (h_n, c_n) = self.lstm(packed)

        # For classification, we only need the final hidden states.
        # h_n[-2]: forward direction, last layer.
        # h_n[-1]: backward direction, last layer.
        # Concatenate along feature dim → (batch, 2 * hidden_size).
        forward_hidden = h_n[-2]   # shape: (batch, hidden_size)
        backward_hidden = h_n[-1]  # shape: (batch, hidden_size)
        final_hidden = torch.cat([forward_hidden, backward_hidden], dim=-1)

        return self.classifier(final_hidden)


# ============================================================
# SECTION 5: POSITIONAL ENCODING AND TRANSFORMER
# ============================================================
# WHAT: Transformer self-attention is permutation-equivariant
#       (it doesn't know which token comes first). Positional
#       encoding injects position information.
# WHY:  Word order matters in NLP. "Dog bites man" ≠ "Man bites dog".
#       Sinusoidal encoding (original paper): deterministic, no params,
#       generalizes to sequences longer than seen at train time.
#       Learned positional encoding: trainable, slightly better on
#       standard benchmarks, but can't extrapolate beyond max_len.

class SinusoidalPositionalEncoding(nn.Module):
    """
    Sinusoidal positional encoding from 'Attention is All You Need'.
    PE(pos, 2i)   = sin(pos / 10000^(2i/d_model))
    PE(pos, 2i+1) = cos(pos / 10000^(2i/d_model))
    Added (not concatenated) to token embeddings.
    """
    def __init__(self, d_model: int, max_len: int = 5000,
                 dropout: float = 0.1):
        super().__init__()
        self.dropout = nn.Dropout(dropout)

        # Build the positional encoding table once at init.
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len).unsqueeze(1).float()
        div_term = torch.exp(
            torch.arange(0, d_model, 2).float() *
            (-math.log(10000.0) / d_model)
        )
        pe[:, 0::2] = torch.sin(position * div_term)  # even dims
        pe[:, 1::2] = torch.cos(position * div_term)  # odd dims

        # Register as buffer: saved in state_dict but not a parameter.
        # Not updated by optimizer. Moved to GPU with model.to(device).
        self.register_buffer('pe', pe.unsqueeze(0))  # (1, max_len, d_model)

    def forward(self, x: torch.Tensor):
        # x: (batch, seq_len, d_model)
        # Slice positional encoding to match current sequence length.
        x = x + self.pe[:, :x.size(1), :]
        return self.dropout(x)


class TransformerClassifier(nn.Module):
    """
    Transformer encoder for text classification.
    Architecture: Embedding + PositionalEncoding → TransformerEncoder
                  → mean pooling → classifier head.
    """
    def __init__(self, vocab_size: int, d_model: int = 128,
                 nhead: int = 4, num_layers: int = 3,
                 dim_feedforward: int = 512, num_classes: int = 2,
                 max_len: int = 512, dropout: float = 0.1,
                 pad_idx: int = 0):
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, d_model, padding_idx=pad_idx)
        self.pos_encoding = SinusoidalPositionalEncoding(d_model, max_len, dropout)

        # TransformerEncoderLayer: one multi-head attention + FFN block.
        # batch_first=True: (batch, seq, features) convention (PyTorch >= 1.9).
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,                  # number of attention heads
            dim_feedforward=dim_feedforward,  # FFN hidden dim (typically 4× d_model)
            dropout=dropout,
            activation='gelu',            # GELU > ReLU for transformers
            batch_first=True,
            norm_first=True,              # Pre-LN: normalize before attention (more stable)
        )

        # Stack num_layers encoder layers with LayerNorm at the end.
        self.transformer = nn.TransformerEncoder(
            encoder_layer, num_layers=num_layers,
            norm=nn.LayerNorm(d_model)
        )

        self.classifier = nn.Sequential(
            nn.Linear(d_model, d_model),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model, num_classes)
        )
        self.d_model = d_model

    def forward(self, x: torch.Tensor, padding_mask: torch.Tensor = None):
        """
        x: (batch, seq_len) — token indices
        padding_mask: (batch, seq_len) — True where tokens are PAD
        """
        # Scale embeddings by sqrt(d_model) — from original paper.
        # Prevents positional encoding from dominating early in training.
        embeddings = self.embedding(x) * math.sqrt(self.d_model)
        embeddings = self.pos_encoding(embeddings)

        # src_key_padding_mask: True values are IGNORED by attention.
        # Prevents attention from attending to PAD tokens.
        output = self.transformer(
            embeddings,
            src_key_padding_mask=padding_mask  # (batch, seq_len)
        )

        # Pooling strategy: mean over non-padding tokens.
        # Alternative: use [CLS] token at position 0 (BERT-style).
        if padding_mask is not None:
            mask = (~padding_mask).float().unsqueeze(-1)  # (batch, seq, 1)
            output = (output * mask).sum(dim=1) / mask.sum(dim=1)
        else:
            output = output.mean(dim=1)  # (batch, d_model)

        return self.classifier(output)


# ============================================================
# SECTION 6: HUGGING FACE TRANSFORMERS
# ============================================================
# WHAT: The transformers library provides pretrained BERT, GPT,
#       T5, RoBERTa, DistilBERT, etc. with consistent API.
#       Fine-tune these on downstream tasks with minimal code.
# WHY:  Training BERT from scratch costs millions of dollars.
#       Fine-tuning costs dollars. The pretrained representations
#       already encode deep language understanding — you just
#       need to adapt the final layer to your task.

try:
    from transformers import (
        AutoTokenizer,
        AutoModel,
        AutoModelForSequenceClassification,
        Trainer,
        TrainingArguments,
    )
    HF_AVAILABLE = True
except ImportError:
    HF_AVAILABLE = False
    print("transformers not installed — skipping HuggingFace section.")

if HF_AVAILABLE:

    class SentimentClassifier(nn.Module):
        """
        DistilBERT fine-tuned for binary sentiment classification.
        DistilBERT: 40% smaller than BERT, 60% faster, 97% accuracy.
        Fine-tuning approach: use [CLS] token output → linear classifier.
        """
        def __init__(self, model_name: str = 'distilbert-base-uncased',
                     num_classes: int = 2, dropout: float = 0.1):
            super().__init__()
            # AutoModel: loads the transformer body without task-specific head.
            # This gives us the raw contextual representations.
            self.bert = AutoModel.from_pretrained(model_name)
            hidden_size = self.bert.config.hidden_size  # 768 for BERT base

            self.classifier = nn.Sequential(
                nn.Dropout(dropout),
                nn.Linear(hidden_size, num_classes)
            )

        def forward(self, input_ids, attention_mask):
            """
            input_ids: (batch, seq_len) — tokenized + padded token ids.
            attention_mask: (batch, seq_len) — 1 for real tokens, 0 for PAD.
            """
            # outputs.last_hidden_state: (batch, seq_len, hidden_size)
            # [CLS] token is always at position 0.
            outputs = self.bert(
                input_ids=input_ids,
                attention_mask=attention_mask
            )

            # [CLS] representation: used for classification tasks.
            # For DistilBERT, use outputs.last_hidden_state[:, 0, :].
            # For BERT, can also use outputs.pooler_output (pre-tanh linear).
            cls_output = outputs.last_hidden_state[:, 0, :]  # (batch, hidden)

            return self.classifier(cls_output)


    class SentimentDataset(Dataset):
        """
        Dataset for HuggingFace-tokenized sentiment data.
        Tokenization happens once at init (or lazily in __getitem__).
        """
        def __init__(self, texts: list, labels: list,
                     model_name: str = 'distilbert-base-uncased',
                     max_length: int = 128):
            self.labels = labels
            tokenizer = AutoTokenizer.from_pretrained(model_name)

            # Tokenize all texts at once — fast (uses Rust tokenizer).
            # truncation=True: clip to max_length (BERT max = 512).
            # padding='max_length': pad all to max_length for uniform tensors.
            # return_tensors='pt': return PyTorch tensors.
            self.encodings = tokenizer(
                texts,
                truncation=True,
                padding='max_length',
                max_length=max_length,
                return_tensors='pt'
            )

        def __len__(self):
            return len(self.labels)

        def __getitem__(self, idx):
            return {
                'input_ids': self.encodings['input_ids'][idx],
                'attention_mask': self.encodings['attention_mask'][idx],
                'labels': torch.tensor(self.labels[idx])
            }


    def fine_tune_distilbert(train_texts, train_labels, val_texts, val_labels,
                              num_classes: int = 2, epochs: int = 3):
        """
        Full fine-tuning pipeline for DistilBERT sentiment classifier.
        Two options:
          1. Manual loop (below) — maximum control.
          2. HuggingFace Trainer API — minimal code, handles logging,
             evaluation, checkpointing automatically.
        """
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        model_name = 'distilbert-base-uncased'

        train_dataset = SentimentDataset(train_texts, train_labels, model_name)
        val_dataset = SentimentDataset(val_texts, val_labels, model_name)

        train_loader = DataLoader(train_dataset, batch_size=16, shuffle=True,
                                  pin_memory=True)
        val_loader = DataLoader(val_dataset, batch_size=32)

        model = SentimentClassifier(model_name, num_classes).to(device)

        # Differential LR: lower LR for pretrained BERT weights,
        # higher LR for the randomly initialized classifier head.
        optimizer = optim.AdamW([
            {'params': model.bert.parameters(), 'lr': 2e-5, 'weight_decay': 0.01},
            {'params': model.classifier.parameters(), 'lr': 1e-3, 'weight_decay': 0.01},
        ])

        criterion = nn.CrossEntropyLoss()

        for epoch in range(epochs):
            model.train()
            total_loss = 0.0

            for batch in train_loader:
                input_ids = batch['input_ids'].to(device)
                attention_mask = batch['attention_mask'].to(device)
                labels = batch['labels'].to(device)

                optimizer.zero_grad()
                logits = model(input_ids, attention_mask)
                loss = criterion(logits, labels)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                optimizer.step()
                total_loss += loss.item()

            avg_train_loss = total_loss / len(train_loader)

            # Validation
            model.eval()
            correct = 0
            total = 0
            with torch.no_grad():
                for batch in val_loader:
                    input_ids = batch['input_ids'].to(device)
                    attention_mask = batch['attention_mask'].to(device)
                    labels = batch['labels'].to(device)
                    logits = model(input_ids, attention_mask)
                    preds = logits.argmax(dim=-1)
                    correct += (preds == labels).sum().item()
                    total += labels.size(0)

            val_acc = correct / total
            print(f"Epoch {epoch+1}: Loss={avg_train_loss:.4f}, Val Acc={val_acc:.4f}")

        return model


    def trainer_api_example(train_dataset, val_dataset):
        """
        HuggingFace Trainer API — alternative to manual loop.
        Handles: multi-GPU, mixed precision, gradient accumulation,
        logging (W&B, TensorBoard), checkpointing.
        Best for standard fine-tuning tasks.
        """
        # AutoModelForSequenceClassification: adds a classifier head
        # on top of BERT automatically.
        model = AutoModelForSequenceClassification.from_pretrained(
            'distilbert-base-uncased', num_labels=2
        )

        training_args = TrainingArguments(
            output_dir='./results',
            num_train_epochs=3,
            per_device_train_batch_size=16,
            per_device_eval_batch_size=32,
            learning_rate=2e-5,
            weight_decay=0.01,
            warmup_ratio=0.06,            # 6% of steps as warmup
            evaluation_strategy='epoch',
            save_strategy='epoch',
            load_best_model_at_end=True,
            metric_for_best_model='eval_accuracy',
            fp16=torch.cuda.is_available(),  # mixed precision if GPU available
            gradient_accumulation_steps=2,
            dataloader_num_workers=4,
            report_to='none',             # set 'wandb' or 'tensorboard' in production
        )

        trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=train_dataset,
            eval_dataset=val_dataset,
        )

        trainer.train()
        return model


# ============================================================
# SECTION 7: DEMO / USAGE
# ============================================================

if __name__ == '__main__':
    print("=== Section 1: CNN Architecture ===")
    cnn = SimpleCNN(num_classes=10)
    dummy_images = torch.randn(4, 1, 28, 28)  # batch of 4 MNIST images
    logits = cnn(dummy_images)
    print(f"Input: {dummy_images.shape} → Output: {logits.shape}")  # (4, 10)

    print("\n=== Section 2: Transfer Learning Model ===")
    if TORCHVISION_AVAILABLE:
        transfer_model = build_transfer_model(num_classes=5, freeze_backbone=True)
        param_groups = get_differential_lr_params(
            transfer_model, backbone_lr=1e-5, head_lr=1e-3
        )
        print(f"Parameter groups: {len(param_groups)} (backbone + head)")

    print("\n=== Section 3: LSTM Classifier ===")
    vocab = Vocabulary()
    sample_texts = ["this movie was great", "terrible waste of time",
                    "absolutely loved it", "worst film ever made"]
    vocab.build(sample_texts, min_freq=1)

    lstm_model = LSTMClassifier(
        vocab_size=len(vocab), embed_dim=64, hidden_size=128,
        num_layers=2, num_classes=2
    )
    dataset = TextDataset(
        sample_texts, [1, 0, 1, 0], vocab, max_len=20
    )
    loader = DataLoader(dataset, batch_size=2, collate_fn=text_collate_fn)
    for tokens, labels, lengths in loader:
        out = lstm_model(tokens, lengths)
        print(f"LSTM output: {out.shape}")  # (2, 2)
        break

    print("\n=== Section 4: Transformer Classifier ===")
    transformer = TransformerClassifier(vocab_size=len(vocab), d_model=64,
                                         nhead=4, num_layers=2, num_classes=2)
    for tokens, labels, lengths in loader:
        padding_mask = (tokens == 0)  # True where token is PAD
        out = transformer(tokens, padding_mask)
        print(f"Transformer output: {out.shape}")  # (2, 2)
        break

    print("\nAll sections complete.")

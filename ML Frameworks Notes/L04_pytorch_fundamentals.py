# ============================================================
# L04: PyTorch Fundamentals
# ============================================================
# WHAT: Tensors, autograd, nn.Module, common layers, loss
#       functions, optimizers, the 4-step training loop,
#       Dataset/DataLoader, learning rate schedulers, model
#       saving/loading, and the train/eval mode distinction.
# WHY:  PyTorch is the dominant framework for research and
#       production deep learning. Its dynamic computation graph
#       (define-by-run) makes debugging with standard Python
#       tools natural. Understanding these fundamentals is the
#       prerequisite for transformers, CNNs, RNNs, and anything
#       built on top.
# LEVEL: Foundations
# ============================================================
"""
CONCEPT OVERVIEW:
    PyTorch models computation as a directed acyclic graph
    (DAG) of tensor operations. Each operation records itself
    in the graph. When you call loss.backward(), PyTorch
    traverses the graph in reverse (chain rule) to compute
    gradients. optimizer.step() then updates weights using
    those gradients. This loop — forward, loss, backward,
    step — is the heartbeat of every neural network.

PRODUCTION USE CASE:
    Binary classifier on tabular data: custom Dataset, DataLoader
    with multi-worker loading, MLP with BatchNorm + Dropout,
    AdamW optimizer, OneCycleLR scheduler, early stopping on
    validation loss, checkpoint saving on best validation score,
    inference under torch.no_grad() with model.eval().

COMMON MISTAKES:
    1. Forgetting model.eval() at inference time — Dropout
       keeps dropping neurons randomly, giving non-deterministic
       predictions. BatchNorm uses batch statistics instead of
       running stats.
    2. Forgetting optimizer.zero_grad() — gradients accumulate
       across backward passes, corrupting weight updates.
    3. Using CrossEntropyLoss with softmax output — CEL includes
       log_softmax internally; passing softmaxed inputs gives
       double-softmax (log(prob) ≈ negative for small probs →
       wrong gradients).
    4. Putting only the model on GPU but leaving data on CPU —
       the forward pass fails with "Expected all tensors to be
       on the same device."
    5. Not pinning memory (pin_memory=True in DataLoader) for
       GPU training — CPU-to-GPU transfers are much slower
       without pinned memory.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
import torch.optim as optim
import numpy as np

# Detect GPU once; use this device throughout the file.
# MPS = Apple Silicon GPU (torch >= 1.12). Fallback to CPU.
device = torch.device(
    'cuda' if torch.cuda.is_available()
    else 'mps' if torch.backends.mps.is_available()
    else 'cpu'
)
print(f"Using device: {device}")

# ============================================================
# SECTION 1: Tensor Creation
# ============================================================
# Tensors are the fundamental data structure — like NumPy arrays
# but with GPU support and autograd integration.
#
# dtype matters:
#   float32 → default for model weights and inputs (GPU-optimized)
#   float16 → half-precision (AMP training, 2x memory savings)
#   bfloat16→ "brain float" (better dynamic range than float16,
#             used by TPUs and Ampere+ GPUs, common in transformers)
#   int64   → class labels, indices, long integers
#   bool    → attention masks, padding masks

# Direct creation
t1 = torch.tensor([1.0, 2.0, 3.0], dtype=torch.float32)
t2 = torch.tensor([[1, 2], [3, 4]], dtype=torch.int64)

# Shape-based creation
zeros   = torch.zeros(3, 4)            # [3,4] of 0.0
ones    = torch.ones(3, 4)             # [3,4] of 1.0
rand    = torch.rand(3, 4)             # [3,4] uniform [0, 1)
randn   = torch.randn(3, 4)            # [3,4] standard normal N(0,1)
eye     = torch.eye(3)                 # 3x3 identity matrix
arange  = torch.arange(0, 10, 2)      # [0, 2, 4, 6, 8]
linspace = torch.linspace(0, 1, 100)  # 100 evenly spaced from 0 to 1
empty   = torch.empty(3, 4)           # uninitialized (garbage values, fast)

# From NumPy (shares memory! changes to one affect the other)
arr = np.array([1.0, 2.0, 3.0])
t_from_np = torch.from_numpy(arr)     # shared memory
t_copy    = torch.tensor(arr)         # independent copy

# ============================================================
# SECTION 2: Tensor Operations and Reshaping
# ============================================================

A = torch.randn(3, 4)
B = torch.randn(4, 5)

# Element-wise ops (same shape required)
x = torch.randn(3, 4)
y = torch.randn(3, 4)
add = x + y
sub = x - y
mul = x * y      # element-wise, NOT matrix multiply
div = x / y
pow_ = x ** 2    # element-wise square

# Matrix multiplication (MOST IMPORTANT for DL)
C = torch.matmul(A, B)   # (3,4) @ (4,5) = (3,5)
C2 = A @ B               # identical, cleaner syntax

# Transpose
At = A.T                 # (3,4) → (4,3)
At2 = A.transpose(0, 1)  # explicit dimension swap

# Reshaping — CRITICAL: understand the difference:
#   .reshape(): returns a new tensor with the same data.
#               May copy memory if not contiguous. Always safe.
#   .view():    REQUIRES contiguous memory. Faster (no copy)
#               but raises RuntimeError if memory not contiguous.
#               After .permute() or .transpose(), call .contiguous() first.
t = torch.randn(2, 3, 4)
reshaped = t.reshape(2, 12)    # safe
contiguous_view = t.contiguous().view(2, 12)  # explicit

# Squeeze / unsqueeze: add or remove size-1 dimensions
t_3d = torch.randn(1, 3, 4)
t_2d = t_3d.squeeze(0)         # (1,3,4) → (3,4)
t_4d = t_2d.unsqueeze(0)       # (3,4)   → (1,3,4)

# Permute: reorder dimensions (e.g., image HWC → CHW for PyTorch)
hwc  = torch.randn(224, 224, 3)  # H, W, C (PIL/numpy format)
chw  = hwc.permute(2, 0, 1)      # C, H, W (PyTorch CNN format)

# Concatenate / stack
t1 = torch.randn(3, 4)
t2 = torch.randn(3, 4)
cat0 = torch.cat([t1, t2], dim=0)    # (6,4) — join along existing dim
stack0 = torch.stack([t1, t2], dim=0) # (2,3,4) — NEW dim at position 0

# ============================================================
# SECTION 3: GPU Operations
# ============================================================
# BOTH model AND data must be on the same device.
# Moving data between CPU and GPU has overhead — do it once,
# keep everything on GPU during the forward/backward pass.

def move_to_device(tensor, device):
    return tensor.to(device)  # .to(device) is the canonical way

# Checking memory usage (useful for debugging OOM errors):
if torch.cuda.is_available():
    allocated = torch.cuda.memory_allocated(device) / 1e9
    reserved  = torch.cuda.memory_reserved(device) / 1e9
    print(f"GPU memory allocated: {allocated:.2f} GB")
    print(f"GPU memory reserved:  {reserved:.2f} GB")

# ============================================================
# SECTION 4: Autograd — Automatic Differentiation
# ============================================================
# requires_grad=True tells PyTorch to track all operations on
# this tensor in the computation graph.
#
# How it works:
#   1. Forward pass: ops create a graph (DAG of Function nodes).
#   2. loss.backward(): traverses graph in reverse via chain rule,
#      computing d(loss)/d(param) for each parameter.
#   3. Gradients accumulate in .grad attribute.

# Example: manual gradient computation
w = torch.tensor([2.0], requires_grad=True)
x = torch.tensor([3.0])
loss = (w * x - 6.0) ** 2   # loss = (2*3 - 6)^2 = 0
loss.backward()
print(f"d(loss)/dw = {w.grad}")  # should be 0 when loss=0

# torch.no_grad(): disable gradient tracking for inference.
# 2-3x faster forward pass, much lower memory usage.
# ALWAYS wrap inference in this context manager.
with torch.no_grad():
    pred = w * x   # no graph built, no grad tracking

# .detach(): creates a tensor that shares data but has no grad.
# Useful when you want to use a tensor value as a constant
# without backpropagating through it.
y = w * x
y_detached = y.detach()   # y_detached.requires_grad = False

# ============================================================
# SECTION 5: nn.Module — Defining Models
# ============================================================
# ALL neural network components inherit from nn.Module:
#   - Layers (Linear, Conv2d, LSTM, ...)
#   - Loss functions (CrossEntropyLoss, ...)
#   - Full models you define yourself
#
# Key rule: ALWAYS call model(x), never model.forward(x).
# Calling via __call__ triggers hooks (e.g., forward hooks for
# feature extraction, gradient hooks for clipping). forward()
# bypasses all of this.

class MLP(nn.Module):
    """
    Multi-Layer Perceptron for tabular binary classification.
    Architecture: Linear → BN → ReLU → Dropout, repeated.
    """
    def __init__(self, input_dim: int, hidden_dims: list, dropout: float = 0.3):
        super().__init__()
        # Build layers programmatically
        layers = []
        prev_dim = input_dim
        for h_dim in hidden_dims:
            layers.extend([
                nn.Linear(prev_dim, h_dim),
                nn.BatchNorm1d(h_dim),   # normalize activations
                nn.ReLU(),               # non-linearity
                nn.Dropout(p=dropout),   # regularization
            ])
            prev_dim = h_dim
        layers.append(nn.Linear(prev_dim, 1))  # output logit (NOT sigmoid)
        self.network = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.network(x).squeeze(-1)  # (batch,1) → (batch,)

# ============================================================
# SECTION 6: Common Layers — Reference
# ============================================================

# nn.Linear(in_features, out_features, bias=True)
#   Fully connected: y = Wx + b
#   weight shape: (out_features, in_features)
#   bias shape:   (out_features,)
fc = nn.Linear(128, 64)

# nn.Conv2d(in_channels, out_channels, kernel_size, stride, padding)
#   2D convolution for images.
#   padding='same' preserves spatial dimensions (newer PyTorch).
#   Output spatial size: floor((H + 2*pad - kernel) / stride) + 1
conv = nn.Conv2d(in_channels=3, out_channels=64, kernel_size=3,
                 stride=1, padding=1)

# nn.BatchNorm1d/2d(num_features)
#   Normalizes activations per mini-batch: (x - mean) / std * gamma + beta.
#   TRAIN mode: uses batch mean/std, updates running stats.
#   EVAL mode: uses running mean/std (accumulated during training).
#   Reduces internal covariate shift → faster training, higher lr.
bn1d = nn.BatchNorm1d(64)   # for (batch, features)
bn2d = nn.BatchNorm2d(64)   # for (batch, channels, H, W)

# nn.Dropout(p=0.5)
#   Randomly zeros out p fraction of neurons during TRAINING.
#   At EVAL time: all neurons active, weights scaled by (1-p).
#   Regularizes by preventing co-adaptation of neurons.
drop = nn.Dropout(p=0.3)

# nn.LSTM(input_size, hidden_size, num_layers, batch_first, dropout)
#   batch_first=True: input shape (batch, seq_len, input_size)
#   output: (output, (h_n, c_n))
#   output shape: (batch, seq_len, hidden_size * (2 if bidirectional))
lstm = nn.LSTM(input_size=64, hidden_size=128, num_layers=2,
               batch_first=True, dropout=0.2, bidirectional=False)

# nn.Embedding(num_embeddings, embedding_dim, padding_idx=0)
#   Learnable lookup table: integer index → dense vector.
#   Used for categorical IDs (words, users, products).
#   padding_idx=0: that embedding vector stays zero (for padding).
emb = nn.Embedding(num_embeddings=10000, embedding_dim=128, padding_idx=0)

# ============================================================
# SECTION 7: Activation Functions
# ============================================================
# Functional API (F.relu): applied to a tensor in forward().
# Module API (nn.ReLU): stored as a layer, appears in model summary.
# Use nn.* when you want it in nn.Sequential or model.named_modules().

# ReLU: max(0, x). Simple, standard. Dead neuron problem (x<0 → 0 gradient).
# GELU: Gaussian Error Linear Unit. ReLU-like but smooth.
#   Standard for transformers (BERT, GPT). Slightly better than ReLU on NLP.
# Sigmoid: (0,1) output. Use in final layer for binary classification
#   but NOT as hidden activation (vanishing gradients).
# Softmax: probability distribution over classes. Applied in final
#   layer for multiclass — but CrossEntropyLoss includes log_softmax,
#   so output raw logits and let CEL handle it.

x_act = torch.randn(32, 64)
relu_out  = F.relu(x_act)
gelu_out  = F.gelu(x_act)
tanh_out  = F.tanh(x_act)
sigmoid_out = torch.sigmoid(x_act)         # F.sigmoid deprecated, use this
softmax_out = F.softmax(x_act, dim=-1)     # sum to 1 along last dim

# ============================================================
# SECTION 8: Loss Functions
# ============================================================
# CRITICAL DETAILS:
#
# CrossEntropyLoss():
#   - For multiclass classification.
#   - INCLUDES log_softmax internally. Pass LOGITS, not probs.
#   - y target: class INDICES (torch.long), NOT one-hot vectors.
#   - Combines: NLLLoss(log_softmax(input), target)
#
# BCEWithLogitsLoss():
#   - For binary classification.
#   - INCLUDES sigmoid internally. Pass LOGITS, not probs.
#   - Numerically more stable than BCE(sigmoid(x), y).
#   - pos_weight: upweight positive class for imbalance.
#
# MSELoss() / L1Loss():
#   - For regression. L1 (MAE) is more robust to outliers.
#
# NLLLoss():
#   - Expects LOG-probabilities (apply log_softmax yourself).
#   - Rarely used directly; prefer CrossEntropyLoss.

ce_loss    = nn.CrossEntropyLoss()            # multiclass
bce_loss   = nn.BCEWithLogitsLoss(            # binary
    pos_weight=torch.tensor([5.0])            # upweight positive class 5x
)
mse_loss   = nn.MSELoss()                     # regression, L2
mae_loss   = nn.L1Loss()                      # regression, L1 (robust)

# ============================================================
# SECTION 9: Optimizers
# ============================================================
# SGD: stochastic gradient descent. Fast per step, noisy.
#   momentum=0.9: exponentially weighted average of gradients.
#   weight_decay: L2 regularization on weights.
#   Requires careful LR tuning but can generalize better than Adam
#   in some computer vision settings.
#
# Adam: adaptive learning rates per parameter. Maintains running
#   average of gradient (m) and squared gradient (v).
#   Fast convergence, works well out of the box.
#   weight_decay in Adam is COUPLED to the adaptive LR → incorrect
#   regularization. Use AdamW to decouple.
#
# AdamW: Adam with DECOUPLED weight decay.
#   Standard choice for transformers and most modern architectures.
#   Default: lr=1e-4, weight_decay=0.01.
#
# weight_decay: L2 penalty on weights. Prevents large weights.
#   Conceptually equivalent to Ridge regression.

def build_optimizer(model: nn.Module, opt_name: str = 'adamw'):
    if opt_name == 'sgd':
        return optim.SGD(
            model.parameters(),
            lr=0.01,
            momentum=0.9,
            weight_decay=1e-4,
            nesterov=True,   # look-ahead momentum, slightly better
        )
    elif opt_name == 'adam':
        return optim.Adam(
            model.parameters(),
            lr=1e-3,
            betas=(0.9, 0.999),  # running avg coefficients
            weight_decay=0.0,    # Adam's weight_decay is incorrect; use AdamW
        )
    else:  # 'adamw' — preferred
        return optim.AdamW(
            model.parameters(),
            lr=1e-4,
            betas=(0.9, 0.999),
            weight_decay=0.01,   # properly decoupled L2 reg
        )

# ============================================================
# SECTION 10: The Training Loop — 4 Steps
# ============================================================
# These 4 steps must happen IN ORDER every training iteration.
# Memorize them. Every DL bug traces back to one being wrong.
#
# 1. optimizer.zero_grad()
#    PyTorch ACCUMULATES gradients by default (grad +=).
#    Without zeroing, previous batch's gradients corrupt this batch.
#    Exception: gradient accumulation (deliberate, for large batches).
#
# 2. output = model(X)
#    Forward pass: compute predictions and build computation graph.
#
# 3. loss = criterion(output, y); loss.backward()
#    Compute scalar loss. Backprop: compute d(loss)/d(param) for all
#    parameters via automatic differentiation.
#
# 4. optimizer.step()
#    Update weights: param -= lr * param.grad (with optimizer tricks).

def train_one_epoch(model, loader, criterion, optimizer, device):
    """Train for one epoch. Returns average training loss."""
    model.train()   # enable Dropout + use batch stats for BN
    total_loss = 0.0
    n_batches = 0

    for X_batch, y_batch in loader:
        # Move data to same device as model
        X_batch = X_batch.to(device, non_blocking=True)  # non_blocking with pin_memory
        y_batch = y_batch.to(device, non_blocking=True)

        # Step 1: clear old gradients
        optimizer.zero_grad()

        # Step 2: forward pass
        output = model(X_batch)

        # Step 3: compute loss and backpropagate
        loss = criterion(output, y_batch)
        loss.backward()

        # Optional: gradient clipping (prevents gradient explosion in RNNs)
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)

        # Step 4: update weights
        optimizer.step()

        total_loss += loss.item()
        n_batches += 1

    return total_loss / n_batches


@torch.no_grad()  # decorator equivalent to: with torch.no_grad()
def evaluate(model, loader, criterion, device):
    """Evaluate on validation/test set. No gradients needed."""
    model.eval()   # disable Dropout + use running stats for BN
    total_loss = 0.0
    all_preds = []
    all_targets = []

    for X_batch, y_batch in loader:
        X_batch = X_batch.to(device, non_blocking=True)
        y_batch = y_batch.to(device, non_blocking=True)

        output = model(X_batch)
        loss = criterion(output, y_batch)

        total_loss += loss.item()
        # Detach + move to CPU before extending list (avoids GPU memory leak)
        all_preds.extend(torch.sigmoid(output).cpu().numpy())
        all_targets.extend(y_batch.cpu().numpy())

    return total_loss / len(loader), np.array(all_preds), np.array(all_targets)

# ============================================================
# SECTION 11: Dataset and DataLoader
# ============================================================
# Dataset: wraps your data and defines how to access one sample.
# DataLoader: batches samples, shuffles, and loads in parallel.
#
# __len__: total number of samples (used by DataLoader to plan batches)
# __getitem__: returns ONE (input, target) pair given an index
#
# DataLoader options:
#   batch_size: samples per batch
#   shuffle=True: randomize order each epoch (training only!)
#   num_workers: parallel processes for loading (0 = main thread)
#     4-8 is typical for SSDs; too many → CPU bottleneck
#   pin_memory=True: allocate CPU tensors in pinned memory.
#     Dramatically speeds up CPU→GPU transfer. Use with CUDA only.
#   drop_last=True: drop final incomplete batch (avoids BN issues
#     with batch_size=1 in the last batch).

class TabularDataset(Dataset):
    """Dataset for tabular (numpy array) data."""
    def __init__(self, X: np.ndarray, y: np.ndarray):
        # Convert to float32 once here — not on every __getitem__ call
        self.X = torch.tensor(X, dtype=torch.float32)
        self.y = torch.tensor(y, dtype=torch.float32)  # float for BCE

    def __len__(self) -> int:
        return len(self.X)

    def __getitem__(self, idx: int):
        return self.X[idx], self.y[idx]


def build_loaders(X_train, y_train, X_val, y_val, batch_size=64):
    train_ds = TabularDataset(X_train, y_train)
    val_ds   = TabularDataset(X_val, y_val)

    train_loader = DataLoader(
        train_ds,
        batch_size=batch_size,
        shuffle=True,
        num_workers=4,
        pin_memory=(device.type == 'cuda'),
        drop_last=True,
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=batch_size * 2,  # val can use larger batch (no gradients)
        shuffle=False,
        num_workers=4,
        pin_memory=(device.type == 'cuda'),
    )
    return train_loader, val_loader

# ============================================================
# SECTION 12: Learning Rate Schedulers
# ============================================================
# LR scheduler adjusts the learning rate during training.
# Call scheduler.step() AFTER optimizer.step() each epoch.
#
# StepLR: reduce LR by gamma every step_size epochs.
#   Simple, predictable. 10x reduction every 10 epochs.
#
# CosineAnnealingLR: smoothly decay from initial LR to eta_min
#   following a cosine curve. No sharp drops. T_max = total epochs.
#
# OneCycleLR: warmup (linear increase) then cosine decay.
#   num_steps = n_epochs * steps_per_epoch.
#   Often gives best results with AdamW. Designed for "super-convergence".

def build_scheduler(optimizer, scheduler_name, n_epochs, steps_per_epoch=None):
    if scheduler_name == 'step':
        return optim.lr_scheduler.StepLR(
            optimizer, step_size=10, gamma=0.1,
        )
    elif scheduler_name == 'cosine':
        return optim.lr_scheduler.CosineAnnealingLR(
            optimizer, T_max=n_epochs, eta_min=1e-6,
        )
    elif scheduler_name == 'onecycle':
        assert steps_per_epoch is not None
        return optim.lr_scheduler.OneCycleLR(
            optimizer,
            max_lr=1e-3,                        # peak LR during warmup
            total_steps=n_epochs * steps_per_epoch,
            pct_start=0.3,                       # 30% of training = warmup
            anneal_strategy='cos',
        )
    raise ValueError(f"Unknown scheduler: {scheduler_name}")

# ============================================================
# SECTION 13: Saving and Loading
# ============================================================
# Best practice: save STATE_DICT, not the full model.
# Full model save uses pickle and is sensitive to class/file
# structure changes. state_dict is just the weight tensors.
#
# For checkpointing: also save optimizer state (resumes correctly
# from mid-training), epoch, and best validation metric.

def save_checkpoint(model, optimizer, epoch, val_loss, path):
    torch.save({
        'epoch': epoch,
        'model_state_dict': model.state_dict(),
        'optimizer_state_dict': optimizer.state_dict(),
        'val_loss': val_loss,
    }, path)

def load_checkpoint(model, optimizer, path, device):
    checkpoint = torch.load(path, map_location=device)
    model.load_state_dict(checkpoint['model_state_dict'])
    if optimizer is not None:
        optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
    return checkpoint['epoch'], checkpoint['val_loss']

# Inference only — no optimizer needed:
def load_model_for_inference(model_class, model_kwargs, path, device):
    model = model_class(**model_kwargs).to(device)
    state = torch.load(path, map_location=device)
    model.load_state_dict(state['model_state_dict'])
    model.eval()   # CRITICAL: set eval mode before any inference
    return model

# ============================================================
# SECTION 14: model.train() vs model.eval()
# ============================================================
# This is one of the most common sources of bugs in PyTorch.
#
# model.train():
#   - Dropout: randomly zeroes p fraction of activations.
#   - BatchNorm: uses BATCH mean/std, updates running stats.
#   - Use during: training loop.
#
# model.eval():
#   - Dropout: ALL neurons active (no dropout).
#   - BatchNorm: uses RUNNING mean/std (accumulated from training).
#   - Use during: validation, testing, and serving.
#
# model.training (bool attribute): tells you current mode.

# ============================================================
# SECTION 15: Complete Binary Classifier Training
# ============================================================

def train_binary_classifier(X_train, y_train, X_val, y_val,
                             input_dim: int, n_epochs: int = 50):
    """
    Full training pipeline for binary classification on tabular data.
    Returns best model (by validation loss).
    """
    train_loader, val_loader = build_loaders(X_train, y_train, X_val, y_val)

    model = MLP(
        input_dim=input_dim,
        hidden_dims=[256, 128, 64],
        dropout=0.3,
    ).to(device)

    pos_rate = y_train.mean()
    pos_weight = torch.tensor([(1 - pos_rate) / pos_rate]).to(device)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

    optimizer = optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0.01)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=n_epochs, eta_min=1e-6,
    )

    best_val_loss = float('inf')
    patience = 10
    patience_counter = 0

    for epoch in range(n_epochs):
        train_loss = train_one_epoch(model, train_loader, criterion, optimizer, device)
        val_loss, val_preds, val_targets = evaluate(model, val_loader, criterion, device)
        scheduler.step()

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience_counter = 0
            save_checkpoint(model, optimizer, epoch, val_loss, 'best_model.pt')
        else:
            patience_counter += 1

        if epoch % 5 == 0:
            lr = optimizer.param_groups[0]['lr']
            print(f"Epoch {epoch:3d} | train_loss={train_loss:.4f} "
                  f"val_loss={val_loss:.4f} | lr={lr:.2e}")

        if patience_counter >= patience:
            print(f"Early stopping at epoch {epoch}")
            break

    # Load best model weights
    load_checkpoint(model, None, 'best_model.pt', device)
    return model


# Inference:
# model.eval()
# with torch.no_grad():
#     logits = model(X_new.to(device))
#     probs = torch.sigmoid(logits)
#     preds = (probs > 0.5).long()

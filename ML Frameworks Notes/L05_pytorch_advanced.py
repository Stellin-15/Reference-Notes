# ============================================================
# L05: Advanced PyTorch — Training Infrastructure
# ============================================================
# WHAT: Deep dive into PyTorch's advanced training primitives:
#       custom datasets, mixed precision, multi-GPU (DDP),
#       gradient management, LR scheduling, checkpointing,
#       profiling, and memory optimization.
# WHY:  Knowing nn.Linear and backward() is not enough for
#       real workloads. Production training requires 2x-10x
#       GPU utilization, fault tolerance (checkpointing),
#       multi-GPU scaling, and numerical stability tricks.
#       These patterns are the difference between a research
#       prototype and a model that actually ships.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    PyTorch exposes every knob in the training loop, which is
    a double-edged sword. You can micro-optimize everything,
    but you also have to know *what* to optimize and *why*.
    This file covers the canonical patterns used in production
    training pipelines: efficient data loading, mixed-precision
    AMP, DistributedDataParallel, gradient accumulation, LR
    schedules, checkpointing, and GPU memory tricks.

PRODUCTION USE CASE:
    - Training a large vision model (ResNet-50, ViT) across
      8x A100 GPUs with DDP, mixed precision, and gradient
      clipping. Wall-clock time drops from ~6h to ~45min.
    - Fine-tuning a transformer (BERT, LLaMA) on limited GPU
      memory using gradient checkpointing + accumulation.
    - Long training runs where checkpointing every N steps
      is the difference between recoverable and lost work.

COMMON MISTAKES:
    1. Calling optimizer.step() inside the accumulation loop
       (gradients not fully accumulated yet).
    2. Forgetting scaler.update() in AMP, causing the scaler
       to never adapt and training to diverge in float16.
    3. Using nn.DataParallel instead of DDP — DataParallel
       has a GIL bottleneck and does gradient sync on CPU.
    4. Not using DistributedSampler with DDP — each GPU sees
       the same data, doubling effective batch size silently.
    5. Saving the DDP-wrapped model directly (saves with
       'module.' prefix keys) — always save model.module.state_dict().
    6. Gradient clipping before scaler.unscale_() in AMP —
       you end up clipping scaled (inflated) gradients, not
       the true ones.
"""

import os
import time
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader, DistributedSampler
from torch.cuda.amp import autocast, GradScaler
from torch.nn.utils.rnn import pad_sequence
import torch.distributed as dist
import torch.multiprocessing as mp
from torch.nn.parallel import DistributedDataParallel as DDP
from torch.optim.lr_scheduler import CosineAnnealingLR, LinearLR, SequentialLR
import torch.profiler

# ============================================================
# SECTION 1: CUSTOM DATASET AND DATALOADER
# ============================================================
# WHAT: torch.utils.data.Dataset is the abstract base class.
#       Subclass it and implement __len__ + __getitem__.
#       DataLoader wraps a Dataset to provide batching,
#       shuffling, multiprocessing, and pinned memory.
# WHY:  Most real datasets don't fit in RAM and require
#       lazy loading from disk. The DataLoader's num_workers
#       forks processes that load data in parallel so the GPU
#       never waits idle for the next batch.

class VariableLengthDataset(Dataset):
    """
    Simulates a text/sequence dataset where samples have
    different lengths — the common case in NLP.
    """
    def __init__(self, num_samples: int = 1000, vocab_size: int = 256):
        self.num_samples = num_samples
        self.vocab_size = vocab_size
        # Pre-generate random sequences of varying lengths.
        # In production: store file paths here, load in __getitem__.
        torch.manual_seed(42)
        self.lengths = torch.randint(10, 100, (num_samples,))
        self.data = [
            torch.randint(0, vocab_size, (length.item(),))
            for length in self.lengths
        ]
        self.labels = torch.randint(0, 2, (num_samples,))  # binary labels

    def __len__(self) -> int:
        # DataLoader calls this to know how many samples exist.
        return self.num_samples

    def __getitem__(self, idx: int):
        # Called by DataLoader worker processes for each index.
        # Keep this lightweight — heavy computation blocks workers.
        # Return raw tensors; collate_fn handles batching.
        return self.data[idx], self.labels[idx]


def variable_length_collate_fn(batch):
    """
    WHAT: Custom collate_fn for batching variable-length sequences.
    WHY:  Default collate_fn calls torch.stack(), which requires
          all tensors to have the same shape. For sequences of
          different lengths, we must pad to the longest in the batch.

    The collate_fn runs in the DataLoader worker process and
    receives a list of (sequence, label) tuples — one per sample
    selected in this batch.
    """
    sequences, labels = zip(*batch)  # unzip list of (seq, label) pairs

    # pad_sequence pads all tensors to the length of the longest one.
    # batch_first=True → output shape: (batch, max_len)
    # padding_value=0 → use 0 as the PAD token index
    padded_sequences = pad_sequence(
        sequences, batch_first=True, padding_value=0
    )

    # Stack labels — they're all scalars so this is straightforward.
    labels = torch.stack(labels)

    # Also return the original lengths — needed by LSTM's
    # pack_padded_sequence to ignore padding during computation.
    lengths = torch.tensor([len(s) for s in sequences])

    return padded_sequences, labels, lengths


def build_dataloader(dataset: Dataset, batch_size: int = 32,
                     num_workers: int = 4, distributed: bool = False):
    """
    WHAT: Construct a production-ready DataLoader.
    WHY:  Each parameter has a performance reason:
          - num_workers: parallel data loading processes.
            Rule of thumb: 4 per GPU, max = num CPU cores.
          - pin_memory=True: allocates batches in page-locked
            (pinned) host memory → faster CPU→GPU transfer.
            Only enable when training on GPU.
          - prefetch_factor: each worker pre-fetches this many
            batches ahead of what the model needs.
          - persistent_workers: keep worker processes alive
            between epochs (avoids fork overhead each epoch).
    """
    sampler = None
    if distributed:
        # DistributedSampler partitions the dataset across ranks.
        # Each GPU process only sees 1/world_size of the data.
        # shuffle=True randomizes the partition each epoch.
        sampler = DistributedSampler(dataset, shuffle=True)

    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=(sampler is None),   # don't shuffle if sampler handles it
        sampler=sampler,
        num_workers=num_workers,
        pin_memory=torch.cuda.is_available(),
        collate_fn=variable_length_collate_fn,
        prefetch_factor=2,           # workers buffer 2 batches ahead
        persistent_workers=(num_workers > 0),
        drop_last=True,              # drop last incomplete batch (avoids
    )                                # batch-norm issues with batch_size=1


# ============================================================
# SECTION 2: CUSTOM LOSS FUNCTIONS
# ============================================================
# WHAT: Subclass nn.Module and implement forward().
#       Loss functions are just modules — they have learnable
#       parameters if needed (though most losses don't).
# WHY:  CrossEntropyLoss assumes balanced classes. Focal loss
#       and weighted losses handle class imbalance — critical
#       in fraud detection, medical imaging, rare event detection.

class FocalLoss(nn.Module):
    """
    WHAT: Focal Loss (Lin et al. 2017, RetinaNet paper).
    WHY:  In class-imbalanced datasets, standard cross-entropy
          is dominated by the easy majority class. Focal loss
          down-weights well-classified examples by factor
          (1 - pt)^gamma, forcing the model to focus on hard,
          misclassified examples.
          gamma=0 → standard cross-entropy.
          gamma=2 → typical choice for detection tasks.
          alpha → per-class weight (separate from gamma).
    """
    def __init__(self, gamma: float = 2.0, alpha: float = 0.25,
                 reduction: str = 'mean'):
        super().__init__()
        self.gamma = gamma
        self.alpha = alpha
        self.reduction = reduction

    def forward(self, logits: torch.Tensor, targets: torch.Tensor):
        # logits: (N, C) — raw scores, not probabilities
        # targets: (N,) — integer class indices

        # Standard cross-entropy loss, unreduced (one value per sample).
        ce_loss = nn.functional.cross_entropy(
            logits, targets, reduction='none'
        )

        # Convert CE loss back to probabilities of the true class.
        # pt = exp(-CE) = probability assigned to the correct class.
        pt = torch.exp(-ce_loss)

        # Focal weight: suppress easy examples (high pt), amplify hard ones.
        focal_weight = self.alpha * (1 - pt) ** self.gamma

        focal_loss = focal_weight * ce_loss

        if self.reduction == 'mean':
            return focal_loss.mean()
        elif self.reduction == 'sum':
            return focal_loss.sum()
        return focal_loss  # 'none' — return per-sample losses


class CombinedLoss(nn.Module):
    """
    WHAT: Weighted combination of multiple loss terms.
    WHY:  Multi-task learning (e.g., classification + bounding box
          regression) or adding auxiliary losses (e.g., center loss +
          cross-entropy for face recognition).
    """
    def __init__(self, ce_weight: float = 1.0, focal_weight: float = 0.5):
        super().__init__()
        self.ce_weight = ce_weight
        self.focal_weight = focal_weight
        self.ce_loss = nn.CrossEntropyLoss()
        self.focal_loss = FocalLoss(gamma=2.0)

    def forward(self, logits, targets):
        ce = self.ce_loss(logits, targets)
        focal = self.focal_loss(logits, targets)
        # Weighted sum — tune weights on validation set.
        return self.ce_weight * ce + self.focal_weight * focal


# ============================================================
# SECTION 3: MODEL DEFINITION (Simple classifier for examples)
# ============================================================

class SimpleClassifier(nn.Module):
    """Minimal model used throughout the training examples below."""
    def __init__(self, input_dim: int = 128, hidden_dim: int = 256,
                 num_classes: int = 10):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(hidden_dim, num_classes),
        )

    def forward(self, x):
        return self.net(x)


# ============================================================
# SECTION 4: MIXED PRECISION TRAINING (AMP)
# ============================================================
# WHAT: torch.cuda.amp.autocast() runs the forward pass in
#       float16 (or bfloat16). GradScaler multiplies the loss
#       by a large scale factor before backward() so that
#       tiny float16 gradients don't underflow to zero.
# WHY:  - 2x memory savings (FP32 params → FP16 activations).
#       - 2x throughput on V100/A100 (tensor cores run FP16).
#       - Loss scaling is the critical trick — without it,
#         gradients like 1e-7 underflow to 0 in FP16.
# NOTE: Weights are stored in FP32. Only the forward pass and
#       gradient accumulation happen in FP16. This is why it's
#       called "mixed" precision, not "full" FP16 training.

def train_step_amp(model, optimizer, scaler, batch, criterion, device):
    """Single training step with automatic mixed precision."""
    inputs, targets = batch
    inputs, targets = inputs.to(device), targets.to(device)

    optimizer.zero_grad()

    # autocast context: eligible ops run in float16 automatically.
    # PyTorch decides which ops are safe in FP16 (matmul, conv)
    # vs which must stay FP32 (softmax, BN running stats).
    with autocast():
        outputs = model(inputs)
        loss = criterion(outputs, targets)

    # Scale loss before backward to prevent FP16 gradient underflow.
    # scaler tracks the scale factor and adjusts it each step.
    scaler.scale(loss).backward()

    # CRITICAL ORDER for gradient clipping with AMP:
    # 1. unscale_ first — converts scaled gradients back to FP32 scale.
    # 2. clip_grad_norm_ — clips the now-correct-scale gradients.
    # 3. scaler.step() — applies gradients (skips step if NaN/Inf detected).
    # 4. scaler.update() — adjusts scale factor for next step.
    scaler.unscale_(optimizer)
    torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)

    # scaler.step() checks for inf/nan gradients. If found, skips the
    # optimizer step and reduces the scale factor. This is automatic
    # recovery from numerical instability.
    scaler.step(optimizer)
    scaler.update()

    return loss.item()


# ============================================================
# SECTION 5: GRADIENT CLIPPING
# ============================================================
# WHAT: Rescale gradients so their global L2 norm ≤ max_norm.
#       Applied after backward(), before optimizer.step().
# WHY:  In RNNs and deep transformers, gradients can explode
#       exponentially through long sequences (vanishing/exploding
#       gradient problem). Clipping prevents parameter updates
#       from blowing up weights, which would cause loss to NaN.
#       LSTMs partially solve vanishing gradients (gates), but
#       clipping is still standard practice.
# NOTE: max_norm=1.0 is the most common default. Some codebases
#       use 0.5 for RNNs or 5.0 for less sensitive models.
#       Monitor grad_norm as a metric — spikes signal instability.

def clip_gradients(model, max_norm: float = 1.0):
    """Returns the gradient norm before clipping (useful for logging)."""
    # Returns the total gradient norm (before clipping).
    # Clips in-place — modifies gradient tensors.
    grad_norm = torch.nn.utils.clip_grad_norm_(
        model.parameters(), max_norm=max_norm
    )
    return grad_norm.item()


# ============================================================
# SECTION 6: GRADIENT ACCUMULATION
# ============================================================
# WHAT: Accumulate gradients over N mini-batches before
#       calling optimizer.step(). Simulates batch_size * N.
# WHY:  Training BERT-large with batch_size=256 requires ~64GB
#       GPU memory. Gradient accumulation lets you use batch_size=8
#       on a 16GB GPU while achieving the same effective batch size
#       as batch_size=256 — just slower due to N forward passes.
# NOTE: Divide loss by accumulation_steps to keep gradient
#       magnitudes consistent regardless of accumulation_steps.
#       DDP users: disable gradient sync on non-accumulation steps
#       with model.no_sync() context for efficiency.

def train_with_gradient_accumulation(model, optimizer, dataloader,
                                      criterion, device,
                                      accumulation_steps: int = 4):
    """Training loop with gradient accumulation."""
    model.train()
    optimizer.zero_grad()  # zero at the start, not inside the loop

    for step, (inputs, targets) in enumerate(dataloader):
        inputs, targets = inputs.to(device), targets.to(device)

        outputs = model(inputs)
        # Divide by accumulation_steps so the total gradient magnitude
        # equals what we'd get from a single forward pass on the full
        # accumulated batch.
        loss = criterion(outputs, targets) / accumulation_steps

        loss.backward()  # accumulates gradients (does NOT zero_grad)

        # Only update weights every accumulation_steps steps.
        if (step + 1) % accumulation_steps == 0:
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            optimizer.zero_grad()  # reset accumulated gradients


# ============================================================
# SECTION 7: LEARNING RATE SCHEDULING
# ============================================================
# WHAT: Schedulers adjust the learning rate over training.
# WHY:  - High LR early → fast progress through loss landscape.
#       - Warmup → avoids instability in first steps (transformers
#         especially — random init + high LR = divergence).
#       - Cosine annealing → gradually refine to minimum.
#         Better final accuracy than step decay.

def build_scheduler(optimizer, num_warmup_steps: int, total_steps: int):
    """
    Linear warmup followed by cosine annealing.
    This is the standard schedule for transformer fine-tuning.
    """
    # Phase 1: LinearLR — LR increases from start_factor to 1.0
    # over num_warmup_steps steps.
    warmup_scheduler = LinearLR(
        optimizer,
        start_factor=1e-8,   # start from near-zero
        end_factor=1.0,
        total_iters=num_warmup_steps
    )

    # Phase 2: CosineAnnealingLR — LR follows cosine curve from
    # base LR down to eta_min over the remaining steps.
    cosine_scheduler = CosineAnnealingLR(
        optimizer,
        T_max=total_steps - num_warmup_steps,
        eta_min=1e-6   # minimum LR (don't go all the way to 0)
    )

    # SequentialLR chains schedulers: warmup runs for num_warmup_steps,
    # then cosine takes over for the rest of training.
    return SequentialLR(
        optimizer,
        schedulers=[warmup_scheduler, cosine_scheduler],
        milestones=[num_warmup_steps]
    )


# ============================================================
# SECTION 8: CHECKPOINTING
# ============================================================
# WHAT: Save model + optimizer + scheduler + training state to disk.
# WHY:  - Resume from crashes (cloud preemption is real).
#       - Save best model by validation metric (not just last epoch).
#       - Reproducibility — exact state at any epoch.
# NOTE: state_dict() saves parameters and buffers (running
#       mean/var in BN). Always save optimizer state too —
#       Adam has per-parameter momentum that takes epochs to warm up.

def save_checkpoint(model, optimizer, scheduler, epoch: int,
                    best_val_loss: float, path: str):
    """Save full training state to resume later."""
    # If using DDP, save model.module (unwrapped) to avoid
    # 'module.' prefix in all state_dict keys.
    model_to_save = model.module if hasattr(model, 'module') else model

    checkpoint = {
        'epoch': epoch,
        'model_state_dict': model_to_save.state_dict(),
        'optimizer_state_dict': optimizer.state_dict(),
        'scheduler_state_dict': scheduler.state_dict() if scheduler else None,
        'best_val_loss': best_val_loss,
    }
    torch.save(checkpoint, path)


def load_checkpoint(path: str, model, optimizer=None, scheduler=None,
                    device='cpu'):
    """Restore training state from checkpoint."""
    checkpoint = torch.load(path, map_location=device)
    model.load_state_dict(checkpoint['model_state_dict'])
    if optimizer and 'optimizer_state_dict' in checkpoint:
        optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
    if scheduler and checkpoint.get('scheduler_state_dict'):
        scheduler.load_state_dict(checkpoint['scheduler_state_dict'])
    return checkpoint['epoch'], checkpoint['best_val_loss']


# ============================================================
# SECTION 9: TORCH.COMPILE (PyTorch 2.0+)
# ============================================================
# WHAT: torch.compile(model) traces the model's computation
#       graph and compiles it to optimized CUDA/CPU kernels
#       using TorchInductor (backed by Triton for GPU).
# WHY:  30-200% speedup with zero code changes. Fuses ops
#       (e.g., matmul + bias + relu → single kernel), eliminates
#       Python overhead in the training loop.
# NOTE: - Requires PyTorch >= 2.0 and CUDA >= 11.7.
#       - First call is slow (compilation overhead, ~minutes).
#       - mode='reduce-overhead' → minimize kernel launch overhead.
#       - mode='max-autotune' → exhaustive tuning, best throughput.
#       - fullgraph=True → error if graph breaks (not all ops supported).
#       - Dynamic shapes (variable batch sizes) need dynamic=True.

def compile_model_if_available(model):
    """Compile model for speedup if torch.compile is available."""
    if hasattr(torch, 'compile'):
        # reduce-overhead is the safe default; use max-autotune
        # for long training runs where compilation time pays off.
        return torch.compile(model, mode='reduce-overhead')
    return model  # fallback for PyTorch < 2.0


# ============================================================
# SECTION 10: DISTRIBUTED DATA PARALLEL (DDP)
# ============================================================
# WHAT: Each GPU process runs a full copy of the model and
#       handles a partition of the data. Gradients are
#       all-reduced across GPUs via NCCL after each backward().
# WHY:  DataParallel has a primary GPU bottleneck — it gathers
#       all gradients to GPU:0, computes updates, then broadcasts.
#       DDP has no primary GPU — all-reduce is peer-to-peer and
#       overlaps with backward computation (bucketed all-reduce).
#       DDP scales linearly with GPU count; DataParallel does not.
# NCCL: NVIDIA Collective Communications Library — the backend
#       used for multi-GPU gradient synchronization. Uses NVLink
#       or PCIe depending on hardware.

def setup_ddp(rank: int, world_size: int):
    """
    Initialize the distributed process group.
    rank: this process's unique ID (0 to world_size-1).
    world_size: total number of GPU processes.
    """
    # MASTER_ADDR/PORT: GPU 0 acts as the rendezvous point where
    # all processes meet to initialize the process group.
    os.environ['MASTER_ADDR'] = 'localhost'
    os.environ['MASTER_PORT'] = '12355'

    # 'nccl' is the backend for NVIDIA GPUs (uses NVLink / PCIe).
    # 'gloo' for CPU or Windows (slower but portable).
    dist.init_process_group(
        backend='nccl',
        rank=rank,
        world_size=world_size
    )
    # Bind this process to its assigned GPU.
    torch.cuda.set_device(rank)


def cleanup_ddp():
    dist.destroy_process_group()


def ddp_training_process(rank: int, world_size: int):
    """
    Full DDP training loop — one process per GPU.
    Launched by torchrun or mp.spawn().
    """
    setup_ddp(rank, world_size)
    device = torch.device(f'cuda:{rank}')

    # Build model and move to this process's GPU.
    model = SimpleClassifier(input_dim=128, num_classes=10).to(device)

    # DDP wraps the model. It hooks into backward() to launch
    # gradient all-reduce automatically. device_ids=[rank] tells
    # DDP which GPU this process owns.
    model = DDP(model, device_ids=[rank])

    # Optionally compile after wrapping with DDP.
    # model = torch.compile(model, mode='reduce-overhead')

    optimizer = optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    criterion = nn.CrossEntropyLoss()
    scaler = GradScaler()

    # Synthetic dataset — replace with real dataset in production.
    dataset = torch.utils.data.TensorDataset(
        torch.randn(1000, 128), torch.randint(0, 10, (1000,))
    )

    # DistributedSampler: partitions dataset across world_size processes.
    # Each epoch, call sampler.set_epoch(epoch) to re-shuffle.
    sampler = DistributedSampler(dataset, num_replicas=world_size, rank=rank)
    dataloader = DataLoader(dataset, batch_size=32, sampler=sampler,
                            pin_memory=True)

    scheduler = build_scheduler(optimizer, num_warmup_steps=50, total_steps=500)
    best_val_loss = float('inf')

    for epoch in range(10):
        # CRITICAL: set_epoch shuffles data differently each epoch.
        # Without this, all epochs see the same order.
        sampler.set_epoch(epoch)
        model.train()

        for step, (inputs, targets) in enumerate(dataloader):
            inputs, targets = inputs.to(device), targets.to(device)

            optimizer.zero_grad()
            with autocast():
                outputs = model(inputs)
                loss = criterion(outputs, targets)

            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()

        # Only rank 0 saves checkpoints (all ranks have identical weights).
        if rank == 0 and loss.item() < best_val_loss:
            best_val_loss = loss.item()
            save_checkpoint(model, optimizer, scheduler, epoch,
                            best_val_loss, 'best_checkpoint.pt')

    cleanup_ddp()


# ============================================================
# SECTION 11: MEMORY OPTIMIZATION — GRADIENT CHECKPOINTING
# ============================================================
# WHAT: torch.utils.checkpoint.checkpoint() recomputes
#       intermediate activations during backward() instead of
#       storing them all in memory during forward().
# WHY:  A standard transformer stores all layer activations for
#       backprop — O(num_layers * seq_len * d_model) memory.
#       Gradient checkpointing stores only activations at
#       "checkpoint" boundaries and recomputes the rest.
#       Memory: O(sqrt(num_layers)) instead of O(num_layers).
#       Cost: ~33% extra compute (one extra forward pass).
# WHEN: Essential for large models on limited GPU memory.
#       GPT-3 / LLaMA training would be impossible without it.

from torch.utils.checkpoint import checkpoint as gradient_checkpoint

class CheckpointedBlock(nn.Module):
    """Example: applying gradient checkpointing to a transformer block."""
    def __init__(self, d_model: int = 512):
        super().__init__()
        self.layer = nn.Sequential(
            nn.Linear(d_model, d_model * 4),
            nn.GELU(),
            nn.Linear(d_model * 4, d_model),
        )

    def forward(self, x):
        # gradient_checkpoint trades compute for memory.
        # use_reentrant=False is the modern recommended API.
        return gradient_checkpoint(self.layer, x, use_reentrant=False)


# ============================================================
# SECTION 12: PROFILING
# ============================================================
# WHAT: torch.profiler traces CPU and CUDA operations with
#       timing and memory information.
# WHY:  You cannot optimize what you cannot measure. The profiler
#       reveals: is training bottlenecked by data loading? By
#       memory copies? By a specific operator? By GPU utilization?
#       Common finding: data loading (CPU) starves the GPU because
#       num_workers is too low.

def profile_training(model, dataloader, criterion, device):
    """Profile one training epoch to find performance bottlenecks."""
    model.train()
    optimizer = optim.Adam(model.parameters(), lr=1e-3)

    with torch.profiler.profile(
        activities=[
            torch.profiler.ProfilerActivity.CPU,
            torch.profiler.ProfilerActivity.CUDA,
        ],
        # Schedule: skip 1 warmup step, then profile 3 steps,
        # then repeat. This avoids profiling slow first steps.
        schedule=torch.profiler.schedule(wait=1, warmup=1, active=3, repeat=2),
        # Export trace for TensorBoard or chrome://tracing.
        on_trace_ready=torch.profiler.tensorboard_trace_handler('./profiler_logs'),
        record_shapes=True,    # log tensor shapes
        profile_memory=True,   # track GPU memory allocation
        with_stack=True,       # include Python stack traces
    ) as prof:
        for step, (inputs, targets) in enumerate(dataloader):
            if step >= 10:  # profile only first 10 steps
                break
            inputs, targets = inputs.to(device), targets.to(device)
            optimizer.zero_grad()
            loss = criterion(model(inputs), targets)
            loss.backward()
            optimizer.step()
            prof.step()  # advance profiler schedule

    # Print top 10 time-consuming operations.
    print(prof.key_averages().table(sort_by='cuda_time_total', row_limit=10))


# ============================================================
# SECTION 13: PUTTING IT ALL TOGETHER — LAUNCHER
# ============================================================
# torchrun is the modern launcher (replaces torch.distributed.launch).
# Usage: torchrun --nproc_per_node=4 L05_pytorch_advanced.py
# It sets LOCAL_RANK, RANK, WORLD_SIZE env vars automatically.
# Each process calls the main training function independently.

if __name__ == '__main__':
    # Single-GPU training example (for development/testing).
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    model = SimpleClassifier(input_dim=128, num_classes=10).to(device)
    model = compile_model_if_available(model)

    criterion = CombinedLoss(ce_weight=1.0, focal_weight=0.5)
    optimizer = optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    scaler = GradScaler(enabled=torch.cuda.is_available())

    # Synthetic data — replace with VariableLengthDataset or real data.
    dataset = torch.utils.data.TensorDataset(
        torch.randn(512, 128), torch.randint(0, 10, (512,))
    )
    dataloader = DataLoader(dataset, batch_size=32, shuffle=True,
                            pin_memory=torch.cuda.is_available())

    scheduler = build_scheduler(optimizer, num_warmup_steps=20, total_steps=200)
    best_val_loss = float('inf')

    for epoch in range(5):
        model.train()
        for inputs, targets in dataloader:
            loss_val = train_step_amp(
                model, optimizer, scaler,
                (inputs, targets), criterion, device
            )
        scheduler.step()
        print(f"Epoch {epoch + 1} | Loss: {loss_val:.4f} | "
              f"LR: {scheduler.get_last_lr()[0]:.2e}")

    # Save final checkpoint.
    save_checkpoint(model, optimizer, scheduler, epoch=4,
                    best_val_loss=best_val_loss, path='final_checkpoint.pt')
    print("Training complete. Checkpoint saved.")

    # Multi-GPU: uncomment below and run with torchrun.
    # world_size = torch.cuda.device_count()
    # mp.spawn(ddp_training_process, args=(world_size,), nprocs=world_size)

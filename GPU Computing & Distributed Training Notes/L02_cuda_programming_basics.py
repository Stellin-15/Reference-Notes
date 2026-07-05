# ============================================================
# L02: CUDA Programming Basics — Writing General-Purpose GPU Kernels
# ============================================================
# WHAT: Writing, launching, and managing memory for basic CUDA kernels —
#       broader in scope than this repo's LLM Quantization Notes L19,
#       which focused narrowly on kernels for dequantize-matmul; this
#       lesson covers the general CUDA programming model itself.
# WHY: Every higher-level tool in this domain (cuDNN, DeepSpeed, PyTorch
#      itself) is built ON TOP of raw CUDA — understanding the actual
#      programming model beneath them is what lets you debug performance
#      issues, understand library documentation, and eventually write
#      custom kernels when a library doesn't provide what you need.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
A CUDA PROGRAM has two parts: HOST code (runs on the CPU, orchestrates
everything) and DEVICE code (runs on the GPU — the actual KERNELS).
Memory must be EXPLICITLY managed across the HOST/DEVICE boundary: data
starts in host (CPU) memory, must be COPIED to device (GPU) memory
before a kernel can operate on it, and results must be copied BACK to
host memory to be used by CPU code afterward — this explicit memory
management (unlike a CPU program, where memory is uniformly addressable)
is one of the most common sources of both bugs and performance problems
in early CUDA code.

A KERNEL LAUNCH specifies a GRID DIMENSION (how many thread blocks) and
a BLOCK DIMENSION (how many threads per block) — together determining
the TOTAL number of threads that will execute the kernel, each with a
unique combination of `blockIdx` and `threadIdx` letting it compute
which piece of data it's responsible for. Getting this INDEXING right
(mapping a thread's ID to the correct memory location) is the most
common source of off-by-one and out-of-bounds bugs in CUDA code — the
BOUNDS CHECK pattern (verify computed index is within the actual data
size before accessing it) is essentially mandatory in real kernels,
since grid/block dimensions are often rounded UP to convenient sizes,
producing more threads than there is actual data for.

STREAMS let you OVERLAP operations — by default, all CUDA operations on
a given device execute in one implicit stream, SEQUENTIALLY. Using
MULTIPLE explicit streams lets you overlap a memory COPY (host-to-device
or device-to-host) with KERNEL EXECUTION, hiding some of the copy
latency behind useful compute — a real, meaningful optimization for
workloads that would otherwise waste time waiting for data transfer
before/after every kernel launch.

PRODUCTION USE CASE:
A custom CUDA kernel for a specialized data-preprocessing step (not
covered by any existing PyTorch/cuDNN operation) processes a large batch
of sensor data — using multiple CUDA streams to overlap the transfer of
the NEXT batch's data from host to device with the CURRENT batch's
kernel execution, hiding transfer latency almost entirely behind
compute time that would otherwise be pure overhead.

COMMON MISTAKES:
- Forgetting to copy data BACK from device to host memory after a
  kernel completes, then reading STALE host-memory values — a subtle
  bug since the code "runs" without error, it just silently operates on
  old data.
- Not bounds-checking a thread's computed index against the actual data
  size — since grid/block dimensions are often rounded up to convenient
  powers of two or block-size multiples, more threads are launched than
  there is real data, and unbounded threads reading/writing out of
  bounds is undefined behavior, not a clean crash.
- Performing MANY small, separate host-to-device memory copies instead
  of batching data into fewer, larger transfers — the fixed overhead
  per `cudaMemcpy` call means many small transfers are significantly
  less efficient than one large one for the same total data volume.
"""

import textwrap


# ------------------------------------------------------------------
# 1. A minimal, complete CUDA program — host and device code together
# ------------------------------------------------------------------
FULL_CUDA_PROGRAM_EXAMPLE = textwrap.dedent("""\
    #include <cuda_runtime.h>

    // DEVICE code — runs on the GPU, one instance per thread
    __global__ void vector_add(const float* a, const float* b, float* out, int n) {
        int idx = blockIdx.x * blockDim.x + threadIdx.x;
        if (idx < n) {   // MANDATORY bounds check — grid size is often
                          // rounded up beyond the actual data size
            out[idx] = a[idx] + b[idx];
        }
    }

    // HOST code — runs on the CPU, orchestrates memory and kernel launches
    int main() {
        int n = 1000000;
        size_t bytes = n * sizeof(float);

        // Allocate HOST memory
        float *h_a = (float*)malloc(bytes);
        float *h_b = (float*)malloc(bytes);
        float *h_out = (float*)malloc(bytes);
        // ... fill h_a, h_b with data ...

        // Allocate DEVICE memory
        float *d_a, *d_b, *d_out;
        cudaMalloc(&d_a, bytes);
        cudaMalloc(&d_b, bytes);
        cudaMalloc(&d_out, bytes);

        // Copy HOST -> DEVICE (explicit, required before the kernel can use this data)
        cudaMemcpy(d_a, h_a, bytes, cudaMemcpyHostToDevice);
        cudaMemcpy(d_b, h_b, bytes, cudaMemcpyHostToDevice);

        // Launch the kernel: grid/block dimensions determine total thread count
        int threads_per_block = 256;
        int blocks = (n + threads_per_block - 1) / threads_per_block;  // round UP
        vector_add<<<blocks, threads_per_block>>>(d_a, d_b, d_out, n);

        // Copy DEVICE -> HOST — results are USELESS until copied back
        cudaMemcpy(h_out, d_out, bytes, cudaMemcpyDeviceToHost);

        cudaFree(d_a); cudaFree(d_b); cudaFree(d_out);
        free(h_a); free(h_b); free(h_out);
        return 0;
    }
""")

# ------------------------------------------------------------------
# 2. Thread indexing — the most common source of bugs
# ------------------------------------------------------------------
INDEXING_2D_EXAMPLE = textwrap.dedent("""\
    // For 2D data (e.g. an image), threads/blocks are often organized
    // in 2D too, with a corresponding 2D index computation:
    __global__ void process_image(float* image, int width, int height) {
        int x = blockIdx.x * blockDim.x + threadIdx.x;
        int y = blockIdx.y * blockDim.y + threadIdx.y;

        if (x < width && y < height) {   // 2D bounds check
            int idx = y * width + x;      // flatten 2D coords to 1D memory offset
            image[idx] = process_pixel(image[idx]);
        }
    }

    // Host-side launch with a 2D grid/block configuration:
    dim3 threads_per_block(16, 16);   // 256 threads per block, arranged 16x16
    dim3 blocks((width + 15) / 16, (height + 15) / 16);
    process_image<<<blocks, threads_per_block>>>(d_image, width, height);
""")

# ------------------------------------------------------------------
# 3. Streams — overlapping memory transfer with compute
# ------------------------------------------------------------------
STREAMS_EXAMPLE = textwrap.dedent("""\
    cudaStream_t stream1, stream2;
    cudaStreamCreate(&stream1);
    cudaStreamCreate(&stream2);

    // ASYNC memory copy + kernel launch on stream1 for batch 1
    cudaMemcpyAsync(d_batch1, h_batch1, bytes, cudaMemcpyHostToDevice, stream1);
    process_kernel<<<blocks, threads, 0, stream1>>>(d_batch1, n);

    // Batch 2's transfer can OVERLAP with batch 1's kernel execution,
    // since they're on DIFFERENT streams — hiding transfer latency
    // behind useful compute time, instead of the default sequential
    // "copy, THEN compute, THEN copy" behavior of the implicit stream.
    cudaMemcpyAsync(d_batch2, h_batch2, bytes, cudaMemcpyHostToDevice, stream2);
    process_kernel<<<blocks, threads, 0, stream2>>>(d_batch2, n);

    cudaStreamSynchronize(stream1);
    cudaStreamSynchronize(stream2);
""")

# ------------------------------------------------------------------
# 4. Calling CUDA from Python — CuPy and Numba as accessible entry points
# ------------------------------------------------------------------
PYTHON_CUDA_ACCESS_EXAMPLE = textwrap.dedent("""\
    # CuPy — a NumPy-compatible array library running on the GPU, no
    # manual CUDA C++ needed for standard array operations:
    import cupy as cp
    a = cp.array([1, 2, 3], dtype=cp.float32)
    b = cp.array([4, 5, 6], dtype=cp.float32)
    c = a + b   # runs on the GPU transparently, NumPy-like API

    # Numba's @cuda.jit lets you write CUDA KERNELS directly in Python
    # syntax, compiled to real GPU machine code — a middle ground between
    # CuPy's high-level API and raw CUDA C++:
    from numba import cuda

    @cuda.jit
    def vector_add_numba(a, b, out):
        idx = cuda.grid(1)   # equivalent to blockIdx.x * blockDim.x + threadIdx.x
        if idx < out.size:
            out[idx] = a[idx] + b[idx]
""")


if __name__ == "__main__":
    print(FULL_CUDA_PROGRAM_EXAMPLE)
    print(INDEXING_2D_EXAMPLE)
    print(STREAMS_EXAMPLE)
    print(PYTHON_CUDA_ACCESS_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
A computer-vision preprocessing pipeline processes incoming video
frames using a Numba @cuda.jit kernel for a custom color-space
conversion not available in any standard library, using multiple CUDA
streams to overlap the NEXT frame's host-to-device transfer with the
CURRENT frame's kernel processing — achieving near-zero effective
transfer overhead in the steady state, a direct application of L02's
streams concept to a real, custom (non-library-covered) GPU workload.
"""

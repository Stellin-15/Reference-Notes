# Quantum Computing — In-Depth Reference

Future-proofing knowledge — lower priority than most domains in this
repo, but genuinely relevant given post-quantum cryptography's active
rollout (see Cryptography Notes) and occasional appearance in
forward-looking technical discussions.


## 1. QUBITS — WHAT'S ACTUALLY DIFFERENT FROM A BIT

A classical bit is definitively 0 or 1. A **qubit** exists in a
SUPERPOSITION — a quantum state that is a weighted combination of |0⟩
and |1⟩ simultaneously, described by complex amplitudes whose squared
magnitudes give the PROBABILITY of measuring each outcome. This isn't
"the bit is secretly both at once in a classical sense" — it's a
genuinely different mathematical object (a vector in a complex vector
space) that only collapses to a definite classical 0 or 1 upon
MEASUREMENT, at which point the superposition is destroyed. **Entanglement**
— two or more qubits whose combined state can't be described as
independent individual qubit states — measuring one entangled qubit
instantaneously affects what you'll measure on its entangled partner,
regardless of physical distance — a real, experimentally verified
phenomenon (not faster-than-light communication — no classical
INFORMATION can actually be transmitted this way, a genuinely subtle and
frequently-misunderstood point).


## 2. WHY QUANTUM COMPUTING MATTERS FOR SPECIFIC PROBLEM CLASSES ONLY

Quantum computers are NOT faster at everything — they offer proven
speedups for a specific, narrow set of problems with known quantum
algorithms:
- **Shor's algorithm** — factors large integers exponentially faster
  than the best known classical algorithm — this is THE reason RSA/ECC
  encryption is considered quantum-vulnerable (see Cryptography deep
  dive's post-quantum cryptography section) — a sufficiently large,
  error-corrected quantum computer could break current public-key cryptography.
- **Grover's algorithm** — provides a quadratic (not exponential) speedup
  for unstructured search problems — meaningful but far less
  dramatic than Shor's algorithm; this is why symmetric encryption (AES)
  is considered LESS quantum-vulnerable than RSA/ECC (Grover's quadratic
  speedup against AES-256 is mitigated simply by doubling the key size,
  unlike Shor's algorithm which breaks RSA/ECC's underlying math structure entirely).
- **Quantum simulation** — simulating quantum physical/chemical systems
  (molecular interactions for drug discovery, material science) is
  where near-term quantum computers show the most genuinely promising
  practical advantage, since simulating quantum systems on CLASSICAL
  hardware is itself exponentially expensive — quantum computers are naturally suited to this specific task.


## 3. THE CURRENT STATE OF THE HARDWARE — NISQ ERA

We are currently in the **NISQ (Noisy Intermediate-Scale Quantum) era**
— today's quantum computers have a meaningful number of qubits but
suffer from significant NOISE/decoherence (qubits lose their quantum
state quickly due to environmental interference) and lack full ERROR
CORRECTION — this is why quantum computers haven't yet broken real-world
RSA encryption despite Shor's algorithm existing mathematically: running
it on a large enough number to matter requires far more STABLE,
ERROR-CORRECTED qubits than currently exist. Quantum error correction
itself requires many PHYSICAL qubits to encode one reliable LOGICAL
qubit — the actual gap between "qubits exist" and "quantum computing threatens current cryptography in practice" is this error-correction overhead, not merely raw qubit count.


## 4. NICHE BUT REAL

- **"Harvest now, decrypt later"** — the real, PRESENT-DAY security
  concern despite quantum computers not yet being capable of breaking
  RSA/ECC — an adversary can record encrypted traffic TODAY and decrypt
  it once sufficiently powerful quantum computers exist years from now —
  this is precisely why post-quantum cryptography migration (NIST's
  ML-KEM/ML-DSA standards, see Cryptography deep dive) is being
  proactively rolled out NOW, well before quantum computers can actually
  break current encryption, specifically to close this future-decryption window.
- **Quantum supremacy/advantage claims** — Google's and others' claimed
  demonstrations of a quantum computer solving a specific (often
  contrived, not practically useful) problem faster than any classical
  computer — genuinely significant as a research milestone, but worth
  distinguishing from "quantum computers are now generally faster/useful
  for real-world problems," which remains a much higher, largely unmet bar.
- **Quantum computing cloud access** — IBM Quantum, Amazon Braket, Azure
  Quantum offer cloud access to real (and simulated) quantum hardware —
  genuinely accessible for experimentation today without owning
  specialized hardware, primarily useful currently for research/education
  rather than production workloads.
- **Topological & other qubit hardware approaches** — superconducting
  qubits (IBM, Google), trapped ions (IonQ), and topological qubits
  (Microsoft's approach, aiming for inherently more error-resistant
  qubits) represent genuinely different physical implementation
  strategies with different tradeoffs in qubit count, coherence time,
  and gate fidelity — worth knowing multiple competing hardware
  paradigms exist, not one standardized quantum computer architecture.
- **Quantum machine learning** — an active but still largely research-
  stage area exploring whether quantum algorithms can accelerate ML
  training/inference — genuinely unclear as of now whether meaningful
  practical advantage exists here versus classical ML, worth treating
  with more skepticism than the cryptography-breaking application, which has firmer theoretical grounding (Shor's algorithm).

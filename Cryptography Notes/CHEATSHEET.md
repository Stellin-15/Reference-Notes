# Cryptography — In-Depth Reference

Applied cryptography for engineers — not the math derivations (that's
Classical ML/theory territory), but what to actually use, why, and the
mistakes that turn correct algorithms into broken security.


## 1. SYMMETRIC ENCRYPTION

**AES** (Advanced Encryption Standard) is the near-universal symmetric
cipher — AES-256 for anything new. The MODE matters more than the key size
for real-world security:
- **AES-GCM** (Galois/Counter Mode) — authenticated encryption (encrypts
  AND verifies integrity in one pass) — the correct modern default.
- **AES-CBC** — encryption only, no built-in integrity check; using CBC
  WITHOUT a separate MAC (encrypt-then-MAC) exposes padding-oracle attacks
  — a real, recurring vulnerability class (the "Lucky 13," POODLE-adjacent
  family of attacks all trace back to this exact mistake).
- **ChaCha20-Poly1305** — the modern alternative to AES-GCM, faster on
  hardware without AES instruction-set acceleration (mobile/embedded) —
  what TLS 1.3 uses as its non-AES cipher suite.

**Never roll your own crypto** isn't a cliché — it's specifically about
NOT re-implementing primitives (write your own AES) and NOT hand-rolling
protocol logic around correct primitives (a hand-built "encrypt then
concatenate a checksum" scheme, even using real AES, routinely fails in
ways professional cryptographic libraries' authenticated modes prevent by construction.)


## 2. ASYMMETRIC (PUBLIC-KEY) CRYPTOGRAPHY

- **RSA** — still common (TLS certs, older systems), but slow and requires
  large keys (2048-4096 bit) for adequate security margin.
- **ECC** (Elliptic Curve Cryptography, e.g. Curve25519, P-256) — same
  security level as RSA with MUCH smaller keys and faster operations — the
  modern default for new systems (WireGuard, SSH ed25519 keys, most modern TLS).
- **Diffie-Hellman / ECDH** — key EXCHANGE, not encryption itself: lets two
  parties agree on a shared secret over an insecure channel without ever
  transmitting the secret itself — the mechanism underneath TLS's handshake
  and WireGuard's tunnel setup.

```
Why public-key crypto solves the "how do strangers get a shared key"
problem symmetric crypto alone can't:
  Symmetric: both sides need the SAME key beforehand — a distribution problem.
  Asymmetric: each side has a public/private keypair; encrypt with the
    recipient's PUBLIC key, only their PRIVATE key can decrypt — no
    pre-shared secret needed. In practice: asymmetric crypto is used to
    negotiate a SYMMETRIC session key (it's much slower), then the fast
    symmetric cipher handles the actual bulk data — this hybrid approach
    is exactly what TLS does.
```


## 3. HASHING & INTEGRITY

- **SHA-256/SHA-3** — general-purpose cryptographic hashing (file
  integrity, digital signatures, Merkle trees/blockchain) — fast BY DESIGN,
  which is exactly why it's WRONG for password storage (see Auth & Security
  deep dive — password hashing needs to be deliberately slow: bcrypt/Argon2, not SHA-256).
- **HMAC** — a hash combined with a secret key, proving both integrity AND
  authenticity (that the message came from someone who knows the key) —
  what webhook-signature verification (Stripe, GitHub) is built on.
- **MD5/SHA-1** — cryptographically BROKEN (collision attacks are
  practical) — still seen in legacy systems for non-security checksums
  (deduplication, non-adversarial integrity checks) but must never be used
  anywhere a malicious actor could exploit a collision.


## 4. TLS/SSL IN DEPTH

TLS 1.3's handshake (vs 1.2, see Networking Notes section 11) removed
several legacy cipher negotiation round-trips and DEPRECATED weak options
entirely (no more RSA key exchange without forward secrecy, no more CBC
mode cipher suites) — TLS 1.3 support essentially forces the secure
defaults instead of allowing a downgrade to a weak-but-compatible option,
closing an entire historical attack class (downgrade attacks) by removing
the vulnerable choices from the protocol altogether.

**Certificate chains, precisely**: a Root CA cert (self-signed, trusted by
being pre-installed in OS/browser trust stores) signs an Intermediate CA
cert, which signs your Leaf/server cert — browsers validate the ENTIRE
chain back to a trusted root. Misconfiguring a server to omit the
intermediate cert is one of the most common real TLS deployment errors
(works in browsers that cache the intermediate from elsewhere, breaks for
clients/tools that don't).

**mTLS (mutual TLS)** — BOTH client and server present certificates,
authenticating each other, not just the server authenticating to the
client as in normal TLS — the standard mechanism for service-to-service
auth inside a service mesh (Istio's default mode — see Kubernetes Notes
deep dive section 17).


## 5. DIGITAL SIGNATURES & PKI

A digital signature = hash the message, encrypt the hash with the SIGNER's
PRIVATE key; anyone can verify using the signer's PUBLIC key — proving
authenticity (only the private-key holder could have produced it) and
integrity (any change to the message invalidates the signature) in one
mechanism. This underlies code-signing (cosign for container images — see
Docker Notes), commit signing (Git & GitHub Notes), and TLS certificates themselves.

**PKI (Public Key Infrastructure)** is the entire trust-management system
around this: Certificate Authorities issuing/revoking certs, Certificate
Transparency logs (public, append-only records of every issued cert —
see Ethical Hacking Notes section 2 for using crt.sh in recon), and
revocation mechanisms (CRLs, OCSP) for when a cert needs to be invalidated before its expiry.


## 6. NICHE BUT REAL

- **Perfect Forward Secrecy (PFS)** — using an ephemeral (per-session) key
  exchange (ECDHE) means even if a server's LONG-TERM private key is later
  compromised, PAST recorded traffic can't be decrypted retroactively —
  each session's key is independently derived and discarded, not
  derivable from the long-term key alone.
- **Post-quantum cryptography** — NIST has standardized ML-KEM (formerly
  Kyber) and ML-DSA (formerly Dilithium) specifically because a
  sufficiently large quantum computer would break RSA/ECC via Shor's
  algorithm; "harvest now, decrypt later" is the real near-term threat
  model (adversaries recording encrypted traffic TODAY to decrypt once
  quantum computing matures) — major browsers/TLS stacks are already
  rolling out hybrid classical+post-quantum key exchange.
- **Homomorphic encryption** — allows computation directly on ENCRYPTED
  data without decrypting it first — still mostly research/niche-production
  (heavy performance cost) but a real, named technique for privacy-
  preserving computation (e.g. a cloud provider computing on data it never sees in plaintext).
- **Zero-knowledge proofs** — proving a statement is true (I know this
  password / I'm over 18 / this transaction is valid) WITHOUT revealing the
  underlying secret itself — the cryptographic foundation of zk-SNARKs in
  blockchain privacy/scaling (see Blockchain & Web3 Notes) and increasingly
  proposed for privacy-preserving identity verification.
- **Side-channel attacks** — extracting a secret key not by breaking the
  math, but by measuring TIMING, POWER CONSUMPTION, or even ACOUSTIC
  signals during cryptographic operations — a real, practical attack class
  against otherwise mathematically sound implementations, part of why
  constant-time implementations matter (see Auth & Security Notes deep
  dive on timing attacks).

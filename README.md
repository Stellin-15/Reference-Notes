# Senior Engineer & ML Architect Reference Notes

A structured self-study library covering the full modern backend + ML engineering stack — from zero to senior/architect level. Every lesson is heavily commented with real-world production examples, common mistakes, and trading/data system use cases.

**11 domains · 88 lessons · Zero to architect in each**

---

## How to Use This Repo

Each domain has 8 lessons (`L01` → `L08`) that progress linearly:
- **L01–L02** — Core concepts and foundations
- **L03–L05** — Intermediate patterns and internals
- **L06–L07** — Advanced production techniques
- **L08** — Architect-level system design

Every file follows the same comment structure:
```
WHAT / WHY / LEVEL header
CONCEPT OVERVIEW
PRODUCTION USE CASE
COMMON MISTAKES
Inline comments on every non-trivial line
Real end-to-end example
```

Read a domain top-to-bottom, or jump to the lesson that matches your current level.

---

## Domains

### [C++ Notes](C++%20Notes/) — HFT & Systems Programming
C++ from first principles to a complete HFT trading system. Every lesson ties the language feature to a real trading use case (order books, market data, latency).

| File | Topic |
|------|-------|
| [L01.cpp](C++%20Notes/L01.cpp) | Hello World, `cout`, headers, `\n` vs `endl` |
| [L02.cpp](C++%20Notes/L02.cpp) | Arithmetic, operators, PnL calculations |
| [L03.cpp](C++%20Notes/L03.cpp) | Variables, data types, fixed-width integers (`int64_t`) |
| [L04.cpp](C++%20Notes/L04.cpp) | `const`, `constexpr`, `auto`, type casting |
| [L05.cpp](C++%20Notes/L05.cpp) | User input, I/O basics |
| [L06.cpp](C++%20Notes/L06.cpp) | Bitwise operators, order flags, bitmasks |
| [L07.cpp](C++%20Notes/L07.cpp) | Control flow, branch prediction, order routing logic |
| [L08.cpp](C++%20Notes/L08.cpp) | Loops, loop unrolling, order book iteration |
| [L09.cpp](C++%20Notes/L09.cpp) | Functions, pass by value/reference/pointer |
| [L10.cpp](C++%20Notes/L10.cpp) | Arrays, `std::array`, price history buffers |
| [L11.cpp](C++%20Notes/L11.cpp) | Strings, `string_view`, FIX message parsing |
| [L12.cpp](C++%20Notes/L12.cpp) | Pointers, pointer arithmetic, market data buffers |
| [L13.cpp](C++%20Notes/L13.cpp) | References vs pointers, `const` correctness |
| [L14.cpp](C++%20Notes/L14.cpp) | Heap vs stack, `new`/`delete`, pre-allocation |
| [L15.cpp](C++%20Notes/L15.cpp) | Scope, lifetime, RAII |
| [L16.cpp](C++%20Notes/L16.cpp) | Classes, constructors, destructors — `Order`, `Position` |
| [L17.cpp](C++%20Notes/L17.cpp) | Access modifiers, encapsulation, `OrderBook` |
| [L18.cpp](C++%20Notes/L18.cpp) | Inheritance, polymorphism, strategy hierarchy |
| [L19.cpp](C++%20Notes/L19.cpp) | Virtual functions, vtables, latency cost |
| [L20.cpp](C++%20Notes/L20.cpp) | Operator overloading for `Price`, `Order` |
| [L21.cpp](C++%20Notes/L21.cpp) | Copy/move semantics, Rule of 5, zero-copy pipelines |
| [L22.cpp](C++%20Notes/L22.cpp) | Templates, `RingBuffer<T>`, `OrderPool<T>` |
| [L23.cpp](C++%20Notes/L23.cpp) | Smart pointers — `unique_ptr` preferred in HFT |
| [L24.cpp](C++%20Notes/L24.cpp) | Move semantics, perfect forwarding |
| [L25.cpp](C++%20Notes/L25.cpp) | `constexpr`, compile-time constants, lookup tables |
| [L26.cpp](C++%20Notes/L26.cpp) | Lambdas, `std::function`, fill callbacks |
| [L27.cpp](C++%20Notes/L27.cpp) | STL containers — `map` for order book, `unordered_map` for symbols |
| [L28.cpp](C++%20Notes/L28.cpp) | STL algorithms — `lower_bound` for order book, `accumulate` for PnL |
| [L29.cpp](C++%20Notes/L29.cpp) | Iterators, ranges, lazy market data pipelines |
| [L30.cpp](C++%20Notes/L30.cpp) | `optional`, `variant`, `span` — safe nullable types |
| [L31.cpp](C++%20Notes/L31.cpp) | Error handling — why HFT avoids exceptions in hot path |
| [L32.cpp](C++%20Notes/L32.cpp) | File I/O, binary vs text, memory-mapped files |
| [L33.cpp](C++%20Notes/L33.cpp) | `std::chrono`, `rdtsc`, nanosecond latency measurement |
| [L34.cpp](C++%20Notes/L34.cpp) | Type traits, SFINAE, Concepts (C++20) |
| [L35.cpp](C++%20Notes/L35.cpp) | `std::thread` — market data, order, risk threads |
| [L36.cpp](C++%20Notes/L36.cpp) | Mutexes, `lock_guard`, deadlock prevention |
| [L37.cpp](C++%20Notes/L37.cpp) | `std::atomic`, memory ordering, lock-free flags |
| [L38.cpp](C++%20Notes/L38.cpp) | Lock-free data structures, SPSC queue |
| [L39.cpp](C++%20Notes/L39.cpp) | `condition_variable`, producer-consumer |
| [L40.cpp](C++%20Notes/L40.cpp) | Thread affinity, CPU pinning, NUMA |
| [L41.cpp](C++%20Notes/L41.cpp) | Busy waiting, spin loops, `_mm_pause()` |
| [L42.cpp](C++%20Notes/L42.cpp) | Thread-local storage, false sharing, cache line padding |
| [L43.cpp](C++%20Notes/L43.cpp) | Memory layout, cache efficiency, AoS vs SoA |
| [L44.cpp](C++%20Notes/L44.cpp) | Custom allocators, memory pools, no-malloc hot path |
| [L45.cpp](C++%20Notes/L45.cpp) | SIMD, AVX2 intrinsics, vectorized price scanning |
| [L46.cpp](C++%20Notes/L46.cpp) | TCP/UDP sockets, `TCP_NODELAY`, FIX over TCP |
| [L47.cpp](C++%20Notes/L47.cpp) | Multicast UDP, market data feeds (CME Globex, ITCH) |
| [L48.cpp](C++%20Notes/L48.cpp) | Non-blocking I/O, `epoll`, event-driven gateway |
| [L49.cpp](C++%20Notes/L49.cpp) | `mmap`, shared memory, zero-copy IPC |
| [L50.cpp](C++%20Notes/L50.cpp) | `rdtsc`, `perf`, latency percentiles |
| [L51.cpp](C++%20Notes/L51.cpp) | Compiler optimizations, PGO, `[[likely]]`/`[[unlikely]]` |
| [L52.cpp](C++%20Notes/L52.cpp) | Kernel bypass, DPDK, FPGA (overview) |
| [L53.cpp](C++%20Notes/L53.cpp) | Order representation — `Order` struct, enums |
| [L54.cpp](C++%20Notes/L54.cpp) | Order book implementation — bid/ask maps, BBO |
| [L55.cpp](C++%20Notes/L55.cpp) | Order matching engine — FIFO, partial fills |
| [L56.cpp](C++%20Notes/L56.cpp) | FIX protocol parsing — tag-value, zero-copy |
| [L57.cpp](C++%20Notes/L57.cpp) | NASDAQ ITCH — binary protocol, `reinterpret_cast` |
| [L58.cpp](C++%20Notes/L58.cpp) | Market data feed handler — ring buffer, gap detection |
| [L59.cpp](C++%20Notes/L59.cpp) | Risk management — pre-trade checks, kill switch |
| [L60.cpp](C++%20Notes/L60.cpp) | Position & PnL tracking — realized vs unrealized |
| [L61.cpp](C++%20Notes/L61.cpp) | Strategy framework — CRTP, `onMarketData()`, `onFill()` |
| [L62.cpp](C++%20Notes/L62.cpp) | Async lock-free logger — SPSC queue, background drain |
| [L63.cpp](C++%20Notes/L63.cpp) | Configuration system — JSON/TOML, SIGHUP reload |
| [L64.cpp](C++%20Notes/L64.cpp) | Backtesting framework — tick replay, Sharpe, drawdown |
| [L65.cpp](C++%20Notes/L65.cpp) | Full system architecture — Feed → Book → Strategy → Risk → Gateway |

---

### [Python Notes](Python%20Notes/) — Python Internals to Production
Deep Python from CPython internals to production design patterns. Focuses on the why behind language features, not just syntax.

| File | Topic |
|------|-------|
| [L01_python_internals.py](Python%20Notes/L01_python_internals.py) | GIL, CPython, bytecode, dunder methods, `__slots__` |
| [L02_data_structures_and_complexity.py](Python%20Notes/L02_data_structures_and_complexity.py) | list/dict/set internals, Big-O, when to use what |
| [L03_functions_advanced.py](Python%20Notes/L03_functions_advanced.py) | Closures, decorators, generators, `contextlib` |
| [L04_oop_advanced.py](Python%20Notes/L04_oop_advanced.py) | Metaclasses, ABC, Protocol, dataclasses, descriptors, MRO |
| [L05_concurrency.py](Python%20Notes/L05_concurrency.py) | threading, multiprocessing, asyncio, `concurrent.futures` |
| [L06_performance_and_profiling.py](Python%20Notes/L06_performance_and_profiling.py) | cProfile, NumPy vectorization, struct, memoryview |
| [L07_testing_and_quality.py](Python%20Notes/L07_testing_and_quality.py) | pytest fixtures, mock, hypothesis, coverage, async tests |
| [L08_design_patterns.py](Python%20Notes/L08_design_patterns.py) | Factory, Observer, Repository, DI, Circuit Breaker, SOLID |

---

### [SQL Notes](SQL%20Notes/) — PostgreSQL from Foundations to Architecture
PostgreSQL dialect throughout. Covers query writing, performance tuning, and data modeling for production systems.

| File | Topic |
|------|-------|
| [L01_foundations.sql](SQL%20Notes/L01_foundations.sql) | SELECT, data types, NULL behavior, string/date functions |
| [L02_joins.sql](SQL%20Notes/L02_joins.sql) | All join types with visual diagrams, performance |
| [L03_aggregations_and_grouping.sql](SQL%20Notes/L03_aggregations_and_grouping.sql) | GROUP BY, HAVING, ROLLUP, CUBE, FILTER |
| [L04_window_functions.sql](SQL%20Notes/L04_window_functions.sql) | ROW_NUMBER, RANK, LAG, LEAD, frame clauses |
| [L05_ctes_and_subqueries.sql](SQL%20Notes/L05_ctes_and_subqueries.sql) | WITH clause, recursive CTEs, LATERAL joins |
| [L06_indexes_and_performance.sql](SQL%20Notes/L06_indexes_and_performance.sql) | B-tree/Hash/GIN/GiST/BRIN, EXPLAIN ANALYZE, pg_stat_statements |
| [L07_advanced_patterns.sql](SQL%20Notes/L07_advanced_patterns.sql) | Upsert, isolation levels, SKIP LOCKED, partitioning, JSONB |
| [L08_data_modeling.sql](SQL%20Notes/L08_data_modeling.sql) | Star schema, SCD Type 1/2/3, event sourcing, multi-tenancy |

---

### [Docker Notes](Docker%20Notes/) — Containers from Internals to Production Security
From Linux namespaces and cgroups to production-hardened multi-service deployments.

| File | Topic |
|------|-------|
| [L01_fundamentals.sh](Docker%20Notes/L01_fundamentals.sh) | Namespaces, cgroups, OverlayFS, core commands |
| [L02_dockerfile_basics.Dockerfile](Docker%20Notes/L02_dockerfile_basics.Dockerfile) | FROM, RUN, COPY, ENTRYPOINT vs CMD (exec vs shell form) |
| [L03_multistage_builds.Dockerfile](Docker%20Notes/L03_multistage_builds.Dockerfile) | Builder → slim final, Python/Node/Go examples |
| [L04_networking.sh](Docker%20Notes/L04_networking.sh) | Bridge, host, overlay, macvlan, DNS, network isolation |
| [L05_volumes_and_storage.sh](Docker%20Notes/L05_volumes_and_storage.sh) | Bind mounts, named volumes, tmpfs, backup/restore |
| [L06_compose.yaml](Docker%20Notes/L06_compose.yaml) | Multi-service app (nginx + api + worker + postgres + redis), healthchecks |
| [L07_security.sh](Docker%20Notes/L07_security.sh) | Non-root user, `--read-only`, `--cap-drop ALL`, seccomp, trivy |
| [L08_production_patterns.sh](Docker%20Notes/L08_production_patterns.sh) | tini, graceful SIGTERM, BuildKit, multi-platform, rolling updates |

---

### [Apache Kafka Notes](Apache%20Kafka%20Notes/) — Distributed Messaging to Exactly-Once Semantics
From the commit log model to production cluster operations, schema evolution, and stream processing.

| File | Topic |
|------|-------|
| [L01_concepts.sh](Apache%20Kafka%20Notes/L01_concepts.sh) | Topics, partitions, offsets, ZooKeeper vs KRaft |
| [L02_producers.py](Apache%20Kafka%20Notes/L02_producers.py) | acks (0/1/all), `linger.ms`, idempotent, transactional producers |
| [L03_consumers.py](Apache%20Kafka%20Notes/L03_consumers.py) | Consumer groups, poll loop, manual commit, rebalancing |
| [L04_partitions_and_ordering.sh](Apache%20Kafka%20Notes/L04_partitions_and_ordering.sh) | Partition sizing, key-based partitioning, compacted topics |
| [L05_reliability.py](Apache%20Kafka%20Notes/L05_reliability.py) | Exactly-once semantics, idempotent consumer, DLQ, retry topics |
| [L06_schema_registry.py](Apache%20Kafka%20Notes/L06_schema_registry.py) | Avro, wire format, schema evolution compatibility modes |
| [L07_kafka_streams_and_ksql.py](Apache%20Kafka%20Notes/L07_kafka_streams_and_ksql.py) | Faust agents/tables, tumbling/hopping/session windows, ksqlDB |
| [L08_production_architecture.sh](Apache%20Kafka%20Notes/L08_production_architecture.sh) | Broker sizing, KRaft, MirrorMaker 2, security ACLs, Kafka Connect |

---

### [Kubernetes Notes](Kubernetes%20Notes/) — From Pod Spec to Production Multi-AZ Clusters
Covers the full Kubernetes object model, storage, autoscaling, Helm, Operators, and GitOps.

| File | Topic |
|------|-------|
| [L01_concepts.sh](Kubernetes%20Notes/L01_concepts.sh) | Control plane vs workers, etcd, API server, kubectl |
| [L02_pods_and_deployments.yaml](Kubernetes%20Notes/L02_pods_and_deployments.yaml) | Resources, liveness/readiness/startup probes, initContainers, rolling update |
| [L03_services_and_ingress.yaml](Kubernetes%20Notes/L03_services_and_ingress.yaml) | ClusterIP/NodePort/LoadBalancer, nginx ingress, TLS/cert-manager |
| [L04_configmaps_and_secrets.yaml](Kubernetes%20Notes/L04_configmaps_and_secrets.yaml) | CM vs Secret, Sealed Secrets, External Secrets Operator, Vault |
| [L05_storage.yaml](Kubernetes%20Notes/L05_storage.yaml) | PV/PVC, StorageClass, StatefulSet, volume snapshots |
| [L06_autoscaling.yaml](Kubernetes%20Notes/L06_autoscaling.yaml) | HPA, VPA, Cluster Autoscaler, KEDA, PodDisruptionBudget, QoS |
| [L07_helm_and_operators.sh](Kubernetes%20Notes/L07_helm_and_operators.sh) | Chart structure, helm lifecycle, Helm secrets, Operators, CloudNativePG |
| [L08_production_architecture.yaml](Kubernetes%20Notes/L08_production_architecture.yaml) | Topology spread, anti-affinity, NetworkPolicy, ResourceQuota, ArgoCD |

---

### [Apache Spark Notes](Apache%20Spark%20Notes/) — Distributed Computing to Delta Lake
PySpark from RDDs to Structured Streaming, with deep dives into the Catalyst optimizer and Delta Lake.

| File | Topic |
|------|-------|
| [L01_concepts.py](Apache%20Spark%20Notes/L01_concepts.py) | Architecture, DAG, lazy evaluation, SparkSession |
| [L02_rdds.py](Apache%20Spark%20Notes/L02_rdds.py) | RDD ops, `groupByKey` vs `reduceByKey`, persistence, broadcast |
| [L03_dataframes_and_sql.py](Apache%20Spark%20Notes/L03_dataframes_and_sql.py) | Schema, select/filter/join/agg, UDFs, Pandas UDFs, EXPLAIN |
| [L04_window_functions.py](Apache%20Spark%20Notes/L04_window_functions.py) | `Window`, ranking, lag/lead, frame specs, deduplication, sessions |
| [L05_performance.py](Apache%20Spark%20Notes/L05_performance.py) | Catalyst, Tungsten, AQE, partitioning, skew, broadcast joins |
| [L06_streaming.py](Apache%20Spark%20Notes/L06_streaming.py) | Structured Streaming, triggers, watermarks, stateful ops |
| [L07_delta_lake.py](Apache%20Spark%20Notes/L07_delta_lake.py) | ACID on object storage, time travel, merge, Z-ordering |
| [L08_production_architecture.py](Apache%20Spark%20Notes/L08_production_architecture.py) | Medallion architecture, cluster sizing, job monitoring |

---

### [CICD Notes](CICD%20Notes/) — GitHub Actions to GitOps
The full CI/CD pipeline: testing pyramid, Docker builds, deployment strategies, secrets, and ArgoCD GitOps.

| File | Topic |
|------|-------|
| [L01_concepts.yaml](CICD%20Notes/L01_concepts.yaml) | Pipelines, triggers, jobs, steps, runners, caching |
| [L02_github_actions.yaml](CICD%20Notes/L02_github_actions.yaml) | Workflow syntax, matrix, secrets, OIDC keyless auth |
| [L03_testing_strategies.yaml](CICD%20Notes/L03_testing_strategies.yaml) | Test pyramid: unit (matrix), integration (service containers), e2e, SAST |
| [L04_docker_cicd.yaml](CICD%20Notes/L04_docker_cicd.yaml) | BuildKit cache, multi-platform, trivy scan, cosign signing, SBOM |
| [L05_deployment_strategies.yaml](CICD%20Notes/L05_deployment_strategies.yaml) | Blue/green, canary, rolling, feature flags |
| [L06_argocd_gitops.yaml](CICD%20Notes/L06_argocd_gitops.yaml) | GitOps model, ApplicationSet, sync waves, rollback |
| [L07_secrets_and_security.yaml](CICD%20Notes/L07_secrets_and_security.yaml) | OIDC, Vault, sealed secrets, SLSA supply chain security |
| [L08_production_pipeline.yaml](CICD%20Notes/L08_production_pipeline.yaml) | Full pipeline: lint → test → build → scan → sign → deploy → verify |

---

### [Cloud Platforms Notes](Cloud%20Platforms%20Notes/) — AWS (+ Azure/GCP Equivalents)
Core cloud services with AWS as primary. Every lesson notes Azure/GCP equivalents. Architect-level HA patterns in L08.

| File | Topic |
|------|-------|
| [L01_concepts.sh](Cloud%20Platforms%20Notes/L01_concepts.sh) | Regions, AZs, shared responsibility, core service categories |
| [L02_compute.sh](Cloud%20Platforms%20Notes/L02_compute.sh) | EC2 instance types, ASGs, spot, EKS, Lambda |
| [L03_storage.sh](Cloud%20Platforms%20Notes/L03_storage.sh) | S3 (storage classes, lifecycle, presigned URLs), EBS, EFS |
| [L04_databases.sh](Cloud%20Platforms%20Notes/L04_databases.sh) | RDS/Aurora Multi-AZ, ElastiCache Redis, DynamoDB, Redshift, RDS Proxy |
| [L05_networking.sh](Cloud%20Platforms%20Notes/L05_networking.sh) | VPC, subnets, route tables, NAT, VPN, Direct Connect, CloudFront |
| [L06_iam_and_security.sh](Cloud%20Platforms%20Notes/L06_iam_and_security.sh) | IAM roles/policies, OIDC federation, SCPs, GuardDuty, KMS |
| [L07_serverless.sh](Cloud%20Platforms%20Notes/L07_serverless.sh) | Lambda, API Gateway, EventBridge, SQS/SNS, Step Functions |
| [L08_high_availability_architecture.sh](Cloud%20Platforms%20Notes/L08_high_availability_architecture.sh) | Multi-AZ, multi-region, Route 53 failover, chaos engineering |

---

### [ML Frameworks Notes](ML%20Frameworks%20Notes/) — Scikit-learn to PyTorch to Production
Complete ML framework coverage: classical ML, gradient boosting, deep learning, and production deployment.

| File | Topic |
|------|-------|
| [L01_sklearn_fundamentals.py](ML%20Frameworks%20Notes/L01_sklearn_fundamentals.py) | Estimator API, Pipeline, ColumnTransformer, CV, metrics, joblib |
| [L02_sklearn_advanced.py](ML%20Frameworks%20Notes/L02_sklearn_advanced.py) | Linear models, ensembles, stacking, SMOTE, calibration, custom transformers |
| [L03_xgboost.py](ML%20Frameworks%20Notes/L03_xgboost.py) | DMatrix, all hyperparameters, early stopping, GPU, SHAP, monotone constraints |
| [L04_pytorch_fundamentals.py](ML%20Frameworks%20Notes/L04_pytorch_fundamentals.py) | Tensors, autograd, nn.Module, training loop, DataLoader, checkpoints |
| [L05_pytorch_advanced.py](ML%20Frameworks%20Notes/L05_pytorch_advanced.py) | DDP, mixed precision (AMP), gradient accumulation, custom CUDA ops |
| [L06_pytorch_cnn_and_nlp.py](ML%20Frameworks%20Notes/L06_pytorch_cnn_and_nlp.py) | CNNs, attention, Transformers from scratch, HuggingFace integration |
| [L07_tensorflow.py](ML%20Frameworks%20Notes/L07_tensorflow.py) | Keras API, tf.data pipelines, SavedModel, TF Serving, TFX |
| [L08_production_ml.py](ML%20Frameworks%20Notes/L08_production_ml.py) | Training-serving skew, ONNX export, quantization, serving, A/B testing, SHAP |

---

### [MLOps Notes](MLOps%20Notes/) — Experiment Tracking to Full ML Platform
End-to-end MLOps: from first MLflow run to a complete production ML platform with CI/CD, feature stores, drift monitoring, and incident response.

| File | Topic |
|------|-------|
| [L01_mlops_foundations.py](MLOps%20Notes/L01_mlops_foundations.py) | MLOps maturity levels, the ML lifecycle, tooling landscape |
| [L02_experiment_tracking.py](MLOps%20Notes/L02_experiment_tracking.py) | MLflow tracking, W&B, experiment comparison, run metadata |
| [L03_feature_stores.py](MLOps%20Notes/L03_feature_stores.py) | Feast, online vs offline store, point-in-time joins, training-serving skew |
| [L04_pipelines_and_orchestration.py](MLOps%20Notes/L04_pipelines_and_orchestration.py) | Airflow, Metaflow, Kubeflow Pipelines, SageMaker Pipelines, Prefect |
| [L05_model_serving.py](MLOps%20Notes/L05_model_serving.py) | FastAPI serving, dynamic batching, ONNX RT, TorchServe, Triton, circuit breaker |
| [L06_monitoring_and_drift.py](MLOps%20Notes/L06_monitoring_and_drift.py) | PSI, KS test, Evidently AI, Prometheus metrics, retraining triggers |
| [L07_model_registry_and_versioning.py](MLOps%20Notes/L07_model_registry_and_versioning.py) | MLflow Registry, DVC, semantic versioning, shadow mode, canary routing |
| [L08_production_mlops_architecture.py](MLOps%20Notes/L08_production_mlops_architecture.py) | Full 6-layer ML platform, CI/CD for ML, cost optimization, incident response |

---

### [LLM Frameworks Notes](LLM%20Frameworks%20Notes/) — OpenAI to Production LLM Architecture
From first API call to production multi-model systems with RAG, agents, guardrails, semantic caching, and cost optimization.

| File | Topic |
|------|-------|
| [L01_openai_api.py](LLM%20Frameworks%20Notes/L01_openai_api.py) | Chat completions, streaming, function calling, structured output, vision |
| [L02_langchain_fundamentals.py](LLM%20Frameworks%20Notes/L02_langchain_fundamentals.py) | LCEL, chains, prompt templates, output parsers, memory |
| [L03_rag_systems.py](LLM%20Frameworks%20Notes/L03_rag_systems.py) | Embeddings, chunking, vector DBs, hybrid search, reranking, RAGAS eval |
| [L04_langchain_agents.py](LLM%20Frameworks%20Notes/L04_langchain_agents.py) | Tool definition, ReAct, AgentExecutor, multi-agent, security |
| [L05_langgraph.py](LLM%20Frameworks%20Notes/L05_langgraph.py) | StateGraph, nodes/edges, cycles, human-in-the-loop, checkpointing |
| [L06_llamaindex.py](LLM%20Frameworks%20Notes/L06_llamaindex.py) | Document loaders, index types, SubQuestion engine, routing, evaluation |
| [L07_aws_bedrock.py](LLM%20Frameworks%20Notes/L07_aws_bedrock.py) | Converse API, streaming, tool use, Knowledge Bases, Guardrails |
| [L08_production_llm_architecture.py](LLM%20Frameworks%20Notes/L08_production_llm_architecture.py) | Prompt versioning, injection defense, LLM router, semantic cache, observability |

---

### [Bash & Scripting Notes](Bash%20%26%20Scripting%20Notes/)
Shell scripting for DevOps and automation tasks.

---

## Recommended Study Order

**Start here if you're new to the stack:**
1. Python Notes (L01-L08) — language foundation everything else builds on
2. SQL Notes (L01-L08) — every system needs a database
3. Docker Notes (L01-L08) — package and run everything
4. Kubernetes Notes (L01-L08) — orchestrate at scale
5. CI/CD Notes (L01-L08) — automate the delivery pipeline

**Then add the data layer:**

6. Apache Kafka Notes — event streaming
7. Apache Spark Notes — large-scale data processing
8. Cloud Platforms Notes — where it all runs

**Then ML/AI:**

9. ML Frameworks Notes — models
10. MLOps Notes — production ML systems
11. LLM Frameworks Notes — AI applications

**C++ / HFT track** is independent — start anytime, pairs well with systems programming interest.

---

## Prerequisites

- Python 3.11+ for Python/ML/MLOps/LLM lessons
- Docker Desktop for Docker lessons
- `kubectl` + a cluster (minikube/kind/EKS) for Kubernetes
- PostgreSQL 15+ for SQL lessons
- AWS account (free tier covers most Cloud lessons)
- PySpark 3.4+ for Spark lessons
- g++ with C++20 support for C++ lessons

---

*88 lessons across 11 domains. Built to take you from zero to senior/architect level.*

# Senior Engineer & ML Architect Reference Notes

A structured self-study library covering the full modern backend + ML engineering stack — from zero to senior/architect level. Every lesson is heavily commented with real-world production examples, common mistakes, and trading/data system use cases.

**32 domains · 366 lessons · Zero to architect (and researcher) in each**

Domains are split into three tracks: the original **ML/Data Platform track** (Python through LLM Frameworks, plus Data Engineering — ETL, Airflow, Databricks, Snowflake, Azure Data Factory; Event-Driven & Real-Time AI Systems — NATS, Hatchet, multi-model LLM routing; Feature Stores & Modern Data Lake Notes — Trino, Iceberg, ScyllaDB, feature/model lineage; Data Science Fundamentals — probability, statistical inference, optimization, and visualization underneath every ML domain; and GPU Computing & Distributed Training — CUDA, NCCL, DeepSpeed, and multi-GPU scaling), the **Backend & Future-Proof track** (FastAPI through Platform Engineering, plus DevOps & SRE Practices — config management, incident command, error budgets, on-call; Full-Stack & Frontend Essentials — React, Vue, Node, Django, MongoDB, Elasticsearch; and System Design Case Studies — 30 deep-dive lessons on Google Meet, Docs, Spotify, Shazam, and Reddit's hardest subsystems plus a from-scratch load-balancer/reverse-proxy/resource-allocation infra build — covering current backend/full-stack job-market demand plus skills expected to stay in demand as the market shifts), and the **Research & Hardware Specialization track** (LLM Quantization & Inference — building/quantizing LLMs from scratch and writing GPU kernels — plus Agentic AI & RAG — a 26-lesson deep track covering the full modern agent/RAG ecosystem: LangGraph, CrewAI, AutoGen, LlamaIndex, Haystack, DSPy, GraphRAG, MCP, vector databases, agent memory, AI security, and observability).

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

### [Event-Driven & Real-Time AI Systems Notes](Event-Driven%20%26%20Real-Time%20AI%20Systems%20Notes/) — NATS, Hatchet, Multi-Model Routing
Event-driven architecture fundamentals through NATS JetStream, durable execution (Hatchet), real-time trigger evaluation, multi-model LLM gateways, and event-driven ML deployment — the lower-operational-overhead alternative/complement to Kafka-based streaming for moderate-throughput, real-time AI systems.

| File | Topic |
|------|-------|
| [L01_event_driven_architecture_fundamentals.py](Event-Driven%20%26%20Real-Time%20AI%20Systems%20Notes/L01_event_driven_architecture_fundamentals.py) | Event-driven vs batch vs request-response, event granularity |
| [L02_nats_jetstream_fundamentals.py](Event-Driven%20%26%20Real-Time%20AI%20Systems%20Notes/L02_nats_jetstream_fundamentals.py) | Core NATS pub/sub, JetStream persistence, streams/consumers |
| [L03_nats_vs_kafka_decision_framework.py](Event-Driven%20%26%20Real-Time%20AI%20Systems%20Notes/L03_nats_vs_kafka_decision_framework.py) | Throughput ceiling, operational overhead, when each wins |
| [L04_hatchet_durable_execution.py](Event-Driven%20%26%20Real-Time%20AI%20Systems%20Notes/L04_hatchet_durable_execution.py) | Durable retries/timeouts/fan-out vs Temporal and Celery |
| [L05_realtime_trigger_evaluation_systems.py](Event-Driven%20%26%20Real-Time%20AI%20Systems%20Notes/L05_realtime_trigger_evaluation_systems.py) | Building a Trigger Hub — subject design, batch-to-real-time latency |
| [L06_websocket_streaming_architecture.py](Event-Driven%20%26%20Real-Time%20AI%20Systems%20Notes/L06_websocket_streaming_architecture.py) | Connection lifecycle, JWT reauth, backpressure handling |
| [L07_multi_model_llm_routing.py](Event-Driven%20%26%20Real-Time%20AI%20Systems%20Notes/L07_multi_model_llm_routing.py) | Cost-based routing and fallback chains across Claude/GPT/Gemini |
| [L08_llm_gateway_patterns.py](Event-Driven%20%26%20Real-Time%20AI%20Systems%20Notes/L08_llm_gateway_patterns.py) | Per-tenant quotas, unified logging, centralized secrets |
| [L09_event_driven_ml_cicd.py](Event-Driven%20%26%20Real-Time%20AI%20Systems%20Notes/L09_event_driven_ml_cicd.py) | Registry alias-change triggers, canary rollout, auto-rollback |
| [L10_real_time_inference_serving.py](Event-Driven%20%26%20Real-Time%20AI%20Systems%20Notes/L10_real_time_inference_serving.py) | Latency budgets, hybrid fast/slow model serving |
| [L11_durable_workflows_for_ai_agents.py](Event-Driven%20%26%20Real-Time%20AI%20Systems%20Notes/L11_durable_workflows_for_ai_agents.py) | Wrapping long-running agent workflows in durable execution |
| [L12_production_realtime_ai_platform_architecture.py](Event-Driven%20%26%20Real-Time%20AI%20Systems%20Notes/L12_production_realtime_ai_platform_architecture.py) | Capstone: full reference architecture |

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

### [Data Engineering Notes](Data%20Engineering%20Notes/) — ETL, Airflow, Databricks, Snowflake, Azure Data Factory
ETL/ELT fundamentals through the four major orchestration/warehouse platforms, data quality, and a full production data platform architecture.

| File | Topic |
|------|-------|
| [L01_etl_fundamentals.py](Data%20Engineering%20Notes/L01_etl_fundamentals.py) | ETL vs ELT, idempotency, schema evolution |
| [L02_data_modeling_and_pipelines.py](Data%20Engineering%20Notes/L02_data_modeling_and_pipelines.py) | Incremental loading, CDC, partitioning strategies |
| [L03_airflow_fundamentals.py](Data%20Engineering%20Notes/L03_airflow_fundamentals.py) | DAGs, operators, scheduler/executor model, sensors |
| [L04_airflow_production.py](Data%20Engineering%20Notes/L04_airflow_production.py) | TaskFlow API, dynamic task mapping, backfills, SLAs |
| [L05_databricks_fundamentals.py](Data%20Engineering%20Notes/L05_databricks_fundamentals.py) | Workspace, clusters, Delta Lake, Unity Catalog |
| [L06_databricks_production.py](Data%20Engineering%20Notes/L06_databricks_production.py) | Workflows, Delta Live Tables, Auto Loader |
| [L07_snowflake_fundamentals.py](Data%20Engineering%20Notes/L07_snowflake_fundamentals.py) | Storage/compute separation, warehouses, Snowpipe, Time Travel |
| [L08_snowflake_advanced.py](Data%20Engineering%20Notes/L08_snowflake_advanced.py) | Streams & Tasks, Snowpark, data sharing, RBAC |
| [L09_azure_data_factory.py](Data%20Engineering%20Notes/L09_azure_data_factory.py) | Pipelines, linked services, Mapping Data Flows, integration runtimes |
| [L10_orchestration_patterns.py](Data%20Engineering%20Notes/L10_orchestration_patterns.py) | Airflow vs ADF vs Databricks Workflows vs Dagster/Prefect |
| [L11_data_quality_and_observability.py](Data%20Engineering%20Notes/L11_data_quality_and_observability.py) | Great Expectations/dbt tests, lineage, pipeline monitoring |
| [L12_production_data_platform_architecture.py](Data%20Engineering%20Notes/L12_production_data_platform_architecture.py) | Capstone: medallion architecture, full reference platform |

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

### [DevOps & SRE Practices Notes](DevOps%20%26%20SRE%20Practices%20Notes/) — Config Management, Incident Response, Error Budgets
The operational discipline underneath CI/CD: configuration management, Linux/network fundamentals, load testing, capacity planning, and the incident/postmortem/on-call practices that keep production systems running.

| File | Topic |
|------|-------|
| [L01_configuration_management_fundamentals.py](DevOps%20%26%20SRE%20Practices%20Notes/L01_configuration_management_fundamentals.py) | Push vs pull config management, idempotency, declarative vs imperative |
| [L02_ansible_deep_dive.py](DevOps%20%26%20SRE%20Practices%20Notes/L02_ansible_deep_dive.py) | Playbooks, inventories, roles, idempotent modules |
| [L03_ansible_vs_puppet_vs_chef.py](DevOps%20%26%20SRE%20Practices%20Notes/L03_ansible_vs_puppet_vs_chef.py) | Push vs pull architecture tradeoffs, when each tool wins |
| [L04_linux_systems_administration.py](DevOps%20%26%20SRE%20Practices%20Notes/L04_linux_systems_administration.py) | systemd, process/disk/package management |
| [L05_network_engineering_for_devops.py](DevOps%20%26%20SRE%20Practices%20Notes/L05_network_engineering_for_devops.py) | DNS, load balancers, security groups |
| [L06_load_and_performance_testing.py](DevOps%20%26%20SRE%20Practices%20Notes/L06_load_and_performance_testing.py) | k6, Locust, JMeter, interpreting load test results |
| [L07_capacity_planning.py](DevOps%20%26%20SRE%20Practices%20Notes/L07_capacity_planning.py) | Demand forecasting, headroom, autoscaling policy design |
| [L08_incident_command_and_management.py](DevOps%20%26%20SRE%20Practices%20Notes/L08_incident_command_and_management.py) | Severity levels, incident commander role separation |
| [L09_postmortems_and_blameless_culture.py](DevOps%20%26%20SRE%20Practices%20Notes/L09_postmortems_and_blameless_culture.py) | Blameless postmortems, 5 Whys root-cause analysis |
| [L10_sre_error_budgets_and_toil.py](DevOps%20%26%20SRE%20Practices%20Notes/L10_sre_error_budgets_and_toil.py) | SLOs, error budgets, identifying and eliminating toil |
| [L11_on_call_practices.py](DevOps%20%26%20SRE%20Practices%20Notes/L11_on_call_practices.py) | Rotation fairness, alert fatigue, runbooks |
| [L12_production_devops_architecture.py](DevOps%20%26%20SRE%20Practices%20Notes/L12_production_devops_architecture.py) | Capstone: full operational architecture end to end |

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

### [Data Science Fundamentals Notes](Data%20Science%20Fundamentals%20Notes/) — Probability, Statistics, Optimization, Visualization
The mathematical foundation underneath every ML/data domain in this repo: probability and Bayesian inference, statistical hypothesis testing, EDA, gradient-descent optimization, linear algebra for ML, and data visualization (Matplotlib/Seaborn/Tableau) done honestly.

| File | Topic |
|------|-------|
| [L01_probability_fundamentals.py](Data%20Science%20Fundamentals%20Notes/L01_probability_fundamentals.py) | Distributions, Bayes' theorem, the base-rate fallacy, expectation/variance |
| [L02_statistical_inference.py](Data%20Science%20Fundamentals%20Notes/L02_statistical_inference.py) | Central Limit Theorem, confidence intervals, hypothesis testing, p-values |
| [L03_descriptive_statistics_and_eda.py](Data%20Science%20Fundamentals%20Notes/L03_descriptive_statistics_and_eda.py) | Central tendency/spread, skewness, outlier detection, correlation vs causation |
| [L04_optimization_fundamentals.py](Data%20Science%20Fundamentals%20Notes/L04_optimization_fundamentals.py) | Gradient descent, learning rate tradeoffs, convexity, SGD with momentum |
| [L05_linear_algebra_for_ml.py](Data%20Science%20Fundamentals%20Notes/L05_linear_algebra_for_ml.py) | Vectors, dot product/cosine similarity, matrix multiplication, PCA intuition |
| [L06_matplotlib_and_seaborn.py](Data%20Science%20Fundamentals%20Notes/L06_matplotlib_and_seaborn.py) | Histograms, scatter plots, box plots, correlation heatmaps, Anscombe's Quartet |
| [L07_tableau_and_bi_visualization.py](Data%20Science%20Fundamentals%20Notes/L07_tableau_and_bi_visualization.py) | Interactive BI dashboards, live data connections, BI vs code-based plotting |
| [L08_data_visualization_best_practices.py](Data%20Science%20Fundamentals%20Notes/L08_data_visualization_best_practices.py) | Honest axes, chart-junk, colorblind-safe palettes, chart-type selection |
| [L09_capstone_data_science_workflow.py](Data%20Science%20Fundamentals%20Notes/L09_capstone_data_science_workflow.py) | Capstone: the full EDA → inference → modeling → communication workflow |

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

### [GPU Computing & Distributed Training Notes](GPU%20Computing%20%26%20Distributed%20Training%20Notes/) — CUDA, NCCL, DeepSpeed, Multi-GPU Training
Goes under the hood of L05's `DDP`/AMP one-liners: SM/warp/Tensor Core architecture, raw CUDA programming, data/model/pipeline parallelism, NCCL collectives, DeepSpeed ZeRO, Kubernetes GPU scheduling, and profiling with Nsight.

| File | Topic |
|------|-------|
| [L01_gpu_computing_fundamentals.py](GPU%20Computing%20%26%20Distributed%20Training%20Notes/L01_gpu_computing_fundamentals.py) | SM/warp/Tensor Core architecture, why GPUs suit matrix multiplication |
| [L02_cuda_programming_basics.py](GPU%20Computing%20%26%20Distributed%20Training%20Notes/L02_cuda_programming_basics.py) | Kernels, memory management, streams |
| [L03_cudnn_and_cublas.py](GPU%20Computing%20%26%20Distributed%20Training%20Notes/L03_cudnn_and_cublas.py) | Vendor libraries, kernel fusion |
| [L04_data_parallelism.py](GPU%20Computing%20%26%20Distributed%20Training%20Notes/L04_data_parallelism.py) | PyTorch DDP internals, linear LR scaling rule |
| [L05_model_and_tensor_parallelism.py](GPU%20Computing%20%26%20Distributed%20Training%20Notes/L05_model_and_tensor_parallelism.py) | Megatron-style tensor/model parallelism |
| [L06_pipeline_parallelism.py](GPU%20Computing%20%26%20Distributed%20Training%20Notes/L06_pipeline_parallelism.py) | GPipe vs 1F1B scheduling, bubble overhead |
| [L07_nccl_collective_communication.py](GPU%20Computing%20%26%20Distributed%20Training%20Notes/L07_nccl_collective_communication.py) | AllReduce/AllGather/Broadcast, ring-AllReduce scaling |
| [L08_deepspeed.py](GPU%20Computing%20%26%20Distributed%20Training%20Notes/L08_deepspeed.py) | ZeRO stages 1-3, memory partitioning |
| [L09_horovod_and_alternatives.py](GPU%20Computing%20%26%20Distributed%20Training%20Notes/L09_horovod_and_alternatives.py) | Horovod vs native DDP/DeepSpeed |
| [L10_mixed_precision_and_gradient_scaling.py](GPU%20Computing%20%26%20Distributed%20Training%20Notes/L10_mixed_precision_and_gradient_scaling.py) | AMP in distributed settings, loss scaling |
| [L11_kubernetes_gpu_scheduling.py](GPU%20Computing%20%26%20Distributed%20Training%20Notes/L11_kubernetes_gpu_scheduling.py) | Device plugins, taints/tolerations, Kubeflow Training Operator |
| [L12_multi_instance_gpu_and_sharing.py](GPU%20Computing%20%26%20Distributed%20Training%20Notes/L12_multi_instance_gpu_and_sharing.py) | MIG partitioning, time-slicing GPU sharing |
| [L13_profiling_with_nsight.py](GPU%20Computing%20%26%20Distributed%20Training%20Notes/L13_profiling_with_nsight.py) | Nsight Systems/Compute profiling |
| [L14_rocm_and_hardware_alternatives.py](GPU%20Computing%20%26%20Distributed%20Training%20Notes/L14_rocm_and_hardware_alternatives.py) | Capstone: ROCm/HIP as an AMD alternative, full architecture |

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
| [L09_online_experimentation_for_ml.py](MLOps%20Notes/L09_online_experimentation_for_ml.py) | A/B testing statistics, the peeking problem, sequential testing, multi-armed bandits |
| [L10_ml_testing_frameworks.py](MLOps%20Notes/L10_ml_testing_frameworks.py) | Data validation, invariance/directional/minimum-functionality behavioral tests |
| [L11_responsible_ai_and_fairness.py](MLOps%20Notes/L11_responsible_ai_and_fairness.py) | Demographic parity, equalized odds, model cards, SHAP-style explainability |
| [L12_advanced_deployment_patterns.py](MLOps%20Notes/L12_advanced_deployment_patterns.py) | Champion-challenger, shadow deployment, bandit-based traffic allocation |

---

### [Feature Stores & Modern Data Lake Notes](Feature%20Stores%20%26%20Modern%20Data%20Lake%20Notes/) — Trino, Iceberg, ScyllaDB
Goes deeper than MLOps Notes L03's Feast introduction — the three-tier feature architecture, Trino+Iceberg as a lakehouse query layer, the Redis+ScyllaDB hybrid online store, point-in-time joins implemented from scratch, feature/model lineage, and the Kernels-as-a-Service polymorphic compute pattern.

| File | Topic |
|------|-------|
| [L01_feature_store_fundamentals.py](Feature%20Stores%20%26%20Modern%20Data%20Lake%20Notes/L01_feature_store_fundamentals.py) | Training-serving skew, offline/online store split, PIT correctness |
| [L02_three_tier_feature_architecture.py](Feature%20Stores%20%26%20Modern%20Data%20Lake%20Notes/L02_three_tier_feature_architecture.py) | Tier 1 ingestion / Tier 2 Feature Management API / Tier 3 online serving |
| [L03_feast_deep_dive.py](Feature%20Stores%20%26%20Modern%20Data%20Lake%20Notes/L03_feast_deep_dive.py) | Feature views, entities, feature services, materialization |
| [L04_point_in_time_joins.py](Feature%20Stores%20%26%20Modern%20Data%20Lake%20Notes/L04_point_in_time_joins.py) | Implementing PIT-correct joins, label leakage bugs, measuring skew |
| [L05_trino_fundamentals.py](Feature%20Stores%20%26%20Modern%20Data%20Lake%20Notes/L05_trino_fundamentals.py) | Distributed SQL engine, connectors, federated queries |
| [L06_apache_iceberg.py](Feature%20Stores%20%26%20Modern%20Data%20Lake%20Notes/L06_apache_iceberg.py) | Open table format internals, schema/partition evolution, time travel |
| [L07_trino_plus_iceberg_lakehouse.py](Feature%20Stores%20%26%20Modern%20Data%20Lake%20Notes/L07_trino_plus_iceberg_lakehouse.py) | Combining Trino+Iceberg into a hybrid on-prem/cloud lakehouse |
| [L08_scylladb_and_online_serving.py](Feature%20Stores%20%26%20Modern%20Data%20Lake%20Notes/L08_scylladb_and_online_serving.py) | Wide-column stores, the Redis (hot) + ScyllaDB (bulk) hybrid pattern |
| [L09_feature_and_model_lineage.py](Feature%20Stores%20%26%20Modern%20Data%20Lake%20Notes/L09_feature_and_model_lineage.py) | Lineage graphs, "which models depend on this PII feature" |
| [L10_data_event_management_systems.py](Feature%20Stores%20%26%20Modern%20Data%20Lake%20Notes/L10_data_event_management_systems.py) | The DEMS/Lasso event-ledger pattern for lineage/drift/SLA analytics |
| [L11_polymorphic_compute_platforms.py](Feature%20Stores%20%26%20Modern%20Data%20Lake%20Notes/L11_polymorphic_compute_platforms.py) | Kernels-as-a-Service: ProcessProxy, Kernel Gateway, token propagation |
| [L12_production_feature_platform_architecture.py](Feature%20Stores%20%26%20Modern%20Data%20Lake%20Notes/L12_production_feature_platform_architecture.py) | Capstone: full reference architecture |

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

### [Bash & Scripting Notes](Bash%20%26%20Scripting%20Notes/) — Shell Scripting for DevOps and Automation
From the shebang line to production-grade automation scripts — variables, control flow, text processing, process management, networking, and real-world scripts you'd actually deploy.

| File | Topic |
|------|-------|
| [L01_hello_world.sh](Bash%20%26%20Scripting%20Notes/L01_hello_world.sh) | Shebang, how bash executes a script, `echo`/`printf`, stdout vs stderr |
| [L02_variables.sh](Bash%20%26%20Scripting%20Notes/L02_variables.sh) | Declaration, quoting rules, arrays, special variables, `readonly`, `export` |
| [L03_strings.sh](Bash%20%26%20Scripting%20Notes/L03_strings.sh) | Length, substring, search/replace, case conversion, here-docs/here-strings |
| [L04_control_flow.sh](Bash%20%26%20Scripting%20Notes/L04_control_flow.sh) | `if`/`case`/`while`/`for`/`until`, `[ ]` vs `[[ ]]` vs `(( ))`, `break`/`continue` |
| [L05_functions.sh](Bash%20%26%20Scripting%20Notes/L05_functions.sh) | Arguments (`$1..$n`, `$@`), return codes vs echo, local scope, recursion |
| [L06_input_output.sh](Bash%20%26%20Scripting%20Notes/L06_input_output.sh) | `read`, redirection (`>`, `>>`, `<`), pipes, process substitution, `tee`, `/dev/null` |
| [L07_error_handling.sh](Bash%20%26%20Scripting%20Notes/L07_error_handling.sh) | `set -euo pipefail`, `trap` for cleanup, exit codes, the `ERR` trap |
| [L08_files_and_dirs.sh](Bash%20%26%20Scripting%20Notes/L08_files_and_dirs.sh) | `find`, `stat`, `cp`/`mv`/`mkdir`/`chmod`, symlinks, `du`/`df` |
| [L09_text_processing.sh](Bash%20%26%20Scripting%20Notes/L09_text_processing.sh) | `grep`, `sed`, `awk`, `cut`, `sort`, `uniq`, `tr` |
| [L10_processes.sh](Bash%20%26%20Scripting%20Notes/L10_processes.sh) | `ps`, `kill`, `jobs`, `bg`/`fg`, `&` + `wait`, `xargs` for parallel execution |
| [L11_networking.sh](Bash%20%26%20Scripting%20Notes/L11_networking.sh) | `curl`, `wget`, `ssh`, `scp`, `nc`, `ping`, DNS lookups |
| [L12_scripting_patterns.sh](Bash%20%26%20Scripting%20Notes/L12_scripting_patterns.sh) | Structured logging, `.env` config loading, file locking, idempotency, `main()` pattern |
| [L13_automation_examples.sh](Bash%20%26%20Scripting%20Notes/L13_automation_examples.sh) | Log rotation, backup, deployment, health checks, service monitoring, cron setup |

---

## Backend & Future-Proof Track

Current backend job-market skills, plus domains expected to stay in demand as the market shifts toward edge/WASM, eBPF-based infra, and platform engineering.

### [FastAPI & Python Web Notes](FastAPI%20%26%20Python%20Web%20Notes/) — Production Python Web Services
Pydantic validation, async SQLAlchemy 2.0, dependency injection, auth, WebSockets, and production deployment.

| File | Topic |
|------|-------|
| [L01_fastapi_fundamentals.py](FastAPI%20%26%20Python%20Web%20Notes/L01_fastapi_fundamentals.py) | Path/query/body params, Pydantic models, response models |
| [L02_dependency_injection.py](FastAPI%20%26%20Python%20Web%20Notes/L02_dependency_injection.py) | `Depends`, sub-dependencies, yield dependencies, overrides for testing |
| [L03_async_and_database.py](FastAPI%20%26%20Python%20Web%20Notes/L03_async_and_database.py) | Async SQLAlchemy 2.0, connection pooling, async sessions |
| [L04_auth_and_middleware.py](FastAPI%20%26%20Python%20Web%20Notes/L04_auth_and_middleware.py) | JWT auth, OAuth2PasswordBearer, custom middleware, CORS |
| [L05_testing.py](FastAPI%20%26%20Python%20Web%20Notes/L05_testing.py) | TestClient, async test fixtures, dependency overrides, mocking |
| [L06_websockets_and_realtime.py](FastAPI%20%26%20Python%20Web%20Notes/L06_websockets_and_realtime.py) | WebSocket endpoints, connection managers, pub/sub broadcast |
| [L07_performance_and_caching.py](FastAPI%20%26%20Python%20Web%20Notes/L07_performance_and_caching.py) | Response caching, background tasks, uvloop, connection tuning |
| [L08_production_deployment.py](FastAPI%20%26%20Python%20Web%20Notes/L08_production_deployment.py) | Gunicorn+Uvicorn workers, health checks, Prometheus metrics, graceful shutdown |

---

### [Full-Stack & Frontend Essentials Notes](Full-Stack%20%26%20Frontend%20Essentials%20Notes/) — React, Vue, Node/Express, Django, MongoDB, Elasticsearch
The frontend and adjacent-backend half of "full-stack": React/Vue component models and state management, Node/Express, Django as a FastAPI alternative, MongoDB and Elasticsearch, and the streaming/WebSocket integration patterns real AI chat UIs need.

| File | Topic |
|------|-------|
| [L01_react_fundamentals.py](Full-Stack%20%26%20Frontend%20Essentials%20Notes/L01_react_fundamentals.py) | Components, JSX, `useState`/`useEffect` |
| [L02_react_state_management.py](Full-Stack%20%26%20Frontend%20Essentials%20Notes/L02_react_state_management.py) | Context API, Zustand, Redux — escalating only as needed |
| [L03_vue_fundamentals.py](Full-Stack%20%26%20Frontend%20Essentials%20Notes/L03_vue_fundamentals.py) | Composition API: `ref`/`reactive`/`computed`/`watch`, fine-grained reactivity |
| [L04_nodejs_and_express.py](Full-Stack%20%26%20Frontend%20Essentials%20Notes/L04_nodejs_and_express.py) | Event loop, routing, middleware, async error handling |
| [L05_django_fundamentals.py](Full-Stack%20%26%20Frontend%20Essentials%20Notes/L05_django_fundamentals.py) | ORM, views/URLs, admin interface, vs FastAPI |
| [L06_mongodb_fundamentals.py](Full-Stack%20%26%20Frontend%20Essentials%20Notes/L06_mongodb_fundamentals.py) | Document model, embedding vs referencing, aggregation pipeline |
| [L07_elasticsearch_fundamentals.py](Full-Stack%20%26%20Frontend%20Essentials%20Notes/L07_elasticsearch_fundamentals.py) | Inverted index, text vs keyword mappings, full-text queries, aggregations |
| [L08_frontend_backend_integration.py](Full-Stack%20%26%20Frontend%20Essentials%20Notes/L08_frontend_backend_integration.py) | REST loading/error states, WebSocket reconnection, SSE streaming |
| [L09_building_ai_chat_uis.py](Full-Stack%20%26%20Frontend%20Essentials%20Notes/L09_building_ai_chat_uis.py) | Optimistic updates, agent tool-call display, response state modeling |
| [L10_fullstack_production_architecture.py](Full-Stack%20%26%20Frontend%20Essentials%20Notes/L10_fullstack_production_architecture.py) | Capstone: full-stack AI product reference architecture |

---

### [System Design Notes](System%20Design%20Notes/) — Scalable Architecture Fundamentals
CAP theorem through real end-to-end system designs (URL shortener, rate limiter, notification system, job scheduler).

| File | Topic |
|------|-------|
| [L01_foundations.py](System%20Design%20Notes/L01_foundations.py) | CAP theorem, consistency models, scalability vs availability tradeoffs |
| [L02_load_balancing_and_caching.py](System%20Design%20Notes/L02_load_balancing_and_caching.py) | LB algorithms, CDN, cache hierarchy, stampede protection |
| [L03_databases_at_scale.py](System%20Design%20Notes/L03_databases_at_scale.py) | Sharding, replication, CQRS, event sourcing, polyglot persistence |
| [L04_messaging_and_event_driven.py](System%20Design%20Notes/L04_messaging_and_event_driven.py) | RabbitMQ exchanges, delivery guarantees, Saga pattern, outbox pattern |
| [L05_microservices_patterns.py](System%20Design%20Notes/L05_microservices_patterns.py) | Service boundaries, API composition, distributed transactions |
| [L06_rate_limiting_and_api_patterns.py](System%20Design%20Notes/L06_rate_limiting_and_api_patterns.py) | Token bucket, sliding window, API gateway patterns |
| [L07_search_and_specialized_stores.py](System%20Design%20Notes/L07_search_and_specialized_stores.py) | Elasticsearch, vector DBs, time-series DBs, graph DBs |
| [L08_real_system_designs.py](System%20Design%20Notes/L08_real_system_designs.py) | URL shortener, rate limiter, notification system, job scheduler — full designs |

---

### [System Design Case Studies Notes](System%20Design%20Case%20Studies%20Notes/) — Google Meet, Docs, Spotify, Shazam, Reddit + Infra Deep Dives
Goes deeper than System Design Notes' general fundamentals — 30 focused lessons deep-diving into SPECIFIC hard subsystems of well-known real products (not whole-app overviews), plus a from-scratch build-up of the load-balancer/reverse-proxy/resource-allocation infrastructure layer underlying all of them.

| File | Topic |
|------|-------|
| **Google Meet — Real-Time Video** | |
| [L01_webrtc_fundamentals_and_signaling.py](System%20Design%20Case%20Studies%20Notes/L01_webrtc_fundamentals_and_signaling.py) | ICE, STUN/TURN NAT traversal, the signaling server |
| [L02_sfu_vs_mcu_architecture.py](System%20Design%20Case%20Studies%20Notes/L02_sfu_vs_mcu_architecture.py) | Selective forwarding vs composite/re-encode, simulcast |
| [L03_adaptive_bitrate_and_network_resilience.py](System%20Design%20Case%20Studies%20Notes/L03_adaptive_bitrate_and_network_resilience.py) | GCC congestion control, FEC, adaptive jitter buffers |
| [L04_screen_sharing_and_media_negotiation.py](System%20Design%20Case%20Studies%20Notes/L04_screen_sharing_and_media_negotiation.py) | Mid-call renegotiation, screen-share encoding profiles |
| [L05_scaling_group_calls_and_turn_relay.py](System%20Design%20Case%20Studies%20Notes/L05_scaling_group_calls_and_turn_relay.py) | SFU cascading, geographic placement, TURN capacity planning |
| **Google Docs — Collaborative Editing** | |
| [L06_operational_transform_fundamentals.py](System%20Design%20Case%20Studies%20Notes/L06_operational_transform_fundamentals.py) | OT transformation, why naive concurrent edits corrupt documents |
| [L07_crdts_for_collaborative_editing.py](System%20Design%20Case%20Studies%20Notes/L07_crdts_for_collaborative_editing.py) | Conflict-free replicated types, stable IDs, tombstones |
| [L08_presence_cursors_and_awareness.py](System%20Design%20Case%20Studies%20Notes/L08_presence_cursors_and_awareness.py) | Ephemeral presence data, heartbeat cleanup, cursor anchoring |
| [L09_offline_sync_and_conflict_resolution.py](System%20Design%20Case%20Studies%20Notes/L09_offline_sync_and_conflict_resolution.py) | Local-first buffering, merging hours of offline edits |
| [L10_version_history_and_document_storage.py](System%20Design%20Case%20Studies%20Notes/L10_version_history_and_document_storage.py) | Operation logs, periodic snapshotting, point-in-time restore |
| **Spotify + Shazam — Audio** | |
| [L11_audio_streaming_and_cdn_delivery.py](System%20Design%20Case%20Studies%20Notes/L11_audio_streaming_and_cdn_delivery.py) | Popularity-skew-aware CDN caching, adaptive bitrate audio |
| [L12_music_recommendation_systems.py](System%20Design%20Case%20Studies%20Notes/L12_music_recommendation_systems.py) | Collaborative + content-based filtering, cold start |
| [L13_playlists_social_features_and_search.py](System%20Design%20Case%20Studies%20Notes/L13_playlists_social_features_and_search.py) | Fractional ordering, social graph, popularity-weighted search |
| [L14_audio_fingerprinting_fundamentals.py](System%20Design%20Case%20Studies%20Notes/L14_audio_fingerprinting_fundamentals.py) | Spectrograms, constellation maps, time-invariant peak-pair hashing |
| [L15_fingerprint_indexing_and_matching_at_scale.py](System%20Design%20Case%20Studies%20Notes/L15_fingerprint_indexing_and_matching_at_scale.py) | Inverted-index matching, time-offset histogram voting |
| **Reddit / Social Feeds** | |
| [L16_comment_tree_storage_at_scale.py](System%20Design%20Case%20Studies%20Notes/L16_comment_tree_storage_at_scale.py) | Adjacency list vs materialized path vs nested sets, lazy loading |
| [L17_feed_ranking_algorithms.py](System%20Design%20Case%20Studies%20Notes/L17_feed_ranking_algorithms.py) | "Hot" time-decay formula, Wilson score "Best" ranking |
| [L18_voting_systems_and_anti_fraud.py](System%20Design%20Case%20Studies%20Notes/L18_voting_systems_and_anti_fraud.py) | Event-sourced vote counters, brigading/bot detection |
| [L19_fanout_on_write_vs_read.py](System%20Design%20Case%20Studies%20Notes/L19_fanout_on_write_vs_read.py) | The celebrity problem, hybrid push/pull feed architecture |
| [L20_trending_and_hot_ranking_at_scale.py](System%20Design%20Case%20Studies%20Notes/L20_trending_and_hot_ranking_at_scale.py) | Sliding windows, baseline-deviation spikes, count-min sketch |
| **Infrastructure Deep Dives — Load Balancers, Proxies, Resource Allocation** | |
| [L21_load_balancing_fundamentals_l4_vs_l7.py](System%20Design%20Case%20Studies%20Notes/L21_load_balancing_fundamentals_l4_vs_l7.py) | Transport vs application layer load balancing |
| [L22_load_balancing_algorithms.py](System%20Design%20Case%20Studies%20Notes/L22_load_balancing_algorithms.py) | Round robin, least connections, consistent hashing |
| [L23_health_checks_and_failover.py](System%20Design%20Case%20Studies%20Notes/L23_health_checks_and_failover.py) | Active vs passive checks, failure/recovery thresholds |
| [L24_reverse_proxy_internals.py](System%20Design%20Case%20Studies%20Notes/L24_reverse_proxy_internals.py) | Forward vs reverse proxy, header manipulation, URL rewriting |
| [L25_nginx_vs_envoy_vs_haproxy.py](System%20Design%20Case%20Studies%20Notes/L25_nginx_vs_envoy_vs_haproxy.py) | Static vs dynamic config models, service-mesh data planes |
| [L26_ssl_tls_termination.py](System%20Design%20Case%20Studies%20Notes/L26_ssl_tls_termination.py) | Terminate-and-forward vs re-encrypt vs passthrough, mTLS |
| [L27_resource_allocation_and_bin_packing.py](System%20Design%20Case%20Studies%20Notes/L27_resource_allocation_and_bin_packing.py) | First fit/best fit, bin-packing vs spreading for fault tolerance |
| [L28_autoscaling_strategies.py](System%20Design%20Case%20Studies%20Notes/L28_autoscaling_strategies.py) | Reactive, predictive, and scheduled scaling |
| [L29_building_a_load_balancer_from_scratch.py](System%20Design%20Case%20Studies%20Notes/L29_building_a_load_balancer_from_scratch.py) | A genuinely runnable Python load balancer implementation |
| [L30_capstone_full_infra_stack.py](System%20Design%20Case%20Studies%20Notes/L30_capstone_full_infra_stack.py) | Capstone: full request trace, mapped back to every earlier case study |

---

### [Go Notes](Go%20Notes/) — Concurrent Backend Services
Goroutines/channels through gRPC, profiling, and production deployment.

| File | Topic |
|------|-------|
| [L01_fundamentals.go](Go%20Notes/L01_fundamentals.go) | Types, structs, interfaces, error handling idioms |
| [L02_concurrency.go](Go%20Notes/L02_concurrency.go) | Goroutines, channels, select, sync package, context |
| [L03_http_server.go](Go%20Notes/L03_http_server.go) | net/http, routing, middleware chains, graceful shutdown |
| [L04_database_and_grpc.go](Go%20Notes/L04_database_and_grpc.go) | pgx, sqlc, gRPC + protobuf service definitions |
| [L05_testing_and_benchmarks.go](Go%20Notes/L05_testing_and_benchmarks.go) | Table-driven tests, mocks, httptest, benchmarks, fuzzing |
| [L06_performance_and_profiling.go](Go%20Notes/L06_performance_and_profiling.go) | pprof, escape analysis, sync.Pool, GOGC tuning |
| [L07_patterns_and_best_practices.go](Go%20Notes/L07_patterns_and_best_practices.go) | Functional options, error wrapping, layered architecture |
| [L08_production_deployment.go](Go%20Notes/L08_production_deployment.go) | Build flags, structured logging, health/readiness, Dockerfile |

---

### [Redis & Caching Notes](Redis%20%26%20Caching%20Notes/) — Caching, Streams, and Distributed Patterns
All Redis data types through clustering, Sentinel, and production hardening.

| File | Topic |
|------|-------|
| [L01_fundamentals.py](Redis%20%26%20Caching%20Notes/L01_fundamentals.py) | Data types, persistence (RDB/AOF), expiration |
| [L02_caching_patterns.py](Redis%20%26%20Caching%20Notes/L02_caching_patterns.py) | Cache-aside/write-through/write-behind, stampede protection |
| [L03_sorted_sets_and_advanced.py](Redis%20%26%20Caching%20Notes/L03_sorted_sets_and_advanced.py) | ZSETs, leaderboards, HyperLogLog, Geo commands, Lua scripts |
| [L04_streams.py](Redis%20%26%20Caching%20Notes/L04_streams.py) | XADD/XREADGROUP, consumer groups, DLQ, watchdog reclaim |
| [L05_distributed_patterns.py](Redis%20%26%20Caching%20Notes/L05_distributed_patterns.py) | Distributed locks, session store, dedup, atomic rate limiter |
| [L06_leaderboards_and_queues.py](Redis%20%26%20Caching%20Notes/L06_leaderboards_and_queues.py) | Real-time leaderboards, priority/delayed/reliable queues |
| [L07_pub_sub_and_patterns.py](Redis%20%26%20Caching%20Notes/L07_pub_sub_and_patterns.py) | Pub/Sub, keyspace notifications, fan-out architecture |
| [L08_cluster_and_ha.py](Redis%20%26%20Caching%20Notes/L08_cluster_and_ha.py) | Redis Cluster horizontal scaling, persistence, memory tuning |
| [L09_clustering_and_sentinel.py](Redis%20%26%20Caching%20Notes/L09_clustering_and_sentinel.py) | Sentinel failover, hash slots, cross-slot limitations |
| [L10_production_patterns.py](Redis%20%26%20Caching%20Notes/L10_production_patterns.py) | Connection pooling, monitoring, memory/persistence tuning, ACLs |

---

### [Observability Notes](Observability%20Notes/) — Metrics, Logs, Traces, SLOs
Prometheus/PromQL through OpenTelemetry, chaos engineering, and full observability architecture.

| File | Topic |
|------|-------|
| [L01_fundamentals.py](Observability%20Notes/L01_fundamentals.py) | Three pillars, golden signals, SLI/SLO/SLA, cardinality |
| [L02_metrics_fundamentals.py](Observability%20Notes/L02_metrics_fundamentals.py) | Prometheus data model, PromQL, USE/RED methods |
| [L03_prometheus_and_metrics.py](Observability%20Notes/L03_prometheus_and_metrics.py) | Metric types, label cardinality rules, production FastAPI setup |
| [L04_logging_best_practices.py](Observability%20Notes/L04_logging_best_practices.py) | Structured logging, correlation IDs, log aggregation |
| [L05_distributed_tracing.py](Observability%20Notes/L05_distributed_tracing.py) | Trace/span model, context propagation, sampling strategies |
| [L06_alerting_and_slos.py](Observability%20Notes/L06_alerting_and_slos.py) | SLI/SLO/error budgets, multi-window burn-rate alerting |
| [L07_opentelemetry.py](Observability%20Notes/L07_opentelemetry.py) | OTel SDK, Collector pipeline, semantic conventions |
| [L08_apm_and_profiling.py](Observability%20Notes/L08_apm_and_profiling.py) | Continuous profiling, memory/CPU profiling, N+1 detection |
| [L09_chaos_engineering.py](Observability%20Notes/L09_chaos_engineering.py) | Fault injection, steady-state hypothesis, circuit breaker validation |
| [L10_production_observability_architecture.py](Observability%20Notes/L10_production_observability_architecture.py) | Full metrics/logs/traces pipeline, cost control, on-call workflow |

---

### [API Design Notes](API%20Design%20Notes/) — REST, gRPC, GraphQL, and Production APIs
REST principles through webhooks, rate limiting, and a full production API design checklist.

| File | Topic |
|------|-------|
| [L01_rest_principles.py](API%20Design%20Notes/L01_rest_principles.py) | Resource modeling, HTTP semantics, HATEOAS |
| [L02_versioning_and_openapi.py](API%20Design%20Notes/L02_versioning_and_openapi.py) | Versioning strategies, OpenAPI 3.1, Pydantic schema generation |
| [L03_grpc_and_protobuf.py](API%20Design%20Notes/L03_grpc_and_protobuf.py) | Protobuf messages, streaming RPCs, deadlines, error codes |
| [L04_graphql.py](API%20Design%20Notes/L04_graphql.py) | Schema/resolvers, N+1 + DataLoader, Apollo Federation |
| [L05_api_gateway.py](API%20Design%20Notes/L05_api_gateway.py) | Kong/AWS API Gateway, BFF pattern, auth at the gateway |
| [L06_webhooks_and_events.py](API%20Design%20Notes/L06_webhooks_and_events.py) | Signature verification, retry/backoff, CloudEvents |
| [L07_webhooks_and_async_apis.py](API%20Design%20Notes/L07_webhooks_and_async_apis.py) | Async operation patterns (202 + polling), idempotency, pagination |
| [L08_rate_limiting_and_throttling.py](API%20Design%20Notes/L08_rate_limiting_and_throttling.py) | Token/leaky bucket, distributed rate limiting with Redis Lua |
| [L09_api_security_and_performance.py](API%20Design%20Notes/L09_api_security_and_performance.py) | Security headers, SSRF blocking, compression, ETags |
| [L10_production_api_design.py](API%20Design%20Notes/L10_production_api_design.py) | Idempotency keys, pagination, contract testing, deprecation workflow |

---

### [Auth & Security Notes](Auth%20%26%20Security%20Notes/) — Authentication, Authorization, OWASP
Password hashing through OAuth2/OIDC, RBAC/OPA, secrets management, and full security architecture.

| File | Topic |
|------|-------|
| [L01_authentication_fundamentals.py](Auth%20%26%20Security%20Notes/L01_authentication_fundamentals.py) | bcrypt/argon2id, TOTP MFA, session security |
| [L02_jwt_and_tokens.py](Auth%20%26%20Security%20Notes/L02_jwt_and_tokens.py) | HS256/RS256, claims validation, refresh rotation, JWKS |
| [L03_oauth2_and_oidc.py](Auth%20%26%20Security%20Notes/L03_oauth2_and_oidc.py) | Authorization Code + PKCE, Client Credentials, OIDC discovery |
| [L04_owasp_top10.py](Auth%20%26%20Security%20Notes/L04_owasp_top10.py) | All OWASP Top 10 with vulnerable code + fix, side by side |
| [L05_rbac_and_authorization.py](Auth%20%26%20Security%20Notes/L05_rbac_and_authorization.py) | RBAC/ABAC/ReBAC, Casbin, OPA/Rego, row-level security |
| [L06_secrets_management.py](Auth%20%26%20Security%20Notes/L06_secrets_management.py) | Secret rotation/distribution patterns, never committing secrets |
| [L07_secrets_management.py](Auth%20%26%20Security%20Notes/L07_secrets_management.py) | Vault dynamic secrets, AWS Secrets Manager, K8s Secrets, leak detection |
| [L08_api_security_hardening.py](Auth%20%26%20Security%20Notes/L08_api_security_hardening.py) | Security headers, CORS, dependency scanning, container hardening |
| [L09_tls_and_network_security.py](Auth%20%26%20Security%20Notes/L09_tls_and_network_security.py) | TLS 1.3, cert-manager, Kubernetes NetworkPolicy |
| [L10_mtls_and_service_security.py](Auth%20%26%20Security%20Notes/L10_mtls_and_service_security.py) | Mutual TLS, SPIFFE/SPIRE, JWT service tokens, zero-trust mesh |
| [L11_security_architecture.py](Auth%20%26%20Security%20Notes/L11_security_architecture.py) | Defense in depth, zero trust, SBOM/cosign, STRIDE threat modeling |
| [L12_security_scanning_and_dependency_management.py](Auth%20%26%20Security%20Notes/L12_security_scanning_and_dependency_management.py) | Bandit SAST, Dependabot/SCA, remediating XSS/SSRF/LFI concretely |
| [L13_api_gateway_multitenant_isolation.py](Auth%20%26%20Security%20Notes/L13_api_gateway_multitenant_isolation.py) | Zuplo-style gateway tenant isolation, per-tenant rate limits, defense in depth |

---

### [Rust Notes](Rust%20Notes/) — Systems Programming with Memory Safety
Ownership/borrowing through async Tokio, Axum, unsafe/FFI, and production Rust.

| File | Topic |
|------|-------|
| [L01_ownership_and_borrowing.rs](Rust%20Notes/L01_ownership_and_borrowing.rs) | Move semantics, borrow checker, lifetimes, RAII |
| [L02_structs_enums_and_traits.rs](Rust%20Notes/L02_structs_enums_and_traits.rs) | Algebraic data types, traits, static vs dynamic dispatch, generics |
| [L03_error_handling.rs](Rust%20Notes/L03_error_handling.rs) | `Result`/`Option`, `?` operator, custom errors, `thiserror`/`anyhow` |
| [L04_concurrency.rs](Rust%20Notes/L04_concurrency.rs) | Threads, `Arc<Mutex<T>>`, channels, `Send`/`Sync` |
| [L05_async_and_tokio.rs](Rust%20Notes/L05_async_and_tokio.rs) | Futures, `tokio::spawn`, channels, `select!`, streams |
| [L06_axum_web_server.rs](Rust%20Notes/L06_axum_web_server.rs) | Router, extractors, shared state, Tower middleware |
| [L07_performance_and_unsafe.rs](Rust%20Notes/L07_performance_and_unsafe.rs) | Zero-cost abstractions, SIMD, raw pointers, FFI |
| [L08_production_rust.rs](Rust%20Notes/L08_production_rust.rs) | Cargo workspaces, `tracing`, Docker multi-stage, CI |

---

### [Edge Computing Notes](Edge%20Computing%20Notes/) — V8 Isolates, WASM, Edge AI
Cloudflare Workers/edge fundamentals through WebAssembly, edge AI inference, and production multi-CDN architecture.

| File | Topic |
|------|-------|
| [L01_concepts.js](Edge%20Computing%20Notes/L01_concepts.js) | V8 Isolates vs containers, edge use cases, provider landscape |
| [L02_cloudflare_workers.js](Edge%20Computing%20Notes/L02_cloudflare_workers.js) | KV, Durable Objects, R2, D1, Queues, Workers AI |
| [L03_webassembly.js](Edge%20Computing%20Notes/L03_webassembly.js) | WASM linear memory, WASI, Rust→WASM, Component Model |
| [L04_edge_ai_and_inference.js](Edge%20Computing%20Notes/L04_edge_ai_and_inference.js) | Quantization, ONNX Runtime Web, Workers AI, hybrid vector search |
| [L05_edge_caching.js](Edge%20Computing%20Notes/L05_edge_caching.js) | Cache-Control/SWR, surrogate keys, request collapsing, ESI |
| [L06_edge_security.js](Edge%20Computing%20Notes/L06_edge_security.js) | WAF, bot management, edge JWT validation, signed URLs |
| [L07_edge_networking.js](Edge%20Computing%20Notes/L07_edge_networking.js) | Anycast/BGP, HTTP/3 QUIC, Early Hints, origin shield |
| [L08_production_edge.js](Edge%20Computing%20Notes/L08_production_edge.js) | Multi-CDN failover, canary deploys, cost optimization, data residency |

---

### [eBPF Notes](eBPF%20Notes/) — Kernel-Level Observability, Networking, and Security
BPF fundamentals through XDP networking, Cilium, and production eBPF operations.

| File | Topic |
|------|-------|
| [L01_fundamentals.py](eBPF%20Notes/L01_fundamentals.py) | Verifier, JIT, program types, BPF maps, CO-RE/BTF |
| [L02_bcc_and_tracing.py](eBPF%20Notes/L02_bcc_and_tracing.py) | BCC Python API, kprobes/kretprobes, per-PID stats |
| [L03_network_observability.py](eBPF%20Notes/L03_network_observability.py) | Tracepoints, USDT, bpftrace one-liners, latency histograms |
| [L04_xdp_advanced.py](eBPF%20Notes/L04_xdp_advanced.py) | XDP verdicts, LPM trie blocklists, DSR load balancing |
| [L05_security_and_observability.py](eBPF%20Notes/L05_security_and_observability.py) | Falco rules, LSM BPF enforcement, Tetragon, container escape detection |
| [L06_cilium_and_kubernetes.py](eBPF%20Notes/L06_cilium_and_kubernetes.py) | kube-proxy replacement, L7 CiliumNetworkPolicy, Hubble |
| [L07_libbpf_and_go.py](eBPF%20Notes/L07_libbpf_and_go.py) | CO-RE, `cilium/ebpf`, bpf2go, ring buffer, pinning |
| [L08_production_ebpf.py](eBPF%20Notes/L08_production_ebpf.py) | Kernel compatibility, capabilities, verifier debugging, self-observability |

---

### [Platform Engineering Notes](Platform%20Engineering%20Notes/) — Internal Developer Platforms
Backstage/IDP through Terraform, Vault, OPA, service mesh, and platform maturity models.

| File | Topic |
|------|-------|
| [L01_idp_and_backstage.py](Platform%20Engineering%20Notes/L01_idp_and_backstage.py) | Software catalog, catalog-info.yaml, scaffolder templates |
| [L02_infrastructure_as_code.py](Platform%20Engineering%20Notes/L02_infrastructure_as_code.py) | Terraform state, modules, workspaces, Atlantis GitOps |
| [L03_secrets_and_vault.py](Platform%20Engineering%20Notes/L03_secrets_and_vault.py) | Dynamic DB secrets, auth methods, Vault Agent, auto-unseal |
| [L04_policy_as_code.py](Platform%20Engineering%20Notes/L04_policy_as_code.py) | Rego, Gatekeeper admission control, Conftest CI policy checks |
| [L05_platform_networking.py](Platform%20Engineering%20Notes/L05_platform_networking.py) | Istio mTLS, canary traffic splits, circuit breaking, Linkerd/Cilium |
| [L06_developer_experience.py](Platform%20Engineering%20Notes/L06_developer_experience.py) | DORA metrics, internal CLI, Tilt, preview environments |
| [L07_finops_and_cost.py](Platform%20Engineering%20Notes/L07_finops_and_cost.py) | Cost attribution, Kubecost allocation, spot strategy, waste detection |
| [L08_platform_maturity.py](Platform%20Engineering%20Notes/L08_platform_maturity.py) | Maturity model, Team Topologies, platform SLOs, reference architecture |

---

## Research & Hardware Specialization Track

A deeper, research-oriented track for going from zero to being able to build LLMs from scratch, quantize them, and eventually publish original work — separate from (and deeper than) the other domains, which are 8-lesson surveys. This one is 25 lessons across 8 phases because it targets genuine research/systems depth, not a survey.

### [LLM Quantization & Inference Notes](LLM%20Quantization%20%26%20Inference%20Notes/) — Build, Quantize, and Optimize LLMs From Scratch
From tensors and autograd through building a transformer from scratch, reproducing GPTQ/AWQ/SmoothQuant/GGUF, writing real Triton/CUDA kernels for a consumer GPU, understanding vLLM/llama.cpp internals, and structuring a publishable research contribution.

| File | Topic |
|------|-------|
| **Phase 1 — Deep Learning Foundations** | |
| [L01_tensors_and_autograd.py](LLM%20Quantization%20%26%20Inference%20Notes/L01_tensors_and_autograd.py) | Tensors as strided memory, autograd/backprop from scratch |
| [L02_linear_algebra_and_numerics.py](LLM%20Quantization%20%26%20Inference%20Notes/L02_linear_algebra_and_numerics.py) | Matmul cost, FP32/FP16/BF16 representation, outlier problem |
| [L03_attention_from_first_principles.py](LLM%20Quantization%20%26%20Inference%20Notes/L03_attention_from_first_principles.py) | Scaled dot-product & multi-head attention derived, positional encoding |
| **Phase 2 — Building an LLM From Scratch** | |
| [L04_tokenization_bpe.py](LLM%20Quantization%20%26%20Inference%20Notes/L04_tokenization_bpe.py) | Byte-pair encoding implemented from scratch, vocab size tradeoffs |
| [L05_transformer_block.py](LLM%20Quantization%20%26%20Inference%20Notes/L05_transformer_block.py) | RMSNorm, RoPE, grouped-query attention, SwiGLU — a real LLaMA-style block |
| [L06_training_loop_and_optimizers.py](LLM%20Quantization%20%26%20Inference%20Notes/L06_training_loop_and_optimizers.py) | AdamW derived from scratch, LR schedules, mixed precision |
| [L07_scaling_laws.py](LLM%20Quantization%20%26%20Inference%20Notes/L07_scaling_laws.py) | Chinchilla scaling laws, compute-optimal allocation, fitting power laws |
| [L08_finetuning_lora_qlora.py](LLM%20Quantization%20%26%20Inference%20Notes/L08_finetuning_lora_qlora.py) | Full FT memory cost, LoRA derived, QLoRA — the bridge to quantization |
| **Phase 3 — Quantization Fundamentals** | |
| [L09_quantization_math_fundamentals.py](LLM%20Quantization%20%26%20Inference%20Notes/L09_quantization_math_fundamentals.py) | Scale/zero-point math, symmetric vs asymmetric, error metrics |
| [L10_ptq_vs_qat.py](LLM%20Quantization%20%26%20Inference%20Notes/L10_ptq_vs_qat.py) | Post-training vs quantization-aware training, straight-through estimator |
| [L11_calibration_and_granularity.py](LLM%20Quantization%20%26%20Inference%20Notes/L11_calibration_and_granularity.py) | Activation calibration, per-tensor/channel/group tradeoffs |
| **Phase 4 — Modern Quantization Research** | |
| [L12_gptq.py](LLM%20Quantization%20%26%20Inference%20Notes/L12_gptq.py) | GPTQ reproduced from scratch — Hessian-based error compensation |
| [L13_awq.py](LLM%20Quantization%20%26%20Inference%20Notes/L13_awq.py) | AWQ reproduced from scratch — activation-aware channel rescaling |
| [L14_smoothquant_and_llm_int8.py](LLM%20Quantization%20%26%20Inference%20Notes/L14_smoothquant_and_llm_int8.py) | SmoothQuant and LLM.int8() — activation quantization (W8A8) |
| [L15_gguf_and_kquants.py](LLM%20Quantization%20%26%20Inference%20Notes/L15_gguf_and_kquants.py) | GGUF/K-quants — llama.cpp's hierarchical block quantization |
| [L16_sub_4bit_and_open_questions.py](LLM%20Quantization%20%26%20Inference%20Notes/L16_sub_4bit_and_open_questions.py) | NF4, ternary/BitNet, and genuinely open research questions |
| **Phase 5 — CUDA/Triton for a Consumer GPU** | |
| [L17_gpu_memory_hierarchy.py](LLM%20Quantization%20%26%20Inference%20Notes/L17_gpu_memory_hierarchy.py) | HBM/shared memory/registers, the roofline model |
| [L18_triton_fused_dequant_matmul.py](LLM%20Quantization%20%26%20Inference%20Notes/L18_triton_fused_dequant_matmul.py) | A real, runnable fused INT4 dequant-matmul Triton kernel |
| [L19_cuda_fundamentals.py](LLM%20Quantization%20%26%20Inference%20Notes/L19_cuda_fundamentals.py) | Threads/warps/blocks, shared-memory tiling, warp shuffles |
| **Phase 6 — Inference Engine Internals** | |
| [L20_kv_cache_and_paged_attention.py](LLM%20Quantization%20%26%20Inference%20Notes/L20_kv_cache_and_paged_attention.py) | KV cache memory cost, PagedAttention block management |
| [L21_continuous_batching_and_speculative_decoding.py](LLM%20Quantization%20%26%20Inference%20Notes/L21_continuous_batching_and_speculative_decoding.py) | In-flight batching, draft-model speculative decoding |
| [L22_inference_engine_architecture.py](LLM%20Quantization%20%26%20Inference%20Notes/L22_inference_engine_architecture.py) | How vLLM and llama.cpp are actually built, mapped to L17-L21 |
| **Phase 7 — Research Methodology & Publishing** | |
| [L23_reading_and_reproducing_papers.py](LLM%20Quantization%20%26%20Inference%20Notes/L23_reading_and_reproducing_papers.py) | Critical paper reading, statistically rigorous reproduction |
| [L24_writing_and_publishing_research.py](LLM%20Quantization%20%26%20Inference%20Notes/L24_writing_and_publishing_research.py) | Contribution scoping, paper structure, realistic venues |
| **Phase 8 — Capstone** | |
| [L25_capstone_design_and_roadmap.py](LLM%20Quantization%20%26%20Inference%20Notes/L25_capstone_design_and_roadmap.py) | Three scoped project templates tying every phase together |

---

### [Agentic AI & RAG Notes](Agentic%20AI%20%26%20RAG%20Notes/) — The Full Modern Agent/RAG Ecosystem
A fully self-contained, 26-lesson deep track covering every major framework in the modern agentic AI and RAG ecosystem — from embeddings and vector databases through RAG frameworks, agent orchestration paradigms, MCP, memory, security, observability, and a production reference architecture.

| File | Topic |
|------|-------|
| **Phase 1 — Foundations** | |
| [L01_llm_provider_landscape.py](Agentic%20AI%20%26%20RAG%20Notes/L01_llm_provider_landscape.py) | OpenAI, Anthropic, Gemini, Llama, Mistral, Cohere, Hugging Face, Ollama, vLLM |
| [L02_embeddings_fundamentals.py](Agentic%20AI%20%26%20RAG%20Notes/L02_embeddings_fundamentals.py) | OpenAI/Cohere/Voyage/Sentence Transformers/BGE embeddings, similarity metrics |
| [L03_vector_databases.py](Agentic%20AI%20%26%20RAG%20Notes/L03_vector_databases.py) | Pinecone, Weaviate, Qdrant, Milvus, Chroma, pgvector, Elasticsearch, Redis, MongoDB Atlas |
| [L04_rag_fundamentals.py](Agentic%20AI%20%26%20RAG%20Notes/L04_rag_fundamentals.py) | End-to-end RAG architecture, chunking, reranking, RAGAS evaluation |
| **Phase 2 — RAG Frameworks** | |
| [L05_langchain_and_embedchain.py](Agentic%20AI%20%26%20RAG%20Notes/L05_langchain_and_embedchain.py) | LangChain's RAG primitives + LCEL, EmbedChain's high-level API |
| [L06_llamaindex_deep_dive.py](Agentic%20AI%20%26%20RAG%20Notes/L06_llamaindex_deep_dive.py) | Index types, query engines, response synthesis |
| [L07_haystack.py](Agentic%20AI%20%26%20RAG%20Notes/L07_haystack.py) | Explicit pipeline/component graph, hybrid retrieval, extractive readers |
| [L08_dspy.py](Agentic%20AI%20%26%20RAG%20Notes/L08_dspy.py) | Signatures, modules, and automatic prompt optimization |
| [L09_unstructured_and_document_processing.py](Agentic%20AI%20%26%20RAG%20Notes/L09_unstructured_and_document_processing.py) | Unstructured.io layout-aware parsing, table extraction, OCR |
| [L10_graphrag.py](Agentic%20AI%20%26%20RAG%20Notes/L10_graphrag.py) | Knowledge graphs, community detection, Microsoft GraphRAG |
| [L11_ragflow_and_production_rag_pipelines.py](Agentic%20AI%20%26%20RAG%20Notes/L11_ragflow_and_production_rag_pipelines.py) | RAGFlow, incremental re-indexing, multi-tenant isolation |
| **Phase 3 — Agentic AI Orchestration Frameworks** | |
| [L12_agent_fundamentals.py](Agentic%20AI%20%26%20RAG%20Notes/L12_agent_fundamentals.py) | The agent loop, ReAct pattern, tools, when NOT to use an agent |
| [L13_langgraph_deep_dive.py](Agentic%20AI%20%26%20RAG%20Notes/L13_langgraph_deep_dive.py) | StateGraph, cycles, persistence, human-in-the-loop interrupts |
| [L14_crewai.py](Agentic%20AI%20%26%20RAG%20Notes/L14_crewai.py) | Role-based agents, tasks, sequential/hierarchical process |
| [L15_autogen_and_microsoft_agent_framework.py](Agentic%20AI%20%26%20RAG%20Notes/L15_autogen_and_microsoft_agent_framework.py) | Conversable agents, group chat, code execution, Microsoft Agent Framework |
| [L16_emerging_agent_orchestrators.py](Agentic%20AI%20%26%20RAG%20Notes/L16_emerging_agent_orchestrators.py) | LlamaIndex Workflows, AWS Strands Agents, CAMEL, Agno |
| [L17_multi_agent_patterns.py](Agentic%20AI%20%26%20RAG%20Notes/L17_multi_agent_patterns.py) | Choosing a paradigm; single-agent vs multi-agent |
| **Phase 4 — Vendor Agent SDKs** | |
| [L18_agent_sdks_landscape.py](Agentic%20AI%20%26%20RAG%20Notes/L18_agent_sdks_landscape.py) | OpenAI Agents SDK, PydanticAI, Semantic Kernel, Google ADK, AWS Bedrock Agents, Azure AI Foundry |
| **Phase 5 — Protocol, Memory, Tool Use** | |
| [L19_mcp_model_context_protocol.py](Agentic%20AI%20%26%20RAG%20Notes/L19_mcp_model_context_protocol.py) | MCP SDK, FastMCP, Registry, GitHub/Slack/Postgres/Drive/Filesystem servers |
| [L20_agent_memory.py](Agentic%20AI%20%26%20RAG%20Notes/L20_agent_memory.py) | Mem0, Zep, Letta, LangGraph Memory; Redis/Postgres/Neo4j/Chroma backends |
| [L21_tool_use_and_function_calling.py](Agentic%20AI%20%26%20RAG%20Notes/L21_tool_use_and_function_calling.py) | Tool schemas, selection at scale, error handling |
| **Phase 6 — Security, Observability, Automation** | |
| [L22_ai_agent_security.py](Agentic%20AI%20%26%20RAG%20Notes/L22_ai_agent_security.py) | Prompt injection, sandboxing, NeMo Guardrails, Presidio, Lakera Guard |
| [L23_agent_observability_and_evaluation.py](Agentic%20AI%20%26%20RAG%20Notes/L23_agent_observability_and_evaluation.py) | LangSmith, Langfuse, Arize Phoenix, Ragas, TruLens, Promptfoo, Helicone |
| [L24_agentic_automation_platforms.py](Agentic%20AI%20%26%20RAG%20Notes/L24_agentic_automation_platforms.py) | n8n, Zapier, Make, Power Automate, Temporal, Prefect, Kestra |
| **Phase 7 — Capstone** | |
| [L25_choosing_your_stack.py](Agentic%20AI%20%26%20RAG%20Notes/L25_choosing_your_stack.py) | A decision framework across the full ecosystem |
| [L26_production_agentic_architecture.py](Agentic%20AI%20%26%20RAG%20Notes/L26_production_agentic_architecture.py) | Full reference architecture wiring every layer together |

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
7.5. Data Engineering Notes — ETL/orchestration across Airflow, Databricks, Snowflake, ADF
8. Cloud Platforms Notes — where it all runs

**Then ML/AI:**

8.5. Data Science Fundamentals Notes — probability, inference, optimization, and visualization underneath everything that follows
9. ML Frameworks Notes — models
9.5. GPU Computing & Distributed Training Notes — what's actually happening under L05's `DDP`/AMP calls, and how to scale training across many GPUs
10. MLOps Notes — production ML systems
11. LLM Frameworks Notes — AI applications

**C++ / HFT track** is independent — start anytime, pairs well with systems programming interest.

**If you're targeting backend/platform roles specifically, follow the Backend & Future-Proof track:**

12. FastAPI & Python Web Notes — production Python web services
12.5. Full-Stack & Frontend Essentials Notes — React/Vue, Node/Express, Django, MongoDB, Elasticsearch, and the streaming UI patterns real AI products need
13. System Design Notes — architecture fundamentals before you need them under pressure
13.5. System Design Case Studies Notes — once fundamentals click, go deep on real products (Google Meet, Docs, Spotify, Shazam, Reddit) plus a from-scratch load-balancer/infra build
14. Go Notes — a second language for high-concurrency services
15. Redis & Caching Notes — the caching layer underneath most of the above
16. Observability Notes — you can't operate what you can't see
16.5. DevOps & SRE Practices Notes — config management, incident command, error budgets, on-call
17. API Design Notes — contracts between everything you've built
18. Auth & Security Notes — non-negotiable for anything production-facing

**Future-proofing (pick up as time allows, high leverage as the market shifts):**

19. Rust Notes — where performance-critical backend work is heading
20. Edge Computing Notes — WASM/V8-isolate compute is growing fast
21. eBPF Notes — the new foundation for observability/networking/security tooling
22. Platform Engineering Notes — the discipline tying all of the above together at org scale

**If your goal is research and hardware-efficiency work specifically (writing papers, building inference tooling):**

23. LLM Quantization & Inference Notes — an independent, self-contained 25-lesson deep track. Start anytime you have a GPU-capable machine and want to go deeper than the ML Frameworks/LLM Frameworks tracks; it assumes no prior transformer-internals knowledge and builds from tensors up through publishing.

**If your goal is building agentic AI / RAG products specifically:**

24. Agentic AI & RAG Notes — an independent, self-contained 26-lesson deep track covering the entire modern agent/RAG ecosystem end to end. No prior reading required — start here even before LLM Frameworks Notes if agentic/RAG systems are your primary focus; it re-covers RAG/agent fundamentals from scratch before going deep into the framework landscape.

---

## Prerequisites

- Python 3.11+ for Python/ML/MLOps/LLM/FastAPI/Redis/Observability/API Design/Auth/Platform Engineering/LLM Quantization/Data Engineering/Agentic AI & RAG/Data Science Fundamentals/DevOps & SRE Practices lessons
- Docker Desktop for Docker lessons
- `kubectl` + a cluster (minikube/kind/EKS) for Kubernetes, Platform Engineering, and eBPF/Cilium lessons
- PostgreSQL 15+ for SQL lessons
- AWS account (free tier covers most Cloud lessons)
- PySpark 3.4+ for Spark lessons
- Node.js 20+ and MongoDB/Elasticsearch local instances (or free-tier cloud accounts) for Full-Stack & Frontend Essentials Notes
- An NVIDIA GPU (consumer-class is enough for the code patterns; multi-GPU/cluster access is only needed to actually run the distributed examples at scale) for GPU Computing & Distributed Training Notes — code and concepts are readable/runnable in single-GPU or conceptual form without one
- Ansible installed locally (or a couple of free-tier VMs) for DevOps & SRE Practices Notes' configuration-management lessons
- g++ with C++20 support for C++ lessons
- Go 1.22+ for Go lessons
- Rust toolchain (rustup) for Rust lessons
- Node.js / a Cloudflare Workers account for Edge Computing lessons
- A Linux host with a modern kernel (5.10+) for eBPF lessons — WSL2 or a VM on Windows
- PyTorch + an NVIDIA GPU (consumer-class, e.g. RTX-series) for the CUDA/Triton kernel lessons (L17-L19) in LLM Quantization & Inference Notes — the rest of that domain's lessons run fine on CPU
- A Databricks workspace trial, Snowflake trial account, and Azure subscription (free tier) for Data Engineering Notes' platform-specific lessons
- An OpenAI/Anthropic/Cohere API key (or a local Ollama install) plus a vector DB account or local instance (Chroma/Qdrant) for Agentic AI & RAG Notes

---

*366 lessons across 32 domains. Built to take you from zero to senior/architect level — and, in the research tracks, to publishable original work and production-grade agentic systems.*

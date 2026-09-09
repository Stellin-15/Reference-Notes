# Message Queues & Brokers — In-Depth Reference

Kafka (covered separately) is a distributed LOG, not a traditional
message queue — this file covers the broker-model messaging systems most
companies also run for different use cases, plus the cloud-native managed options.


## 1. RABBITMQ — THE CLASSIC MESSAGE BROKER

RabbitMQ implements AMQP (Advanced Message Queuing Protocol) and is built
around EXCHANGES routing messages to QUEUES, not a partitioned log:
- **Direct exchange** — routes by exact routing key match (point-to-point).
- **Topic exchange** — routes by pattern match (`orders.*.created`) — the
  most flexible, common choice for complex routing needs.
- **Fanout exchange** — broadcasts to ALL bound queues, ignoring routing
  key entirely — the pub/sub equivalent.
- **Headers exchange** — routes based on message header attributes rather
  than the routing key — less common, used for more complex conditional routing.

**Once a message is CONSUMED and ACKed, it's gone** — unlike Kafka, where
consumed messages remain in the log for other consumers/replay. This is
the fundamental architectural difference: RabbitMQ is a queue (messages
are consumed once and removed); Kafka is a log (messages persist and can
be re-read by any number of independent consumer groups).

```python
# Basic RabbitMQ publish/consume (pika library)
channel.exchange_declare(exchange='orders', exchange_type='topic')
channel.queue_bind(exchange='orders', queue='billing_queue', routing_key='orders.*.created')
channel.basic_publish(exchange='orders', routing_key='orders.us.created', body=message)

def callback(ch, method, properties, body):
    process(body)
    ch.basic_ack(delivery_tag=method.delivery_tag)   # Explicit ack — message removed only after this
channel.basic_consume(queue='billing_queue', on_message_callback=callback)
```

**Dead-letter queues (DLQs)** — a message that fails processing
repeatedly (or exceeds a TTL) is routed to a DLQ instead of being lost or
retried forever — the standard pattern for "don't let one poison message
block or infinitely loop a queue."


## 2. AWS SQS & SNS

- **SQS** (Simple Queue Service) — a fully managed QUEUE, point-to-point:
  one message, consumed by ONE consumer (from a pool), then deleted. Standard
  queues are at-least-once delivery with best-effort ordering; FIFO queues
  add strict ordering and exactly-once processing within a message group,
  at lower throughput.
- **SNS** (Simple Notification Service) — pub/sub FAN-OUT: one message
  published, delivered to EVERY subscribed endpoint (SQS queues, Lambda,
  HTTP endpoints, email/SMS) — commonly paired with SQS per-subscriber
  ("SNS fan-out to SQS" pattern) so each downstream consumer gets its own
  durable, independently-consumable queue instead of a single shared one.
- **Visibility timeout** — SQS's core reliability mechanism: when a
  consumer receives a message, it becomes temporarily invisible to other
  consumers; if not deleted (acknowledged) within the timeout, it
  reappears for another consumer to try — the SQS equivalent of an ack/nack cycle.

```
Visibility timeout in practice:
1. Consumer A receives message, timeout starts (default 30s)
2. Consumer A processes for 45s (longer than timeout!)
3. At 30s, message becomes visible again — Consumer B ALSO receives it
4. Both A and B may now process the same message — a real, common bug
   source when processing time isn't accounted for in the timeout setting
5. Fix: extend visibility timeout via ChangeMessageVisibility for long-running jobs,
   or set the timeout comfortably above the expected p99 processing time
```


## 3. GOOGLE CLOUD PUB/SUB & AZURE SERVICE BUS/EVENT HUBS

- **Cloud Pub/Sub** — GCP's fully managed pub/sub, globally distributed by
  default, at-least-once delivery with ordering keys for per-key ordering guarantees.
- **Azure Service Bus** — queue AND topic/subscription (pub/sub) modes in
  one service, with sessions (ordered, related message grouping) and
  dead-lettering built in natively — Azure's answer combining
  SQS-and-SNS-like capability in a single product.
- **Azure Event Hubs** — Kafka-like (partitioned, log-based, replayable),
  positioned specifically for high-throughput event streaming rather than
  traditional queue semantics — the Azure-native Kafka alternative (also
  offers a Kafka-compatible protocol endpoint for easier migration).


## 4. NICHE BUT REAL

- **Competing consumers pattern** — multiple consumer instances pulling
  from the SAME queue to horizontally scale processing — the fundamental
  scaling pattern for any queue-based worker pool, whether SQS, RabbitMQ, or Kafka consumer groups.
- **Poison message handling** — a message that CONSISTENTLY fails
  processing (a malformed payload, a bug triggered by specific data) needs
  a MAX RETRY COUNT before moving to a dead-letter queue, or it can loop
  forever, continuously consuming worker capacity without ever succeeding.
- **Message ordering guarantees, precisely compared**: RabbitMQ queues are
  ordered by default (FIFO per queue, absent priority queues); SQS
  Standard is best-effort (NOT guaranteed) unless you pay the throughput
  cost of a FIFO queue; Kafka guarantees order only per-partition — three
  genuinely different default behaviors that matter a lot for
  correctness-sensitive event processing.
- **Backpressure & flow control** — when consumers can't keep up with
  producers, queue depth grows; RabbitMQ has publisher confirms/flow
  control that can slow producers when queues back up; cloud queues
  (SQS) simply buffer (up to service limits) — knowing whether your
  chosen broker applies backpressure to producers or just lets the queue
  grow unbounded is a real operational planning question.
- **Enterprise Service Bus (ESB) legacy** — older enterprise integration
  patterns (MuleSoft, IBM MQ, TIBCO) still run in large, established
  companies (especially banking/insurance/telco) — worth recognizing the
  category exists even though modern architectures have largely moved to
  lighter-weight brokers/event streaming.

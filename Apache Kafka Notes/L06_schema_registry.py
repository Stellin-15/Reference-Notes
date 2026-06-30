"""
============================================================
L06: Kafka Schema Registry
============================================================
WHAT: Schema Registry is a standalone service that stores and
      versions schemas (Avro, Protobuf, JSON Schema) for Kafka
      topics. Producers register schemas; consumers fetch them
      by ID embedded in each message.
WHY:  Without schemas, Kafka is a byte stream. Any producer can
      change its message format at any time. Consumers break
      silently (or noisily, at 3 AM). Schema Registry enforces
      a contract between producers and consumers, with versioning
      and compatibility rules that prevent breaking changes.
LEVEL: Advanced
============================================================
CONCEPT OVERVIEW:
  WIRE FORMAT (every Avro/Protobuf/JSONSchema Kafka message):
    Byte 0:    Magic byte = 0x00 (identifies Schema Registry encoding)
    Bytes 1-4: Schema ID (4-byte big-endian int)
    Bytes 5+:  Avro/Protobuf/JSON payload

  On PRODUCE:
    1. Producer has schema (string or .avsc file).
    2. Serializer POSTs schema to Registry: POST /subjects/{topic}-value/versions
    3. Registry returns schema_id (int). If schema already registered: returns existing id.
    4. Serializer encodes: [0x00][schema_id_4_bytes][avro_bytes]
    5. Message sent to Kafka broker.

  On CONSUME:
    1. Consumer receives raw bytes.
    2. Deserializer reads magic byte (0x00) → Schema Registry encoding.
    3. Reads 4-byte schema_id.
    4. Fetches schema from Registry: GET /schemas/ids/{schema_id}
       (cached after first fetch — very fast on subsequent messages)
    5. Deserializes payload using fetched schema.
    6. Returns Python dict (for Avro) or protobuf message object.

PRODUCTION USE CASE:
  A user_created event published by the auth service is consumed
  by: the email service, the analytics service, the CRM service.
  When the auth team adds a new optional field (phone_number),
  they register a new schema version. The Registry validates it
  as BACKWARD compatible (consumers using the old schema can still
  read the new messages — phone_number has a default, so old
  readers ignore it). No consumer changes required. No downtime.

COMMON MISTAKES:
  - Using NONE compatibility mode in production: any schema change
    is allowed, including ones that break every consumer.
  - Evolving schema without adding defaults to new fields: breaks
    BACKWARD compatibility — old consumers can't read new messages.
  - Forgetting to handle schema fetch errors (Registry is down):
    consumer should fail fast rather than commit corrupted offsets.
  - Using TopicNameStrategy and reusing topic names: if topic
    "users" is deleted and recreated with a different schema,
    old schema_ids may collide. Use separate subjects.
  - Putting schema Registry on the same JVM as Kafka broker: it's
    a separate service and should be independently scaled/HA'd.

REAL INCIDENT (fictional but representative):
  Team A deploys new producer that publishes user_events with
  field "user_age" renamed to "age". No Schema Registry in use.
  Team B's consumer crashes: KeyError: 'user_age'. 50 microservices
  consuming user_events. Half are broken. Hotfix takes 4 hours.
  With Schema Registry + BACKWARD compatibility: the rename would
  have been REJECTED at deploy time. Zero consumer downtime.
============================================================
"""

import json
import logging
from typing import Dict, Any, Optional, List

# confluent-kafka-python with Schema Registry support:
# pip install confluent-kafka[avro,schemaregistry]
from confluent_kafka import Producer, Consumer, KafkaError
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroSerializer, AvroDeserializer
from confluent_kafka.serialization import (
    SerializationContext, MessageField,
    StringSerializer, StringDeserializer
)
import requests   # for direct Schema Registry REST API calls

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)
log = logging.getLogger(__name__)


# ============================================================
# SECTION 1: AVRO SCHEMA DEFINITIONS
# ============================================================
# Avro schema is a JSON string describing the data structure.
# Each field has: name, type, optional doc, optional default.
#
# AVRO PRIMITIVE TYPES:
#   null, boolean, int, long, float, double, string, bytes
#
# AVRO COMPLEX TYPES:
#   record   — struct with named fields
#   array    — ["array", {"items": "string"}]
#   map      — {"type": "map", "values": "string"}
#   union    — ["null", "string"] (nullable field)
#   enum     — {"type": "enum", "symbols": ["A", "B"]}
#
# UNION FOR NULLABLE FIELDS:
#   ["null", "string"] means the field can be null OR a string.
#   The DEFAULT must match the FIRST type in the union.
#   So ["null", "string"] with default: null → nullable string.
#   This is the standard pattern for optional fields.

# Schema v1: initial user_created event
USER_CREATED_SCHEMA_V1 = """
{
  "type": "record",
  "namespace": "com.myapp.events",
  "name": "UserCreated",
  "doc": "Emitted when a new user account is created",
  "fields": [
    {
      "name": "user_id",
      "type": "string",
      "doc": "UUID of the newly created user"
    },
    {
      "name": "email",
      "type": "string",
      "doc": "User's email address (unique, not null)"
    },
    {
      "name": "username",
      "type": "string",
      "doc": "Display name chosen by the user"
    },
    {
      "name": "created_at_ms",
      "type": "long",
      "doc": "Unix timestamp in milliseconds when the account was created"
    }
  ]
}
"""

# Schema v2: adds optional phone_number field.
# BACKWARD COMPATIBLE because:
#   - New field has a default value (null).
#   - Old consumers (using v1 schema) simply ignore the new field.
#   - New consumers can read v1 messages: phone_number defaults to null.
#
# HOW TO EVOLVE BACKWARD COMPATIBLY:
#   ADD fields: always add with a default value.
#   REMOVE fields: only fields that have defaults can be removed.
#   RENAME fields: NOT backward compatible. Use aliases instead:
#     "aliases": ["old_field_name"]
#   CHANGE types: widening is OK (int→long). Narrowing (long→int) is NOT.

USER_CREATED_SCHEMA_V2 = """
{
  "type": "record",
  "namespace": "com.myapp.events",
  "name": "UserCreated",
  "doc": "Emitted when a new user account is created",
  "fields": [
    {
      "name": "user_id",
      "type": "string",
      "doc": "UUID of the newly created user"
    },
    {
      "name": "email",
      "type": "string",
      "doc": "User's email address (unique, not null)"
    },
    {
      "name": "username",
      "type": "string",
      "doc": "Display name chosen by the user"
    },
    {
      "name": "created_at_ms",
      "type": "long",
      "doc": "Unix timestamp in milliseconds when the account was created"
    },
    {
      "name": "phone_number",
      "type": ["null", "string"],
      "default": null,
      "doc": "Optional phone number for 2FA. Null if not provided."
    }
  ]
}
"""
# NOTE: ["null", "string"] union with default: null.
# This follows Avro convention: default value must match the
# FIRST type in the union array. null is first, so default is null.


# ============================================================
# SECTION 2: SCHEMA REGISTRY CLIENT SETUP
# ============================================================
# The SchemaRegistryClient talks to the Registry REST API.
# It caches schema lookups locally to minimize HTTP round-trips.
# After the first lookup, schema_id → schema is cached in-process.

def create_schema_registry_client(registry_url: str,
                                   api_key: Optional[str] = None,
                                   api_secret: Optional[str] = None) -> SchemaRegistryClient:
    """
    Create a Schema Registry client.
    For Confluent Cloud: use api_key + api_secret (basic auth).
    For self-hosted: usually no auth needed on internal network.
    """
    config = {'url': registry_url}

    if api_key and api_secret:
        # Confluent Cloud Schema Registry uses HTTP basic auth.
        config['basic.auth.user.info'] = f"{api_key}:{api_secret}"
        config['basic.auth.credentials.source'] = 'USER_INFO'

    return SchemaRegistryClient(config)


# ============================================================
# SECTION 3: AVRO PRODUCER WITH SCHEMA REGISTRY
# ============================================================
# The AvroSerializer:
#   1. On first produce: registers schema with Registry if not present.
#   2. Serializes Python dict → Avro binary using the schema.
#   3. Prepends magic byte (0x00) + schema_id (4 bytes).
#
# auto.register.schemas=True (default): serializer automatically
# registers the schema on first use. Set to False in production
# if you want CI/CD to pre-register and control schema lifecycle.

def create_avro_producer(bootstrap_servers: str,
                          schema_registry_client: SchemaRegistryClient,
                          schema_str: str) -> Producer:
    """
    Create a Kafka producer that serializes values as Avro.
    Keys are plain UTF-8 strings (no schema needed for simple keys).
    """
    # AvroSerializer converts Python dict → Avro bytes + schema header
    value_serializer = AvroSerializer(
        schema_registry_client=schema_registry_client,
        schema_str=schema_str,
        # to_dict: convert your domain object to a dict before serialization.
        # If your value is already a dict, set to None (identity function).
        to_dict=lambda obj, ctx: obj,
        conf={
            # Register schema if not already in Registry.
            # In prod: consider False + pre-register in CI pipeline.
            'auto.register.schemas': True,
        }
    )

    # Keys are simple strings (user_id). StringSerializer for UTF-8 encoding.
    key_serializer = StringSerializer('utf_8')

    producer_config = {
        'bootstrap.servers': bootstrap_servers,
        'enable.idempotence': True,
        'compression.type': 'lz4',
        'linger.ms': 5,
    }

    # The Producer itself is Kafka-agnostic. Serialization is done
    # in the produce() call via SerializationContext.
    from confluent_kafka.schema_registry.avro import AvroSerializer
    from confluent_kafka.serialization import SerializingProducer

    return SerializingProducer({
        **producer_config,
        'key.serializer': key_serializer,
        'value.serializer': value_serializer,
    })


def produce_user_created_event(producer, user_id: str, email: str,
                                username: str, phone: Optional[str] = None):
    """
    Produce a UserCreated event using Avro serialization.
    The SerializingProducer handles schema lookup, serialization,
    and header injection automatically.
    """
    event = {
        'user_id': user_id,
        'email': email,
        'username': username,
        'created_at_ms': int(__import__('time').time() * 1000),
        # v2 field: include if schema is v2, omit if v1
        # Avro will use the default (null) for missing optional fields.
    }
    if phone is not None:
        event['phone_number'] = phone   # optional: only include if provided

    producer.produce(
        topic='user-events',
        key=user_id,
        value=event,
        on_delivery=lambda err, msg: (
            log.error("Delivery failed: %s", err) if err
            else log.info("Delivered to partition %d offset %d",
                          msg.partition(), msg.offset())
        )
    )
    producer.poll(0)   # trigger delivery callbacks


# ============================================================
# SECTION 4: AVRO CONSUMER WITH SCHEMA REGISTRY
# ============================================================
# The AvroDeserializer:
#   1. Reads magic byte (asserts 0x00 — Schema Registry format).
#   2. Reads 4-byte schema_id.
#   3. Fetches schema from Registry by ID (cached after first fetch).
#   4. Deserializes Avro bytes → Python dict using fetched schema.
#
# READER vs WRITER SCHEMA:
#   Writer schema: the schema used when the message was produced (from Registry).
#   Reader schema: the schema the consumer wants to use (optional).
#   Avro does schema resolution: if fields differ between writer and reader,
#   Avro maps them using field names and aliases. This is how a v1 consumer
#   reads v2 messages (phone_number field is unknown → ignored using writer schema).

def create_avro_consumer(bootstrap_servers: str,
                          schema_registry_client: SchemaRegistryClient,
                          group_id: str) -> 'DeserializingConsumer':
    """
    Create a Kafka consumer that deserializes Avro values automatically.
    """
    from confluent_kafka.serialization import DeserializingConsumer

    value_deserializer = AvroDeserializer(
        schema_registry_client=schema_registry_client,
        # from_dict: convert deserialized dict to your domain object.
        # None means return raw dict (simpler, good for most cases).
        from_dict=lambda d, ctx: d,
    )

    key_deserializer = StringDeserializer('utf_8')

    return DeserializingConsumer({
        'bootstrap.servers': bootstrap_servers,
        'group.id': group_id,
        'key.deserializer': key_deserializer,
        'value.deserializer': value_deserializer,
        'enable.auto.commit': False,   # manual commit for reliability
        'auto.offset.reset': 'earliest',
        'isolation.level': 'read_committed',
    })


def run_user_event_consumer(bootstrap_servers: str, registry_url: str):
    """Consume and process UserCreated events with Avro deserialization."""
    registry_client = create_schema_registry_client(registry_url)
    consumer = create_avro_consumer(bootstrap_servers, registry_client, 'user-processor-v1')
    consumer.subscribe(['user-events'])

    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    log.error("Consumer error: %s", msg.error())
                continue

            # msg.value() is already a Python dict — deserialization is done.
            user_event: Dict[str, Any] = msg.value()
            log.info(
                "Received UserCreated | user_id=%s email=%s phone=%s",
                user_event.get('user_id'),
                user_event.get('email'),
                user_event.get('phone_number')   # None for v1 messages (default applied)
            )

            # Process... then commit.
            consumer.commit(message=msg)
    finally:
        consumer.close()


# ============================================================
# SECTION 5: SCHEMA REGISTRY REST API (DIRECT)
# ============================================================
# The Schema Registry exposes a REST API. Understanding it helps
# when debugging, writing CI checks, or using languages without
# Confluent client libraries.

REGISTRY_URL = "http://localhost:8081"


def list_subjects() -> List[str]:
    """
    List all subjects in the Schema Registry.
    A SUBJECT is a named container for schema versions.
    Default naming (TopicNameStrategy):
      {topic}-key   (for key schema)
      {topic}-value (for value schema)
    """
    response = requests.get(f"{REGISTRY_URL}/subjects")
    response.raise_for_status()
    return response.json()
    # Example: ["user-events-key", "user-events-value", "orders-value"]


def list_schema_versions(subject: str) -> List[int]:
    """List all version numbers for a subject."""
    response = requests.get(f"{REGISTRY_URL}/subjects/{subject}/versions")
    response.raise_for_status()
    return response.json()
    # Example: [1, 2, 3]


def get_schema_by_version(subject: str, version: int) -> Dict[str, Any]:
    """Fetch a specific schema version (returns id + schema JSON)."""
    response = requests.get(f"{REGISTRY_URL}/subjects/{subject}/versions/{version}")
    response.raise_for_status()
    return response.json()
    # Example: {"subject": "user-events-value", "version": 2, "id": 42, "schema": "{...}"}


def get_schema_by_id(schema_id: int) -> str:
    """
    Fetch schema by its numeric ID (the ID embedded in message bytes).
    This is what the Avro deserializer calls internally.
    """
    response = requests.get(f"{REGISTRY_URL}/schemas/ids/{schema_id}")
    response.raise_for_status()
    return response.json()['schema']


def register_schema(subject: str, schema_str: str) -> int:
    """
    Register a new schema version. Returns the schema ID.
    If the schema already exists (same content), returns the existing ID.
    If the schema is INCOMPATIBLE with the current compatibility mode,
    returns HTTP 409 Conflict.
    """
    payload = {"schema": schema_str}
    response = requests.post(
        f"{REGISTRY_URL}/subjects/{subject}/versions",
        headers={"Content-Type": "application/vnd.schemaregistry.v1+json"},
        json=payload
    )
    if response.status_code == 409:
        raise ValueError(f"Schema incompatible with {subject}: {response.json()}")
    response.raise_for_status()
    return response.json()['id']


def check_compatibility(subject: str, schema_str: str) -> bool:
    """
    Test if a new schema is compatible with the latest version
    in the registry WITHOUT registering it.
    Use this in CI/CD to gate schema changes before deploy.
    """
    payload = {"schema": schema_str}
    response = requests.post(
        f"{REGISTRY_URL}/compatibility/subjects/{subject}/versions/latest",
        headers={"Content-Type": "application/vnd.schemaregistry.v1+json"},
        json=payload
    )
    response.raise_for_status()
    return response.json().get('is_compatible', False)


# ============================================================
# SECTION 6: COMPATIBILITY MODES — DEEP DIVE
# ============================================================
# The compatibility mode is set PER SUBJECT (per topic per key/value).
# Change it via: PUT /config/{subject}  {"compatibility": "BACKWARD"}
#
# BACKWARD (most common default):
#   New schema can read data written with the OLD schema.
#   Old consumers (using old schema) CAN read new messages.
#   "Consumers can be upgraded first, then producers."
#   ALLOWED changes:
#     + Add field WITH default
#     + Remove field that HAD a default
#   FORBIDDEN changes:
#     - Add field WITHOUT default (old consumers fail on new messages)
#     - Remove required field (new schema can't read old messages)
#     - Change field type incompatibly
#
# FORWARD:
#   Old schema can read data written with the NEW schema.
#   New consumers CAN read messages from old producers.
#   "Producers can be upgraded first, then consumers."
#   ALLOWED changes:
#     + Add field (even without default — old consumers ignore it)
#     + Remove field WITH default
#
# FULL:
#   Both BACKWARD and FORWARD. Safest.
#   All changes allowed: add with default, remove with default.
#   This is the recommendation for mature, multi-team systems.
#
# BACKWARD_TRANSITIVE / FORWARD_TRANSITIVE / FULL_TRANSITIVE:
#   Check compatibility against ALL previous versions, not just latest.
#   Without TRANSITIVE: v3 is checked only against v2. v1 consumers
#   might still break. With TRANSITIVE: v3 must be compatible with
#   v1, v2, and all future consumers using any old version.
#
# NONE:
#   Any schema is accepted. No compatibility checking.
#   NEVER use in production. Exists only for testing/development.

def set_subject_compatibility(subject: str, mode: str):
    """
    Set the compatibility mode for a subject.
    mode: BACKWARD, FORWARD, FULL, FULL_TRANSITIVE, NONE, etc.
    """
    valid_modes = {
        'BACKWARD', 'BACKWARD_TRANSITIVE',
        'FORWARD', 'FORWARD_TRANSITIVE',
        'FULL', 'FULL_TRANSITIVE',
        'NONE'
    }
    if mode not in valid_modes:
        raise ValueError(f"Invalid mode {mode}. Valid: {valid_modes}")

    response = requests.put(
        f"{REGISTRY_URL}/config/{subject}",
        headers={"Content-Type": "application/vnd.schemaregistry.v1+json"},
        json={"compatibility": mode}
    )
    response.raise_for_status()
    log.info("Set compatibility for %s to %s", subject, mode)


# ============================================================
# SECTION 7: SUBJECT NAMING STRATEGIES
# ============================================================
# SUBJECT = where schemas are stored in the Registry.
# The naming strategy determines which subject a schema is
# registered under.
#
# TopicNameStrategy (default):
#   subject = {topic_name}-key or {topic_name}-value
#   Simple. All records on the same topic share one schema.
#   LIMITATION: one topic = one record type. Can't mix types on a topic.
#
# RecordNameStrategy:
#   subject = {record.namespace}.{record.name}
#   e.g., "com.myapp.events.UserCreated"
#   Multiple record types CAN share a topic. Schema tied to the type,
#   not the topic. Useful for event bus topics.
#
# TopicRecordNameStrategy:
#   subject = {topic_name}-{record.namespace}.{record.name}
#   Per-topic per-type isolation. Most granular.
#
# Change strategy on the Serializer:
#   conf={'subject.name.strategy': TopicRecordNameStrategy}

# Example showing RecordNameStrategy (config only, shown as comment):
# value_serializer = AvroSerializer(
#     schema_registry_client=schema_registry_client,
#     schema_str=USER_CREATED_SCHEMA_V2,
#     conf={
#         'auto.register.schemas': True,
#         'subject.name.strategy': RecordNameStrategy,
#     }
# )
# → registers under subject "com.myapp.events.UserCreated"
# → topic "user-events" can also have "com.myapp.events.UserDeleted"


# ============================================================
# SECTION 8: FULL MIGRATION EXAMPLE — V1 → V2
# ============================================================
# Scenario: Add optional phone_number field to UserCreated.
# Goal: zero downtime, no consumer changes required.

def migrate_schema_v1_to_v2():
    """
    Step-by-step v1 → v2 schema migration with compatibility check.
    Run this in CI before deploying the new producer.
    """
    subject = "user-events-value"

    # Step 1: Verify current compatibility mode is BACKWARD or FULL.
    resp = requests.get(f"{REGISTRY_URL}/config/{subject}")
    if resp.status_code == 404:
        # Subject has no override; use global default.
        resp = requests.get(f"{REGISTRY_URL}/config")
    current_mode = resp.json().get('compatibilityLevel', 'BACKWARD')
    log.info("Current compatibility mode for %s: %s", subject, current_mode)

    # Step 2: Test compatibility BEFORE registering.
    # This is the CI gate. Run this in your pipeline.
    is_compatible = check_compatibility(subject, USER_CREATED_SCHEMA_V2)
    if not is_compatible:
        raise RuntimeError(
            f"Schema v2 is NOT compatible with subject {subject}. "
            f"Cannot deploy. Fix the schema evolution."
        )
    log.info("Schema v2 is BACKWARD compatible with %s ✓", subject)

    # Step 3: Register v2 (only runs if CI gate passes).
    schema_id = register_schema(subject, USER_CREATED_SCHEMA_V2)
    log.info("Registered schema v2 with ID %d for subject %s", schema_id, subject)

    # Step 4: Deploy new producer (uses v2 schema → includes phone_number).
    # Existing consumers keep running with v1 schema.
    # When they receive v2 messages, the AvroDeserializer uses the
    # WRITER schema (v2, from Registry by ID) and the consumer
    # sees phone_number as null (default), which is correct.

    # Step 5: Eventually upgrade consumers to use v2 schema.
    # They now expose phone_number in their processing logic.
    # This can happen weeks after the producer upgrade.

    log.info("Migration complete. Consumers can upgrade at their own pace.")


# ============================================================
# SECTION 9: CI/CD SCHEMA VALIDATION PIPELINE
# ============================================================
# Best practice: pre-register schemas in CI, before the application
# container is built. This gates the pipeline on schema compatibility.
#
# .github/workflows/schema-check.yml:
#
#   - name: Check schema compatibility
#     run: |
#       pip install confluent-kafka[schemaregistry] requests
#       python scripts/validate_schemas.py
#
# scripts/validate_schemas.py:
#
#   from pathlib import Path
#   import requests, json, sys
#
#   REGISTRY = "https://schema-registry.prod.example.com"
#   SCHEMA_DIR = Path("schemas/")
#
#   failed = False
#   for schema_file in SCHEMA_DIR.glob("*.avsc"):
#       subject = schema_file.stem + "-value"
#       schema_str = schema_file.read_text()
#       resp = requests.post(
#           f"{REGISTRY}/compatibility/subjects/{subject}/versions/latest",
#           headers={"Content-Type": "application/vnd.schemaregistry.v1+json"},
#           json={"schema": schema_str}
#       )
#       if not resp.json().get("is_compatible", False):
#           print(f"INCOMPATIBLE: {schema_file} rejected for {subject}")
#           print(resp.json())
#           failed = True
#       else:
#           print(f"OK: {schema_file} is compatible with {subject}")
#
#   sys.exit(1 if failed else 0)
#
# This pattern catches breaking schema changes at PR time,
# not at 3 AM when the consumer crashes in production.

if __name__ == '__main__':
    # Demo: run migration validation
    try:
        migrate_schema_v1_to_v2()
    except Exception as e:
        log.error("Migration failed: %s", e)

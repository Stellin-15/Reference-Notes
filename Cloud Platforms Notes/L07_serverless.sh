#!/usr/bin/env bash
# ============================================================
# L07: Cloud Serverless Services
# ============================================================
# WHAT: Event-driven, fully managed compute and messaging
#       services where you pay for execution time, not idle
#       servers. Covers Lambda, API Gateway, SQS, SNS,
#       EventBridge, and Step Functions with real examples.
# WHY:  Serverless removes operational overhead (no OS patching,
#       no capacity planning, automatic scaling to zero). For
#       event-driven workloads, it dramatically reduces cost and
#       complexity versus always-on servers.
# LEVEL: Advanced
# ============================================================
# CONCEPT OVERVIEW:
#   Serverless ≠ no servers. It means YOU don't manage them.
#   AWS runs your code in containers that spin up on demand and
#   scale to thousands of concurrent executions automatically.
#   The core pattern: events trigger functions, functions write
#   to storage, services communicate via queues and topics.
#
# PRODUCTION USE CASE:
#   E-commerce order flow: customer places order → API Gateway
#   invokes Lambda → Lambda writes to DynamoDB → DynamoDB stream
#   triggers another Lambda → sends to SQS → warehouse Lambda
#   processes and triggers SNS notification to customer.
#   Zero servers to manage. Scales from 1 to 1M orders/day.
#
# COMMON MISTAKES:
#   - Functions longer than 15 min → break into Step Functions.
#   - Synchronous calls between Lambdas → use SQS/EventBridge.
#   - Lambda inside VPC without understanding cold start latency.
#   - Using groupByKey patterns with Kinesis/SQS (hotkey problem).
#   - Not setting DLQ (Dead Letter Queue) → failed messages lost.
#   - Deploying full monolith as a single Lambda → defeats purpose.
#   - Not setting reserved concurrency → one function can starve others.
# ============================================================

set -euo pipefail

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="us-east-1"

# ============================================================
# SECTION 1: AWS Lambda — Fundamentals
# ============================================================
# WHAT: Run code without provisioning servers. You upload a
#       function, define a trigger, and Lambda handles the rest:
#       allocation, scaling, patching, logging.
#
# CONFIGURATION OPTIONS:
#   Runtime: Python 3.12, Node.js 20, Java 21, Go 1.x,
#            .NET 8, Ruby 3.3, custom (bring your own).
#   Memory:  128MB to 10,240MB (10GB). CPU scales proportionally
#            with memory — more memory = more CPU. If your function
#            is CPU-bound, try bumping memory even if RAM isn't needed.
#   Timeout: 1 second to 15 minutes (900 seconds).
#            Default is 3 seconds — increase for anything non-trivial.
#   Storage: 512MB to 10GB ephemeral /tmp. Lost after invocation.
#   Layers:  Up to 5 Lambda Layers (shared deps, max 250MB unzipped).
#
# PRICING (2024):
#   Invocation cost: $0.20 per 1M invocations.
#   Duration cost:   $0.0000166667 per GB-second.
#   Example: 128MB function running 100ms = 0.0125 GB-seconds.
#            1M such invocations: $0.20 (requests) + $0.208 (duration)
#            = ~$0.41/month for 1M invocations. Extremely cheap.
#   Free tier: 1M invocations + 400,000 GB-seconds per month.
#
# TRIGGERS (things that invoke Lambda):
#   Synchronous (caller waits for result):
#     API Gateway, ALB, CloudFront, Cognito, Lex, Alexa,
#     SDK direct invocation (InvocationType=RequestResponse).
#   Asynchronous (Lambda retries on failure, has DLQ):
#     S3 events, SNS, EventBridge, SDK async invocation.
#   Stream-based (Lambda polls the stream):
#     DynamoDB Streams, Kinesis Data Streams.
#   Queue-based (Lambda polls and batches):
#     SQS, SQS FIFO, Amazon MQ, Kafka (MSK).
#
# GCP equivalent: Cloud Functions (Gen 2 = Cloud Run under the hood).
#   Key differences: max 60min timeout (Cloud Run), global HTTP triggers.
# Azure equivalent: Azure Functions. Durable Functions = Step Functions.
# ============================================================

# Deploy a Python Lambda function
# First, create the function code
mkdir -p /tmp/lambda_package

cat > /tmp/lambda_package/handler.py << 'PYTHON'
import json
import boto3
import os
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
s3 = boto3.client('s3')

TABLE_NAME = os.environ['TABLE_NAME']
BUCKET_NAME = os.environ['BUCKET_NAME']

def handler(event, context):
    """
    Lambda handler — entry point for every invocation.

    event:   dict with trigger-specific data (SQS message, API GW request, etc.)
    context: object with runtime info (function_name, memory_limit_in_mb,
             remaining_time_in_millis, aws_request_id for tracing).

    Return: dict for sync triggers (API GW expects statusCode + body).
            For async/stream: return value is ignored, raise exception to retry.
    """
    logger.info(f"Processing event: {json.dumps(event)}")
    logger.info(f"Request ID: {context.aws_request_id}")
    logger.info(f"Remaining time: {context.get_remaining_time_in_millis()}ms")

    # Process each SQS message in the batch
    # Lambda SQS trigger sends a batch of messages in event['Records']
    processed = []
    failed = []

    for record in event.get('Records', []):
        try:
            message = json.loads(record['body'])
            order_id = message['order_id']

            # Read from DynamoDB
            table = dynamodb.Table(TABLE_NAME)
            response = table.get_item(Key={'order_id': order_id})
            order = response.get('Item')

            if not order:
                logger.warning(f"Order not found: {order_id}")
                continue

            # Write processed result to S3
            s3.put_object(
                Bucket=BUCKET_NAME,
                Key=f"processed/{order_id}.json",
                Body=json.dumps(order),
                ContentType='application/json'
            )

            processed.append(order_id)
            logger.info(f"Processed order: {order_id}")

        except Exception as e:
            logger.error(f"Failed to process record: {e}")
            # For partial batch failure, add to failed list
            # SQS will retry only failed messages (requires batchItemFailures)
            failed.append({'itemIdentifier': record['messageId']})

    logger.info(f"Processed: {len(processed)}, Failed: {len(failed)}")

    # Return partial batch failure response — only failed messages are retried
    # Without this, ANY failure causes the ENTIRE batch to be retried
    return {'batchItemFailures': failed}
PYTHON

# Package the function
cd /tmp/lambda_package && zip -r /tmp/order_processor.zip . && cd -

# Create the Lambda function
LAMBDA_ARN=$(aws lambda create-function \
  --function-name "order-processor" \
  --runtime "python3.12" \
  --role "arn:aws:iam::${ACCOUNT_ID}:role/OrderProcessorLambdaRole" \
  --handler "handler.handler" \
  --zip-file "fileb:///tmp/order_processor.zip" \
  --timeout 300 \
  --memory-size 512 \
  --environment 'Variables={TABLE_NAME=orders,BUCKET_NAME=my-processed-data-bucket}' \
  --reserved-concurrent-executions 100 \
  --dead-letter-config '{"TargetArn":"arn:aws:sqs:us-east-1:'"$ACCOUNT_ID"':order-processor-dlq"}' \
  --tracing-config Mode=Active \  # X-Ray tracing
  --query 'FunctionArn' --output text)

echo "Lambda function: $LAMBDA_ARN"

# ============================================================
# SECTION 2: Cold Starts — Understanding and Mitigation
# ============================================================
# WHAT: The latency penalty when Lambda must initialize a new
#       execution environment from scratch.
#
# COLD START LIFECYCLE:
#   1. Download code package from S3 or ECR (~50-500ms).
#   2. Initialize runtime (Python runtime init: ~20-50ms).
#   3. Execute init code OUTSIDE the handler (import statements,
#      global variables, SDK clients — run ONCE per container).
#   4. Run handler (your actual function code).
#
# COLD START TIMES BY RUNTIME (approximate):
#   Python 3.12:     ~100-200ms cold start.
#   Node.js 20:      ~80-150ms cold start.
#   Java 21:         ~1-3 SECONDS cold start. JVM is heavy.
#   Go:              ~50-100ms (compiled binary, fast init).
#   .NET 8:          ~500ms-1s cold start.
#   Container image: +1-3s additional for image pull.
#
# MITIGATION STRATEGIES:
#
#   Provisioned Concurrency:
#     Pre-warm N execution environments. They are always ready.
#     Cost: you pay for those environments even if idle.
#     $0.015 per GB-hour of provisioned concurrency.
#     Use for: latency-sensitive APIs where p99 matters.
#     Set on an alias or version, not $LATEST.
#
#   SnapStart (Java only):
#     Take a snapshot of the initialized JVM state.
#     On cold start, restore from snapshot instead of re-initializing.
#     Reduces Java cold start from 2-3s to ~200ms.
#
#   Keep functions warm:
#     Use EventBridge to ping function every 5 min (poor man's warm).
#     Unreliable and wastes resources. Use Provisioned Concurrency instead.
#
#   Avoid VPC Lambda if possible:
#     VPC Lambda historically added 10-15s cold start (ENI setup).
#     AWS fixed this in 2019 with HyperPlane ENIs — now adds ~0ms.
#     But VPC Lambda cannot access internet without NAT Gateway.
#
#   Minimize package size:
#     Smaller package = faster download and init.
#     Use Lambda Layers for large deps (numpy, pandas, scipy).
#     Keep deployment package under 10MB zipped.
# ============================================================

# Configure Provisioned Concurrency on an alias (not $LATEST)
# First, publish a version (immutable snapshot of function code)
VERSION=$(aws lambda publish-version \
  --function-name "order-processor" \
  --description "v1 — initial production release" \
  --query 'Version' --output text)

# Create an alias pointing to this version
aws lambda create-alias \
  --function-name "order-processor" \
  --name "prod" \
  --function-version "$VERSION" \
  --description "Production alias"

# Set Provisioned Concurrency on the alias — 10 pre-warmed environments
# These start immediately, no cold start. Costs ~$0.015 * memory * 10 / 1000 per hour
aws lambda put-provisioned-concurrency-config \
  --function-name "order-processor" \
  --qualifier "prod" \
  --provisioned-concurrent-executions 10

# ============================================================
# SECTION 3: API Gateway
# ============================================================
# WHAT: Fully managed API front-end. Accept HTTP requests,
#       validate them, authorize them, route to Lambda/HTTP backends.
#
# THREE TYPES:
#
#   REST API (v1):
#     - Full featured. Request/response transformation.
#     - Usage plans and API keys. Custom authorizers.
#     - Cache responses (TTL, invalidation). Request validation.
#     - More expensive: $3.50 per million API calls.
#
#   HTTP API (v2):
#     - Simpler, 70% cheaper than REST API: $1.00/M calls.
#     - JWT authorizers, Lambda authorizers.
#     - No request/response transformation, no caching.
#     - Use this unless you need REST API-specific features.
#
#   WebSocket API:
#     - Persistent bidirectional connections.
#     - Routes: $connect, $disconnect, $default, custom routes.
#     - Backend can push messages to connected clients.
#     - Use for: real-time apps (chat, live dashboards, gaming).
#
# AUTH OPTIONS:
#   Lambda Authorizer: custom JWT/OAuth validation logic.
#   Cognito User Pools: built-in JWT validation.
#   IAM auth: use when caller is an AWS service or role (SigV4 signing).
#   API Keys + Usage Plans: rate limiting per API consumer.
#
# THROTTLING:
#   Default: 10,000 req/s per account per region (soft limit).
#   Per-stage and per-method limits configurable.
#   429 Too Many Requests returned when limit exceeded.
#
# GCP equivalent: Cloud Endpoints, Apigee (enterprise), API Gateway.
# Azure equivalent: Azure API Management (APIM) — more feature-rich.
# ============================================================

# Create an HTTP API (v2) for the orders service
HTTP_API_ID=$(aws apigatewayv2 create-api \
  --name "orders-api" \
  --protocol-type HTTP \
  --cors-configuration \
    AllowOrigins="https://app.example.com",AllowMethods="GET,POST,PUT",AllowHeaders="Content-Type,Authorization" \
  --query 'ApiId' --output text)

# Create a Lambda integration
INTEGRATION_ID=$(aws apigatewayv2 create-integration \
  --api-id "$HTTP_API_ID" \
  --integration-type AWS_PROXY \
  --integration-uri "arn:aws:apigateway:${REGION}:lambda:path/2015-03-31/functions/${LAMBDA_ARN}/invocations" \
  --payload-format-version "2.0" \
  --query 'IntegrationId' --output text)

# Add a JWT authorizer using Cognito User Pool
AUTHORIZER_ID=$(aws apigatewayv2 create-authorizer \
  --api-id "$HTTP_API_ID" \
  --name "CognitoAuthorizer" \
  --authorizer-type JWT \
  --identity-source '$request.header.Authorization' \
  --jwt-configuration \
    Audience="my-app-client-id",Issuer="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_POOL_ID" \
  --query 'AuthorizerId' --output text)

# Create routes with the authorizer
aws apigatewayv2 create-route \
  --api-id "$HTTP_API_ID" \
  --route-key "POST /orders" \
  --authorization-type JWT \
  --authorizer-id "$AUTHORIZER_ID" \
  --target "integrations/$INTEGRATION_ID"

aws apigatewayv2 create-route \
  --api-id "$HTTP_API_ID" \
  --route-key "GET /orders/{orderId}" \
  --authorization-type JWT \
  --authorizer-id "$AUTHORIZER_ID" \
  --target "integrations/$INTEGRATION_ID"

# Deploy to a stage
aws apigatewayv2 create-stage \
  --api-id "$HTTP_API_ID" \
  --stage-name "prod" \
  --auto-deploy

# Grant API Gateway permission to invoke Lambda
aws lambda add-permission \
  --function-name "order-processor" \
  --statement-id "apigateway-invoke" \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:${REGION}:${ACCOUNT_ID}:${HTTP_API_ID}/*/*/orders"

# ============================================================
# SECTION 4: SQS — Simple Queue Service
# ============================================================
# WHAT: Managed message queue. Decouples producers and consumers.
#       Producer writes to queue without caring if consumer is ready.
#       Consumer reads at its own pace. Handles traffic spikes.
#
# TWO TYPES:
#
#   STANDARD QUEUE:
#     - Unlimited throughput (nearly unlimited TPS).
#     - At-least-once delivery (rarely delivers duplicates — design
#       your consumer to be IDEMPOTENT: same message twice = same result).
#     - Best-effort ordering (not guaranteed).
#     - Use for: decoupling, high throughput, when ordering doesn't matter.
#
#   FIFO QUEUE (*.fifo suffix required):
#     - Exactly-once processing (deduplication).
#     - Strict ordering within a MessageGroupId.
#     - 300 TPS (3,000 with batching of 10).
#     - More expensive: $0.50/M vs $0.40/M for Standard.
#     - Use for: financial transactions, order state machines, anything
#       where duplicates or ordering issues cause correctness bugs.
#
# KEY SETTINGS:
#   Visibility Timeout: How long a message is hidden from other consumers
#     after being received. If consumer doesn't delete it before timeout,
#     message reappears. Set to > your processing time. Default: 30s.
#   Message Retention: 4 days default, 1-14 days.
#   DLQ (Dead Letter Queue): After maxReceiveCount failures, message
#     moves to DLQ. Use for debugging and alerting. Essential.
#   Long Polling: ReceiveMessage waits up to 20s for a message.
#     Reduces empty responses and cost vs short polling (immediate return).
#   Batch Size: Lambda reads 1-10,000 messages per invocation. More
#     efficient but larger failure blast radius. 10 is common.
#
# GCP equivalent: Pub/Sub (more like SNS but has pull subscriptions).
#                 Cloud Tasks (like SQS with scheduling and targeting).
# Azure: Azure Service Bus — Standard (like SQS), Premium (FIFO, sessions).
# ============================================================

# Create SQS queues: main queue + DLQ
# DLQ first (main queue references it)
DLQ_ARN=$(aws sqs create-queue \
  --queue-name "order-processor-dlq" \
  --attributes MessageRetentionPeriod=1209600 \   # 14 days — longer to investigate failures
  --query 'QueueUrl' --output text | xargs aws sqs get-queue-attributes \
  --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)

DLQ_URL=$(aws sqs create-queue \
  --queue-name "order-processor-dlq" \
  --attributes MessageRetentionPeriod=1209600 \
  --query 'QueueUrl' --output text)

MAIN_QUEUE_URL=$(aws sqs create-queue \
  --queue-name "order-processor" \
  --attributes '{
    "VisibilityTimeout": "300",
    "MessageRetentionPeriod": "345600",
    "ReceiveMessageWaitTimeSeconds": "20",
    "RedrivePolicy": "{\"deadLetterTargetArn\":\"'"$DLQ_ARN"'\",\"maxReceiveCount\":\"5\"}"
  }' \
  --query 'QueueUrl' --output text)

echo "Main queue: $MAIN_QUEUE_URL"
echo "DLQ: $DLQ_URL"

# Configure Lambda trigger from SQS with partial batch failure support
aws lambda create-event-source-mapping \
  --function-name "order-processor" \
  --qualifier "prod" \
  --event-source-arn "$(aws sqs get-queue-attributes \
    --queue-url "$MAIN_QUEUE_URL" \
    --attribute-names QueueArn \
    --query 'Attributes.QueueArn' --output text)" \
  --batch-size 10 \
  --maximum-batching-window-in-seconds 5 \
  --function-response-types ReportBatchItemFailures  # enables partial batch failure

# ============================================================
# SECTION 5: SNS — Simple Notification Service
# ============================================================
# WHAT: Pub/Sub messaging. One publisher, many subscribers.
#       Publisher sends to a Topic. All subscribers receive a copy.
#       Fan-out: one message → multiple parallel processors.
#
# USE CASES:
#   - Fan-out: S3 event → SNS → [SQS queue 1 (analytics),
#              SQS queue 2 (notification service), Lambda (audit log)].
#   - Alert broadcasting: GuardDuty finding → SNS → [email, PagerDuty, Slack].
#   - Mobile push: SNS can deliver to APNs (iOS) and FCM (Android).
#
# SUBSCRIPTION TYPES:
#   SQS, Lambda, HTTP/HTTPS, Email, Email-JSON, SMS, Platform (push).
#
# MESSAGE FILTERING:
#   Subscriber can filter messages using a policy. Only receives
#   messages matching their filter. Reduces wasted processing.
#   Example: order-service subscribes with filter {"event_type": ["ORDER_PLACED"]}.
#   Shipping-service subscribes with {"event_type": ["ORDER_SHIPPED"]}.
#
# FIFO TOPICS: Ordered delivery to SQS FIFO queues. Same 300 TPS limit.
#
# GCP equivalent: Pub/Sub — both push and pull subscriptions.
# Azure: Azure Service Bus Topics and Subscriptions (filter-based).
#        Azure Event Grid (event routing, like EventBridge).
# ============================================================

# Create an SNS topic for order events
ORDER_TOPIC_ARN=$(aws sns create-topic \
  --name "order-events" \
  --attributes DisplayName="Order Events" \
  --query 'TopicArn' --output text)

# Subscribe the SQS queue to receive all order events
aws sns subscribe \
  --topic-arn "$ORDER_TOPIC_ARN" \
  --protocol sqs \
  --notification-endpoint "$(aws sqs get-queue-attributes \
    --queue-url "$MAIN_QUEUE_URL" \
    --attribute-names QueueArn \
    --query 'Attributes.QueueArn' --output text)"

# Subscribe email for alerts (requires confirmation click)
# aws sns subscribe \
#   --topic-arn "$ORDER_TOPIC_ARN" \
#   --protocol email \
#   --notification-endpoint "ops-team@example.com"

# Add message filter — this SQS queue only gets ORDER_PLACED events
aws sns set-subscription-attributes \
  --subscription-arn "arn:aws:sns:us-east-1:${ACCOUNT_ID}:order-events:SUBSCRIPTION_ID" \
  --attribute-name FilterPolicy \
  --attribute-value '{"event_type": ["ORDER_PLACED", "ORDER_CANCELLED"]}'

# ============================================================
# SECTION 6: EventBridge — Event Bus and Scheduler
# ============================================================
# WHAT: Serverless event bus for routing events between AWS services,
#       your apps, and SaaS providers. Rules match event patterns
#       and route to targets. Think of it as the nervous system of
#       your event-driven architecture.
#
# THREE BUS TYPES:
#   Default bus: AWS service events (EC2 state changes, CodeBuild,
#                GuardDuty findings, etc.)
#   Custom bus:  Your application events. Create one per domain.
#   Partner bus: Events from SaaS providers (Datadog, Zendesk, Stripe).
#
# FEATURES:
#   Rules: Pattern-match events and route to 20+ target types.
#   Scheduled events: cron(0 12 * * ? *) or rate(5 minutes).
#   Event Archives: store all events for replay (e.g., reprocess after bug fix).
#   Schema Registry: auto-discover event schemas, generate code bindings.
#   Pipes: point-to-point integration with filtering and enrichment.
#
# WHEN TO USE EventBridge vs SNS vs SQS:
#   EventBridge: routing between many services, pattern matching,
#                scheduled tasks, AWS service integration.
#   SNS:         fan-out to many subscribers, mobile push.
#   SQS:         queue for load leveling, decoupling, at-least-once processing.
#   Use all three together in complex architectures.
#
# GCP equivalent: Eventarc, Cloud Scheduler (for cron).
# Azure: Azure Event Grid — very similar to EventBridge.
# ============================================================

# Create a custom event bus for the orders domain
aws events create-event-bus --name "orders-bus"

# Rule: route order completion events to Step Functions for fulfillment workflow
aws events put-rule \
  --name "OrderCompletedToFulfillment" \
  --event-bus-name "orders-bus" \
  --event-pattern '{
    "source": ["com.example.orders"],
    "detail-type": ["OrderCompleted"],
    "detail": {
      "status": ["PAID"],
      "total": [{"numeric": [">", 0]}]
    }
  }' \
  --state ENABLED

# Scheduled rule: daily cleanup job (cron runs at UTC midnight)
# cron(minutes hours day-of-month month day-of-week year)
aws events put-rule \
  --name "DailyOrderCleanup" \
  --schedule-expression "cron(0 0 * * ? *)" \
  --state ENABLED

# Add Lambda as target for the scheduled rule
aws events put-targets \
  --rule "DailyOrderCleanup" \
  --targets '[{
    "Id": "cleanup-lambda",
    "Arn": "'"$LAMBDA_ARN"'",
    "Input": "{\"action\":\"cleanup\",\"days_old\":90}"
  }]'

# Publish a custom event from your application code
aws events put-events \
  --entries '[{
    "Source": "com.example.orders",
    "DetailType": "OrderCompleted",
    "EventBusName": "orders-bus",
    "Detail": "{\"order_id\":\"ORD-12345\",\"status\":\"PAID\",\"total\":99.99,\"user_id\":\"USR-456\"}"
  }]'

# ============================================================
# SECTION 7: Step Functions — Workflow Orchestration
# ============================================================
# WHAT: Visual workflow orchestration for coordinating Lambda
#       functions, AWS services, and your own APIs into a
#       reliable, auditable state machine.
#
# WHY NOT JUST CHAIN LAMBDA CALLS:
#   - Hard to debug when step 7 of 12 fails.
#   - Error handling spaghetti code in every function.
#   - No built-in retry logic, timeout handling, or parallel execution.
#   - No audit trail of what ran and when.
#   Step Functions solves all of these.
#
# STATE TYPES:
#   Task:     Invoke a Lambda, API call, ECS task, etc.
#   Choice:   Conditional branching (if/switch logic).
#   Wait:     Pause for N seconds or until a timestamp.
#   Parallel: Run multiple branches concurrently.
#   Map:      Process each item in an array (like forEach in parallel).
#   Pass:     Pass input to output unchanged (useful for testing).
#   Succeed:  Terminal success state.
#   Fail:     Terminal failure state.
#
# TWO WORKFLOW TYPES:
#   Standard (default):
#     - Max 1 year duration. Exactly-once execution.
#     - Full history in console. Async execution.
#     - Cost: $0.025 per 1,000 state transitions.
#     - Use for: long-running processes, business workflows.
#   Express:
#     - Max 5 minutes. At-least-once (or at-most-once for sync).
#     - No history stored (use CloudWatch logs).
#     - Cost: $1 per million executions + $0.00001 per GB-second.
#     - Use for: high-volume, short-duration event processing.
#
# RETRY AND CATCH: Every Task state can have Retry rules
#   (backoff, max attempts) and Catch rules (go to error handling state).
#
# GCP equivalent: Cloud Workflows.
# Azure equivalent: Logic Apps (low-code), Durable Functions (code-first).
# ============================================================

# Define the state machine for order fulfillment
cat > /tmp/order-fulfillment-sm.json << 'STATEMACHINE'
{
  "Comment": "Order fulfillment workflow — from paid to shipped",
  "StartAt": "ValidateInventory",
  "States": {
    "ValidateInventory": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:us-east-1:ACCOUNT:function:validate-inventory",
      "Retry": [
        {
          "ErrorEquals": ["Lambda.ServiceException", "Lambda.AWSLambdaException"],
          "IntervalSeconds": 2,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["InsufficientInventoryError"],
          "Next": "NotifyOutOfStock"
        }
      ],
      "Next": "ProcessPaymentAndShipping"
    },
    "ProcessPaymentAndShipping": {
      "Type": "Parallel",
      "Branches": [
        {
          "StartAt": "ChargePayment",
          "States": {
            "ChargePayment": {
              "Type": "Task",
              "Resource": "arn:aws:lambda:us-east-1:ACCOUNT:function:charge-payment",
              "End": true
            }
          }
        },
        {
          "StartAt": "ReserveShipping",
          "States": {
            "ReserveShipping": {
              "Type": "Task",
              "Resource": "arn:aws:lambda:us-east-1:ACCOUNT:function:reserve-shipping",
              "End": true
            }
          }
        }
      ],
      "Next": "WaitForWarehouse"
    },
    "WaitForWarehouse": {
      "Type": "Wait",
      "Seconds": 3600,
      "Next": "CheckShipmentStatus"
    },
    "CheckShipmentStatus": {
      "Type": "Choice",
      "Choices": [
        {
          "Variable": "$.shipment_status",
          "StringEquals": "SHIPPED",
          "Next": "NotifyCustomerShipped"
        },
        {
          "Variable": "$.shipment_status",
          "StringEquals": "DELAYED",
          "Next": "NotifyCustomerDelay"
        }
      ],
      "Default": "WaitForWarehouse"
    },
    "NotifyCustomerShipped": {
      "Type": "Task",
      "Resource": "arn:aws:states:::sns:publish",
      "Parameters": {
        "TopicArn": "arn:aws:sns:us-east-1:ACCOUNT:order-events",
        "Message.$": "$.confirmation_message"
      },
      "End": true
    },
    "NotifyCustomerDelay": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:us-east-1:ACCOUNT:function:notify-delay",
      "End": true
    },
    "NotifyOutOfStock": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:us-east-1:ACCOUNT:function:notify-out-of-stock",
      "End": true
    }
  }
}
STATEMACHINE

# Create the state machine
SM_ARN=$(aws stepfunctions create-state-machine \
  --name "OrderFulfillmentWorkflow" \
  --definition file:///tmp/order-fulfillment-sm.json \
  --role-arn "arn:aws:iam::${ACCOUNT_ID}:role/StepFunctionsRole" \
  --type STANDARD \
  --query 'stateMachineArn' --output text)

echo "State machine: $SM_ARN"

# Start an execution (would normally be triggered by EventBridge)
aws stepfunctions start-execution \
  --state-machine-arn "$SM_ARN" \
  --name "order-ORD-12345-$(date +%s)" \
  --input '{"order_id":"ORD-12345","user_id":"USR-456","total":99.99}'

# ============================================================
# SECTION 8: Full Event-Driven Architecture Example
# ============================================================
# WHAT: Putting it all together — the complete serverless pipeline
#       for processing e-commerce orders.
#
# FLOW:
#   1. Customer uploads receipt image → S3 PutObject event.
#   2. S3 event publishes to SNS topic.
#   3. SNS fans out to two SQS queues:
#      a. OCR processing queue (Lambda reads, extracts order data with Textract).
#      b. Audit log queue (Lambda stores raw image metadata to DynamoDB).
#   4. OCR Lambda completes, publishes "OrderExtracted" event to EventBridge.
#   5. EventBridge rule routes to Step Functions state machine.
#   6. State machine orchestrates: validate → charge → ship → notify.
#   7. Final Lambda sends SNS notification → email/SMS to customer.
#
# This pattern gives you:
#   - Loose coupling (services don't call each other directly).
#   - Independent scaling (each Lambda scales for its own load).
#   - Resilience (SQS buffers during Lambda cold starts or errors).
#   - Auditability (EventBridge event archive, Step Functions history).
#   - Zero servers to manage.
# ============================================================

# S3 → SNS → SQS → Lambda pipeline
aws s3api put-bucket-notification-configuration \
  --bucket "my-receipts-bucket" \
  --notification-configuration '{
    "TopicConfigurations": [{
      "TopicArn": "'"$ORDER_TOPIC_ARN"'",
      "Events": ["s3:ObjectCreated:*"],
      "Filter": {
        "Key": {
          "FilterRules": [{"Name": "suffix", "Value": ".jpg"}]
        }
      }
    }]
  }'

echo "Serverless architecture configured."
echo "API: https://${HTTP_API_ID}.execute-api.${REGION}.amazonaws.com/prod"
echo "Queue: $MAIN_QUEUE_URL"
echo "Topic: $ORDER_TOPIC_ARN"
echo "State Machine: $SM_ARN"

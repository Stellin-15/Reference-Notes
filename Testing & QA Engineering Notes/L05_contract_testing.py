# ============================================================
# L05: Contract Testing — Verifying Microservices Agree, Without Full E2E Tests
# ============================================================
# WHAT: How to verify that a CONSUMER service and a PROVIDER service's
#       assumptions about each other's API actually match — WITHOUT
#       needing to run both services together, using consumer-driven
#       contract testing (the Pact framework being the most widely used tool).
# WHY: L03 covered integration testing against REAL dependencies (a real
#      database, a sandboxed API). Contract testing solves a RELATED but
#      DISTINCT problem specific to microservices: verifying
#      service-to-service API compatibility without the cost of
#      spinning up every dependent service for every test.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
THE PROBLEM CONTRACT TESTING SOLVES: in a microservices architecture, a
CONSUMER service (e.g. an order service) depends on a PROVIDER service's
API (e.g. a user service's `/users/{id}` endpoint) — if the provider
team changes their API's response shape (renaming a field, changing a
data type) WITHOUT the consumer team knowing, this breaks the consumer
IN PRODUCTION, often not discovered until then, since the two services'
teams may not even be aware of each other's specific usage patterns.
Full E2E tests (L04) COULD catch this, but require running BOTH real
services together for every test — impractical at scale with many
services and many consumer-provider relationships.

CONSUMER-DRIVEN CONTRACT TESTING (the Pact framework's approach) flips
the usual test-writing direction: the CONSUMER team writes tests
describing EXACTLY what they expect from the provider's API (e.g. "when
I call GET /users/123, I expect a response with fields `id`, `name`,
`email`") — running these tests generates a CONTRACT FILE (a formal,
machine-readable specification of these expectations) WITHOUT ever
calling the real provider (a MOCK provider, auto-generated from the
contract, stands in). This contract file is then PUBLISHED (commonly to
a shared "Pact Broker") for the PROVIDER team to consume.

PROVIDER VERIFICATION: the provider team's CI pipeline runs a SEPARATE
verification step — replaying every published contract from every
consumer against their ACTUAL, real API implementation, checking that
their real responses actually satisfy every consumer's stated
expectations. If the provider changes their API in a way that would
break a consumer's contract, THIS verification step fails IMMEDIATELY
in the provider's own CI pipeline, BEFORE the breaking change is ever
deployed — catching the exact class of bug full E2E tests would
eventually catch, but WITHOUT ever needing to run the consumer
service at all during this check.

WHY THIS IS FASTER AND MORE SCALABLE than full E2E testing for this
specific problem: verifying N consumer-provider relationships via full
E2E tests requires running potentially MANY real services together;
contract testing decouples this into two independent, fast checks (each
consumer verifies against a mock; each provider verifies against
published contracts) that can run INDEPENDENTLY in each team's own CI
pipeline, without ANY team needing the other's service running at all — a
genuine scalability advantage as the number of services grows.

WHAT CONTRACT TESTING DOES NOT REPLACE: it verifies API SHAPE/SCHEMA
compatibility — it does NOT verify end-to-end BUSINESS LOGIC correctness
across the full system (e.g. "does placing an order actually correctly
update inventory levels end-to-end") — that broader correctness question
still needs SOME level of E2E testing (L04) for the most critical flows,
just a much SMALLER set than would be needed to catch pure API-
compatibility breakage, which contract testing now handles far more efficiently.

PRODUCTION USE CASE:
An order service (consumer) and a user service (provider) both
participate in contract testing via a shared Pact Broker — when the
user-service team accidentally renames a field the order-service team
depends on, the user service's provider-verification step (running
against the ALREADY-PUBLISHED contract from the order service) fails
immediately in the user service's own CI pipeline — the breaking change
never reaches production, and the user-service team learns EXACTLY
which consumer's expectation broke and why, all without the order
service ever needing to be running during this check.

COMMON MISTAKES:
- Treating contract tests as a REPLACEMENT for all integration/E2E
  testing — contract tests verify API SHAPE compatibility specifically;
  they don't verify broader business-logic correctness across a full
  request flow, which still needs some E2E coverage for critical paths.
- Having the PROVIDER team write the contracts unilaterally, without
  consumer input — "consumer-driven" is the actual value: the contract
  reflects what CONSUMERS genuinely need, preventing the provider from
  either over-promising unused fields or missing fields a consumer
  actually depends on.
- Not integrating contract verification into the PROVIDER's CI pipeline
  as a BLOCKING check — if contract verification is optional/informational
  rather than a build-blocking gate, breaking changes can still reach
  production despite the contract test technically existing and having failed.
"""

import textwrap


# ------------------------------------------------------------------
# 1. The consumer side — defining expectations, generating a contract
# ------------------------------------------------------------------
CONSUMER_CONTRACT_EXAMPLE = textwrap.dedent("""\
    // Consumer (order-service) test, using Pact — defines EXACTLY what
    // it expects from the user-service provider, WITHOUT calling the real thing
    describe('Order service calling User service', () => {
      it('expects a user by ID to have id, name, and email fields', async () => {
        await provider.addInteraction({
          state: 'a user with ID 123 exists',
          uponReceiving: 'a request for user 123',
          withRequest: { method: 'GET', path: '/users/123' },
          willRespondWith: {
            status: 200,
            body: { id: 123, name: like('Alice'), email: like('alice@example.com') },
            // 'like()' means: match the TYPE, not the exact value —
            // the contract cares about SHAPE, not specific test data
          },
        });

        const user = await orderService.getUserById(123);
        expect(user.name).toBeDefined();
      });
    });
    // Running this test generates a CONTRACT FILE, published to a
    // shared Pact Broker for the user-service team to consume.
""")

# ------------------------------------------------------------------
# 2. The provider side — verifying against published contracts
# ------------------------------------------------------------------
PROVIDER_VERIFICATION_EXAMPLE = textwrap.dedent("""\
    // Provider (user-service) CI pipeline step — verifies its REAL API
    // against EVERY consumer's published contract
    describe('User service Pact verification', () => {
      it('satisfies all consumer contracts', async () => {
        await new Verifier({
          provider: 'user-service',
          providerBaseUrl: 'http://localhost:8080',   // the REAL running service
          pactBrokerUrl: 'https://pact-broker.internal',
          publishVerificationResult: true,
        }).verifyProvider();
        // This replays EVERY consumer's contract (order-service's, and any
        // other service's) against the REAL user-service implementation —
        // if a real response doesn't match a published expectation,
        // THIS step fails, blocking the deployment.
      });
    });
""")


def contract_testing_flow_illustration():
    print("Contract testing flow, end to end:\n")
    steps = [
        "1. Consumer (order-service) writes a test describing expected API shape",
        "2. Running that test generates a CONTRACT FILE (no real provider called)",
        "3. Contract is PUBLISHED to a shared Pact Broker",
        "4. Provider (user-service) CI runs VERIFICATION against its REAL API,",
        "   replaying EVERY published contract from EVERY consumer",
        "5. If the real API violates ANY contract -> provider's CI FAILS,",
        "   blocking deployment BEFORE the breaking change reaches production",
    ]
    for step in steps:
        print(f"  {step}")


if __name__ == "__main__":
    print(CONSUMER_CONTRACT_EXAMPLE)
    print(PROVIDER_VERIFICATION_EXAMPLE)
    contract_testing_flow_illustration()

"""
PRODUCTION CONTEXT EXAMPLE:
A large e-commerce platform with 40+ microservices adopts Pact-based
contract testing specifically because full E2E testing across every
consumer-provider pair had become prohibitively slow and flaky at that
scale — after adoption, a provider team's routine field rename is
caught by their OWN CI pipeline's provider-verification step within
minutes, referencing the SPECIFIC consumer contract it would have
broken — a bug that, before contract testing, would most likely have
only been discovered after deployment, via a consumer service failing in production.
"""

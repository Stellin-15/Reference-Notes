# Compliance & Governance — In-Depth Reference

Compliance frameworks from an ENGINEER's implementation perspective — what
each one actually requires you to build/change, not the legal text.


## 1. SOC 2

The most common compliance framework for B2B SaaS companies — a THIRD-
PARTY AUDIT (not self-certification) against 5 Trust Service Criteria:
Security (mandatory), Availability, Processing Integrity, Confidentiality,
Privacy (the last 4 are chosen based on what the company actually offers).

**What engineers actually build for it**: access reviews (quarterly proof
that who-has-access-to-what matches who-SHOULD-have-access — this is why
IAM/SCIM automation matters, manual reviews don't scale and auditors know it),
change management logs (every production change traceable to a ticket/PR/
approval — this is why "who approved this deploy" needs to be answerable
from CI/CD logs, not tribal memory), encryption at rest/in transit
(provable, not just "we use HTTPS" — actual TLS config and at-rest
encryption settings get checked), and incident response documentation (a
written, FOLLOWED runbook, not just an aspirational doc — auditors ask for
evidence of an actual past incident being handled per the documented process).

**Type I vs Type II**: Type I attests controls are DESIGNED correctly at a
point in time; Type II attests they were OPERATING effectively over a
period (typically 6-12 months) — Type II is what most enterprise customers
actually require before signing a contract, because Type I proves nothing
about whether controls are followed in practice.


## 2. GDPR (EU) & CCPA/CPRA (California)

Data-privacy regulations with real engineering implications, not just legal ones:
- **Right to erasure ("right to be forgotten")** — a user can request
  deletion of their personal data; engineering must be able to actually
  FIND and delete it across every system it lives in (primary DB, backups,
  analytics pipelines, third-party processors) — a genuinely hard
  distributed-systems problem most companies underestimate until the first real request.
- **Data minimization** — collect only what's actually needed; a schema
  with a `middle_name` field nobody uses is now a liability, not a
  convenience, under this principle.
- **Data residency** — GDPR restricts transferring EU personal data
  outside the EU without adequate safeguards — directly shapes multi-region
  cloud architecture decisions (which region actually stores EU user data,
  and does your DR/backup strategy accidentally replicate it elsewhere).
- **Breach notification timelines** — GDPR requires notifying regulators
  within 72 hours of becoming aware of a breach — this is why incident
  response runbooks need a "determine if this is a REPORTABLE breach"
  step, on a clock, not just "fix the technical issue."


## 3. PCI-DSS (PAYMENT CARD INDUSTRY)

Required for anyone storing/processing/transmitting credit card data. The
single most important engineering strategy: **scope reduction** — the
fewer systems that ever touch raw card data, the smaller (and cheaper) your
compliance burden. This is why most companies use a tokenization provider
(Stripe, Braintree) so RAW card numbers never touch their own servers at
all — the PCI scope shrinks to "we redirect to/embed a hosted field from a
compliant processor," not "we are ourselves a fully PCI-DSS Level 1 merchant."

**SAQ (Self-Assessment Questionnaire) levels** vary by how card data is
handled — SAQ A (fully outsourced, no card data touches your servers) is
dramatically simpler than SAQ D (full cardholder data environment) —
architecture decisions early on directly determine which SAQ level you're
stuck with for years.


## 4. HIPAA (US HEALTHCARE)

Governs PHI (Protected Health Information). Key engineering-relevant pieces:
- **BAAs (Business Associate Agreements)** — any third-party vendor
  touching PHI (your cloud provider, an analytics tool) needs a signed BAA
  — using a SaaS tool without one, even accidentally, is a real compliance gap.
- **Minimum necessary standard** — same spirit as GDPR's data minimization,
  specific to health data — a support tool shouldn't surface a patient's
  full medical history if it only needs their appointment time.
- **Audit logging requirements** — WHO accessed WHICH patient's record,
  WHEN, is a hard requirement, not a nice-to-have — shapes logging/audit-
  trail architecture from day one for any healthcare system.


## 5. GOVERNANCE FRAMEWORKS & PRACTICES

- **ISO 27001** — an international information-security management
  standard, broader than SOC2's US-centric audit model, often required for
  companies selling into European/global enterprise customers.
- **NIST Cybersecurity Framework (CSF)** — Identify, Protect, Detect,
  Respond, Recover — a widely-referenced STRUCTURE for organizing a
  security program, not itself a certification.
- **Data governance/classification** — labeling data by sensitivity
  (public/internal/confidential/restricted) and enforcing HANDLING RULES
  per tier programmatically (encryption requirements, access restrictions,
  retention periods) rather than leaving it to individual judgment.
- **Vendor/third-party risk management** — the process of assessing a
  new SaaS tool/vendor's own security posture BEFORE adopting it (security
  questionnaires, SOC2 report review) — the discipline that prevents
  "we adopted a tool with terrible security and inherited their breach risk."


## 6. NICHE BUT REAL

- **Compliance-as-code** — tools like Chef InSpec, AWS Config rules, or
  OPA policies that continuously and AUTOMATICALLY verify compliance
  controls (encryption enabled, MFA enforced, logging active) rather than
  a once-a-year manual audit scramble — the modern direction compliance
  tooling is moving, turning audits from a fire-drill into a continuously-passing check.
- **Data Processing Agreements (DPAs)** — the specific contractual
  mechanism required under GDPR whenever a company (controller) uses a
  third-party processor (a cloud provider, an email service) — engineers
  don't sign these, but the existence of a DPA constrains which vendors/
  regions are even LEGALLY usable for certain data.
- **Right-sizing compliance scope** — a genuinely important but
  underappreciated skill: architecting systems so SENSITIVE data (PCI/PHI/
  PII) is isolated into the smallest possible subsystem, so the REST of the
  company's systems don't inherit that subsystem's full compliance burden
  — the same "scope reduction" principle from PCI-DSS generalized across every framework.
- **Continuous compliance monitoring platforms** — Vanta, Drata, Secureframe
  — SaaS products that automate evidence collection for SOC2/ISO27001 by
  integrating directly with cloud accounts/IdPs/ticketing systems, now the
  default tooling choice for any company pursuing SOC2 rather than manual
  evidence-gathering spreadsheets.

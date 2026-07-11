# ============================================================
# L03: Azure AI Services — Speech, Vision, Language, Document Intelligence
# ============================================================
# WHAT: The pre-built, task-specific AI APIs (formerly "Cognitive
#       Services") — Speech (STT/TTS), Vision (OCR, image analysis),
#       Language (sentiment, NER, translation, summarization), and
#       Document Intelligence (structured extraction from forms/
#       invoices) — and when to reach for these instead of an LLM call.
# WHY: Job descriptions list these as a distinct skill from "LLM
#      integration" for a reason: they solve narrow, well-defined
#      problems faster, cheaper, and more deterministically than routing
#      everything through a general-purpose LLM prompt.
# LEVEL: Core (Lesson 3 of 8)
# ============================================================

"""
CONCEPT OVERVIEW:
It's tempting, once you have GPT-4o available, to route every task
through it — "summarize this call transcript," "extract the invoice
total," "what's the sentiment of this review." For many of these tasks
a purpose-built Azure AI Services API is the better engineering choice:

WHY NOT JUST USE THE LLM FOR EVERYTHING
------------------------------------------
- COST: A Speech-to-Text API call is priced per audio-second; an LLM
  call to transcribe the same audio (via a multimodal model) is
  typically far more expensive per unit of work, for a task that
  doesn't need reasoning.
- LATENCY: Task-specific APIs are optimized for their one job and
  usually respond faster than an LLM completion.
- DETERMINISM: Sentiment analysis or language detection from a
  dedicated classifier is far more consistent run-to-run than the same
  task phrased as an LLM prompt, which can vary with temperature,
  prompt wording, and model version changes.
- NO PROMPT INJECTION SURFACE: A structured API call (audio in,
  transcript out) has no natural-language instruction channel for an
  attacker to inject into, unlike a prompt-based approach.
The right default: use Azure AI Services for narrow, well-defined
extraction/classification tasks; reserve LLM calls for tasks that
genuinely require reasoning, synthesis, or open-ended generation.

SPEECH SERVICE
-----------------
- Speech-to-Text (STT): real-time streaming transcription or batch
  transcription of recorded audio, with speaker diarization (who said
  what) — the backbone of call-center "call analytics" use cases named
  explicitly in Azure AI job postings.
- Text-to-Speech (TTS): neural voices, including custom/branded voice
  creation for a consistent enterprise voice assistant identity.
- Speech Translation: real-time speech-to-speech or speech-to-text
  translation across languages in a single API call.

VISION SERVICE
------------------
- OCR (Read API): extract text from images/scanned documents.
- Image Analysis: captioning, tagging, object detection, and — a
  compliance-relevant feature — content moderation (detecting
  inappropriate imagery before it's stored or displayed).
- Face API: detection/verification (usage is restricted and gated by
  Microsoft's Responsible AI review for facial-recognition use cases —
  a direct instance of the Responsible AI governance theme in L08).

LANGUAGE SERVICE
--------------------
- Sentiment Analysis & Opinion Mining: not just positive/negative/
  neutral at the document level, but opinion mining that ties a
  sentiment to the specific aspect of text it's about (e.g. "the food
  was great but service was slow" -> two opinions, two sentiments).
- Named Entity Recognition (NER) & PII detection: extracting people,
  orgs, locations — and, critically for banking/regulated use cases, a
  dedicated PII detection/redaction capability that flags and can
  auto-redact sensitive data (SSNs, account numbers, health info)
  BEFORE that text is logged, stored, or forwarded to an LLM prompt.
- Text Summarization (extractive and abstractive) as a standalone
  service, distinct from asking an LLM to summarize.
- Translation.

DOCUMENT INTELLIGENCE (formerly Form Recognizer)
----------------------------------------------------
Structured extraction from semi-structured documents — invoices,
receipts, ID documents, and CUSTOM document types you train a model on
by providing labeled examples. This is the standard tool for "extract
the total, date, and line items from this invoice" — a task an LLM
CAN do via a vision-capable model and a careful prompt, but Document
Intelligence returns typed, schema-validated fields with confidence
scores per field, which is far more reliable for downstream automation
than parsing free-text LLM output.

PRODUCTION USE CASE:
A bank's call-center pipeline uses Speech Service for real-time
transcription with diarization (STT), Language Service's PII detection
to redact account numbers and SSNs from the transcript BEFORE it's
stored or sent anywhere else, Language Service's sentiment/opinion
mining for a per-call sentiment score, and only THEN — for the subset
of calls flagged high-risk or negative-sentiment — escalates the
redacted transcript to an LLM call (L02) for a nuanced compliance
summary. Most of the pipeline never touches an LLM at all.

COMMON MISTAKES:
- Reaching for an LLM prompt to do sentiment analysis, NER, or
  translation when a dedicated Language Service call is cheaper, faster,
  and more deterministic for the same task.
- Sending raw, unredacted transcripts or documents containing PII into
  an LLM prompt when a PII-detection pass could have redacted sensitive
  fields first — a real compliance exposure in regulated environments.
- Using Document Intelligence's generic "prebuilt" model for a
  domain-specific document type (e.g. a bank's own loan application
  form) instead of training a CUSTOM model on labeled examples — the
  prebuilt model's field extraction accuracy on non-standard layouts is
  meaningfully worse.
- Not checking confidence scores returned by extraction APIs — treating
  a low-confidence field extraction the same as a high-confidence one,
  when the right behavior is often "flag for human review" below a
  threshold.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Speech-to-Text with diarization (call-center transcription)
# ------------------------------------------------------------------
SPEECH_TO_TEXT_EXAMPLE = textwrap.dedent("""\
    import azure.cognitiveservices.speech as speechsdk

    speech_config = speechsdk.SpeechConfig(subscription=key, region="uaenorth")
    speech_config.set_property(
        speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode, "Continuous"
    )
    # Diarization: distinguishes speaker 1 (agent) from speaker 2 (customer)
    # in a single audio stream -- essential for call-analytics use cases.
    conversation_transcriber = speechsdk.transcription.ConversationTranscriber(
        speech_config=speech_config,
        audio_config=speechsdk.audio.AudioConfig(filename="call_recording.wav"),
    )

    transcript_segments = []

    def handle_transcribed(evt):
        transcript_segments.append({
            "speaker": evt.result.speaker_id,
            "text": evt.result.text,
            "offset_ms": evt.result.offset / 10_000,
        })

    conversation_transcriber.transcribed.connect(handle_transcribed)
    conversation_transcriber.start_transcribing_async().get()
""")

# ------------------------------------------------------------------
# 2. PII detection/redaction BEFORE anything touches an LLM prompt
# ------------------------------------------------------------------
PII_REDACTION_EXAMPLE = textwrap.dedent("""\
    from azure.ai.textanalytics import TextAnalyticsClient
    from azure.core.credentials import AzureKeyCredential

    client = TextAnalyticsClient(endpoint=endpoint, credential=AzureKeyCredential(key))

    result = client.recognize_pii_entities([transcript_text])[0]
    redacted_transcript = result.redacted_text   # PII replaced with ****

    for entity in result.entities:
        audit_log.info(f"Redacted {entity.category} at confidence {entity.confidence_score}")

    # Only the REDACTED text is ever forwarded to an LLM prompt (L02) --
    # raw PII never leaves this boundary.
    summary = call_azure_openai_summarize(redacted_transcript)
""")

# ------------------------------------------------------------------
# 3. Sentiment + opinion mining (aspect-level, not just document-level)
# ------------------------------------------------------------------
OPINION_MINING_EXAMPLE = textwrap.dedent("""\
    result = client.analyze_sentiment(
        [redacted_transcript], show_opinion_mining=True
    )[0]

    print(f"Overall sentiment: {result.sentiment}")   # positive/negative/mixed/neutral
    for sentence in result.sentences:
        for opinion in sentence.mined_opinions:
            # e.g. target="hold time" sentiment="negative"
            #      target="agent"     sentiment="positive"
            print(f"  {opinion.target.text}: {opinion.target.sentiment}")
""")

# ------------------------------------------------------------------
# 4. Document Intelligence — structured extraction with confidence scores
# ------------------------------------------------------------------
DOCUMENT_INTELLIGENCE_EXAMPLE = textwrap.dedent("""\
    from azure.ai.documentintelligence import DocumentIntelligenceClient

    client = DocumentIntelligenceClient(endpoint=endpoint, credential=credential)
    poller = client.begin_analyze_document(
        "prebuilt-invoice", document=invoice_bytes    # or a CUSTOM trained model id
    )
    result = poller.result()

    for document in result.documents:
        total = document.fields.get("InvoiceTotal")
        if total and total.confidence < 0.7:
            # Below-threshold confidence -> route to human review,
            # never silently trust a low-confidence extracted field.
            queue_for_human_review(document, field="InvoiceTotal")
        else:
            ingest_invoice_total(total.value_currency.amount)
""")

TASK_TO_SERVICE_GUIDE = {
    "Call transcription + diarization": "Speech Service (STT)",
    "Redact SSNs/account numbers before logging": "Language Service (PII detection)",
    "Per-call sentiment score": "Language Service (sentiment + opinion mining)",
    "Extract invoice total/date/line items": "Document Intelligence",
    "Open-ended compliance summary of a flagged call": "Azure OpenAI (L02) -- needs reasoning",
}


if __name__ == "__main__":
    print(SPEECH_TO_TEXT_EXAMPLE)
    print(PII_REDACTION_EXAMPLE)
    print(OPINION_MINING_EXAMPLE)
    print(DOCUMENT_INTELLIGENCE_EXAMPLE)
    print("=== Task -> service guide ===")
    for task, service in TASK_TO_SERVICE_GUIDE.items():
        print(f"{task}: {service}")

"""
PRODUCTION CONTEXT EXAMPLE:
A bank's loan-processing pipeline trains a CUSTOM Document Intelligence
model on 200 labeled examples of its own loan application form (the
prebuilt invoice/receipt models don't match this layout), extracts
applicant fields with per-field confidence scores, auto-routes any
field below 85% confidence to a human reviewer queue, and only invokes
an LLM call at the very end of the pipeline to draft a plain-language
summary of the application for the underwriter -- reasoning is reserved
for the one step that actually needs it.
"""

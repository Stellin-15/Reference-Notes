# ============================================================
# L05: LangChain's RAG Primitives, and EmbedChain's Higher-Level Abstraction
# ============================================================
# WHAT: LangChain's core RAG-building blocks (document loaders, text
#       splitters, retrievers, chains, LCEL composition) and EmbedChain's
#       much higher-level "RAG in a few lines" API — two different
#       altitudes of abstraction over the same L04 fundamentals.
# WHY: LangChain is the most widely used framework for GLUING together
#      models, retrievers, and prompts — nearly every other framework in
#      this domain either builds on it, integrates with it, or
#      deliberately positions itself as an alternative to it. Knowing
#      its primitives is close to a prerequisite for the RAG framework
#      ecosystem generally.
# LEVEL: Intermediate (Phase 2 of 7 — RAG Frameworks)
# ============================================================

"""
CONCEPT OVERVIEW:
LangChain provides composable pieces for EVERY stage of the RAG pipeline
from L04: DOCUMENT LOADERS (ingest from PDFs, web pages, databases,
hundreds of source types via a consistent interface), TEXT SPLITTERS
(implementing chunking strategies — `RecursiveCharacterTextSplitter` is
LangChain's implementation of the recursive/cascading chunking approach
from L04), VECTOR STORE integrations (a consistent interface across
Pinecone/Qdrant/Chroma/pgvector/etc. from L03), and RETRIEVERS (wrapping
a vector store's search behind a standard `.invoke()` interface, so
swapping the underlying vector store doesn't require rewriting your
retrieval-calling code).

LCEL (LangChain Expression Language) is LangChain's composition syntax —
chaining components with the `|` (pipe) operator, similar in spirit to
Unix pipes: `prompt | model | output_parser` reads as "build a prompt,
send it to the model, parse the output," with each stage's output
becoming the next stage's input automatically. This replaced the older,
more verbose class-based "Chain" objects (`LLMChain`, `RetrievalQA`) as
the recommended way to compose RAG pipelines in modern LangChain.

EMBEDCHAIN sits at a MUCH higher level of abstraction: instead of
composing loaders/splitters/retrievers/chains yourself, you call
`app.add(source)` to ingest a document and `app.query(question)` to get
an answer — EmbedChain handles chunking, embedding, storage, retrieval,
and generation internally with sensible defaults. This trades
CONTROL/CUSTOMIZATION (you can't easily swap out individual pipeline
stages) for SPEED of getting a working RAG system running, making it a
reasonable choice for prototyping or simple use cases where LangChain's
full composability isn't needed.

PRODUCTION USE CASE:
A team prototypes a RAG proof-of-concept in an afternoon using EmbedChain
(`app.add()` a handful of PDFs, `app.query()` immediately works) to
validate the PRODUCT idea with stakeholders, then rebuilds the validated
concept in LangChain (or a more specialized framework from later
lessons) once they need custom chunking logic, a specific reranking
step, or fine-grained control EmbedChain's high-level API doesn't expose.

COMMON MISTAKES:
- Reaching for LangChain's full composability for a genuinely simple,
  fixed use case where EmbedChain's higher-level API would get the same
  result with far less code to maintain — not every RAG system needs
  maximum flexibility.
- The opposite mistake: starting a project in EmbedChain and hitting a
  customization wall (needing a specific reranking strategy, a custom
  retrieval filter) that its high-level API doesn't expose, requiring a
  late rewrite into a more composable framework — worth judging your
  customization needs BEFORE choosing the abstraction level.
- Using LangChain's older `Chain` classes (`RetrievalQA`, `LLMChain`) in
  new code instead of LCEL — the older classes still work but are no
  longer where LangChain's own development focus/documentation emphasis is.
"""

import textwrap


# ------------------------------------------------------------------
# 1. LangChain's RAG-building primitives
# ------------------------------------------------------------------
LANGCHAIN_LOADER_AND_SPLITTER = textwrap.dedent("""\
    from langchain_community.document_loaders import PyPDFLoader
    from langchain.text_splitter import RecursiveCharacterTextSplitter

    loader = PyPDFLoader("handbook.pdf")
    documents = loader.load()   # a consistent Document interface across
                                  # hundreds of source-type loaders

    # LangChain's implementation of the recursive/cascading chunking
    # strategy from L04 — tries paragraph breaks first, falls back to
    # sentence/word boundaries as needed.
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_documents(documents)
""")

LANGCHAIN_VECTORSTORE_AND_RETRIEVER = textwrap.dedent("""\
    from langchain_openai import OpenAIEmbeddings
    from langchain_community.vectorstores import Qdrant

    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    vectorstore = Qdrant.from_documents(chunks, embeddings, url="http://localhost:6333")

    # .as_retriever() wraps the vector store behind a STANDARD interface
    # — swapping Qdrant for Pinecone/Chroma/pgvector later means changing
    # ONE line above, not every place retrieval is called.
    retriever = vectorstore.as_retriever(search_kwargs={"k": 5})
""")

# ------------------------------------------------------------------
# 2. LCEL — composing a full RAG chain with the pipe operator
# ------------------------------------------------------------------
LCEL_RAG_CHAIN = textwrap.dedent("""\
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.runnables import RunnablePassthrough
    from langchain_openai import ChatOpenAI

    prompt = ChatPromptTemplate.from_template(
        "Answer using ONLY this context:\\n{context}\\n\\nQuestion: {question}"
    )
    model = ChatOpenAI(model="gpt-4o")

    def format_docs(docs):
        return "\\n\\n".join(d.page_content for d in docs)

    # LCEL composition: retriever's output is formatted and fed into the
    # prompt's {context} slot, the original question passes through
    # unchanged into {question}, then the assembled prompt flows to the
    # model, then to a parser that extracts the plain string response.
    rag_chain = (
        {"context": retriever | format_docs, "question": RunnablePassthrough()}
        | prompt
        | model
        | StrOutputParser()
    )

    answer = rag_chain.invoke("How do I request a refund?")
    # Every stage is independently swappable: change `model` to Anthropic's
    # ChatAnthropic, change `retriever` to a different vector store, without
    # restructuring the surrounding chain — this composability is LCEL's
    # entire value proposition over hand-writing the equivalent glue code.
""")

# ------------------------------------------------------------------
# 3. EmbedChain — the high-level, few-lines-of-code alternative
# ------------------------------------------------------------------
EMBEDCHAIN_EXAMPLE = textwrap.dedent("""\
    from embedchain import App

    app = App()

    # Ingestion: chunking, embedding, and storage all happen internally
    # with sensible defaults — no explicit splitter/vectorstore wiring.
    app.add("handbook.pdf")
    app.add("https://company.com/faq")           # loaders for many source
    app.add("How do I request a refund?", data_type="qna_pair")  # types built in

    # Query: retrieval + prompt construction + generation, all internal.
    answer = app.query("How do I request a refund?")

    # The tradeoff versus LangChain's LCEL chain above: MUCH less code
    # for the common case, but no direct hook to, say, swap in a custom
    # reranking step (L04) without dropping down to EmbedChain's more
    # advanced/lower-level configuration options, which narrows the gap
    # to LangChain's explicitness as your customization needs grow.
""")

# ------------------------------------------------------------------
# 4. When to choose which
# ------------------------------------------------------------------
LANGCHAIN_VS_EMBEDCHAIN = {
    "Choose LangChain when": "you need custom chunking logic, a specific "
        "reranking step, multiple retrieval strategies combined, or "
        "fine-grained control over each pipeline stage — LCEL's "
        "composability is the point.",
    "Choose EmbedChain when": "you want a working RAG system in minutes "
        "for prototyping, a straightforward use case, or validating a "
        "product idea before investing in a more customizable "
        "implementation.",
}


if __name__ == "__main__":
    print(LANGCHAIN_LOADER_AND_SPLITTER)
    print(LANGCHAIN_VECTORSTORE_AND_RETRIEVER)
    print(LCEL_RAG_CHAIN)
    print(EMBEDCHAIN_EXAMPLE)
    print("=== When to choose which ===")
    for choice, note in LANGCHAIN_VS_EMBEDCHAIN.items():
        print(f"{choice}: {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
A startup validates a documentation-search product using EmbedChain in a
single afternoon, gets positive user feedback, then rebuilds it in
LangChain once real usage reveals a need for a custom two-stage
retrieval-plus-reranking pipeline (L04) that EmbedChain's high-level API
doesn't expose — the prototype wasn't wasted work, it validated the
product decision cheaply before investing in the more customizable
(and more code to maintain) LangChain implementation.
"""

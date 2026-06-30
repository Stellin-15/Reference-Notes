# ============================================================
# L02: LangChain Fundamentals
# ============================================================
# WHAT: LangChain is a framework providing standardized abstractions
#       for building LLM applications. It wraps dozens of LLM providers,
#       vector stores, document loaders, and output parsers under a
#       unified interface.
# WHY:  Without LangChain, switching from OpenAI to Anthropic requires
#       rewriting every API call. With LangChain, you swap one line.
#       It also provides battle-tested primitives: prompt templates,
#       output parsers, document loaders, and the LCEL composition system.
# LEVEL: Foundations
# ============================================================
"""
CONCEPT OVERVIEW:
    LangChain's core insight: most LLM applications follow a pattern of
    (1) format input → (2) call model → (3) parse output. LCEL (LangChain
    Expression Language) makes this pipeline explicit using the | operator,
    like Unix pipes but for LLM operations.

    Architecture: LangChain sits between your business logic and the raw
    LLM APIs. It handles serialization, retry, streaming unification,
    and output parsing.

PRODUCTION USE CASE:
    Document Q&A system: DirectoryLoader ingests PDFs, RecursiveCharacterTextSplitter
    chunks them, OpenAIEmbeddings vectorizes chunks, Chroma stores them. A
    RetrievalQA chain ties it all together. Swap ChatOpenAI → ChatAnthropic
    without touching any other code.

COMMON MISTAKES:
    - Using LangChain for simple one-shot calls (overkill; adds latency and
      debugging complexity — use raw openai SDK instead)
    - Using deprecated .run()/.predict() methods (LCEL .invoke() is the current API)
    - Mixing LangChain v0.1 and v0.2 patterns (API changed significantly)
    - Not pinning langchain versions (breaks between minor versions)
    - Over-chaining: nesting 10 chains is harder to debug than 10 function calls
    - Using ConversationChain (deprecated) instead of LCEL with message history
"""

from typing import Any
import os

# Core LangChain packages (pip install langchain langchain-openai langchain-anthropic)
# langchain:           Core abstractions, LCEL, chains, agents
# langchain-openai:    ChatOpenAI, OpenAIEmbeddings
# langchain-anthropic: ChatAnthropic
# langchain-community: Dozens of third-party integrations (loaders, stores, etc.)

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser, JsonOutputParser
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.runnables import RunnablePassthrough, RunnableLambda, RunnableParallel
from pydantic import BaseModel, Field


# ============================================================
# SECTION 1: CHAT MODELS — UNIFIED INTERFACE
# ============================================================
# WHAT: ChatModel wraps any LLM provider with the same .invoke() interface.
# WHY:  Your RAG chain works identically whether the LLM is OpenAI, Anthropic,
#       or a local Ollama model. Swap the model without rewriting the chain.

# ChatOpenAI: wraps OpenAI chat completions API
chat_openai = ChatOpenAI(
    model="gpt-4o-mini",
    api_key=os.environ.get("OPENAI_API_KEY"),
    temperature=0,
    max_tokens=512,
    # streaming=True,  # Enable by default for LCEL .stream() calls
    # request_timeout=30,
)

# ChatAnthropic: wraps Anthropic's Messages API (claude-3-5-sonnet, etc.)
# Identical interface — same .invoke(), same message format
chat_anthropic = ChatAnthropic(
    model="claude-3-5-haiku-20241022",
    api_key=os.environ.get("ANTHROPIC_API_KEY"),
    temperature=0,
    max_tokens=512,
)

# AWS Bedrock: access Claude, Llama, Titan via AWS IAM (see L07 for full Bedrock)
# from langchain_aws import ChatBedrock
# chat_bedrock = ChatBedrock(model_id="anthropic.claude-3-5-sonnet-20241022-v2:0")

# Direct invocation: call the model with a list of messages
def direct_model_call():
    """The simplest possible LangChain usage."""
    messages = [
        SystemMessage(content="You are a concise assistant. Answer in one sentence."),
        HumanMessage(content="What is a transformer in ML?"),
    ]

    # .invoke() returns an AIMessage object
    response = chat_openai.invoke(messages)
    return response.content  # str

    # AIMessage also has: response.response_metadata (token counts, finish reason)
    # response.response_metadata["token_usage"]["prompt_tokens"]


# ============================================================
# SECTION 2: PROMPT TEMPLATES
# ============================================================
# WHAT: Parameterized prompt strings. Variables are filled in at runtime.
# WHY:  Separate prompt structure from runtime values. Reusable, testable,
#       version-controllable. Essential for any non-trivial application.

# PromptTemplate: for single-string prompts (legacy LLM interface)
simple_template = PromptTemplate.from_template(
    "Summarize the following text in {num_sentences} sentences:\n\n{text}"
)
# Usage: simple_template.format(num_sentences=3, text="Long article...")

# ChatPromptTemplate: for chat models (system + user + optional few-shot)
# This is what you should use for GPT-4, Claude, etc.
chat_template = ChatPromptTemplate.from_messages([
    ("system", "You are an expert {domain} analyst. Be precise and cite sources."),
    ("human",  "Analyze the following: {content}"),
])
# Usage: chat_template.invoke({"domain": "financial", "content": "Q3 earnings..."})

# ChatPromptTemplate with few-shot examples
few_shot_template = ChatPromptTemplate.from_messages([
    ("system",    "Classify the intent of the user's message. Return only the label."),
    ("human",     "I want to return this product"),
    ("ai",        "RETURN_REQUEST"),
    ("human",     "Where is my order?"),
    ("ai",        "ORDER_STATUS"),
    ("human",     "Your service is terrible"),
    ("ai",        "COMPLAINT"),
    ("human",     "{user_message}"),  # The actual variable to fill
])

# MessagesPlaceholder: inject a list of messages into the template
# Used for conversation history in multi-turn chains
from langchain_core.prompts import MessagesPlaceholder

conversation_template = ChatPromptTemplate.from_messages([
    ("system",  "You are a helpful assistant."),
    MessagesPlaceholder(variable_name="history"),  # Inject conversation history here
    ("human",   "{input}"),
])


# ============================================================
# SECTION 3: OUTPUT PARSERS
# ============================================================
# WHAT: Transform raw LLM text output into structured Python objects.
# WHY:  LLMs return strings. Your code needs dicts, lists, Pydantic models.
#       Parsers handle extraction and validation.

# StrOutputParser: simplest — just extracts the .content string from AIMessage
str_parser = StrOutputParser()

# JsonOutputParser: parse JSON from LLM output (handles markdown code blocks too)
json_parser = JsonOutputParser()

# PydanticOutputParser: parse and validate against a Pydantic model
# This is the most production-safe option — validates types, required fields
class ExtractedPerson(BaseModel):
    name: str            = Field(description="Full name of the person")
    age: int | None      = Field(description="Age in years, null if not mentioned")
    company: str | None  = Field(description="Company or employer, null if not mentioned")
    role: str | None     = Field(description="Job title or role, null if not mentioned")

pydantic_parser = JsonOutputParser(pydantic_object=ExtractedPerson)

# The parser generates format instructions to add to your prompt:
format_instructions = pydantic_parser.get_format_instructions()
# This tells the LLM exactly what JSON structure to return

extraction_prompt = ChatPromptTemplate.from_messages([
    ("system", "Extract person information from the text.\n{format_instructions}"),
    ("human",  "{text}"),
]).partial(format_instructions=format_instructions)  # .partial() pre-fills some variables


# ============================================================
# SECTION 4: LCEL — LANGCHAIN EXPRESSION LANGUAGE
# ============================================================
# WHAT: A declarative syntax for composing LangChain components using |.
#       Each | passes the output of the left side as input to the right side.
# WHY:  - Automatic streaming (the | chain streams end-to-end)
#       - Built-in async support (.ainvoke(), .astream(), .abatch())
#       - Parallelism with RunnableParallel
#       - Consistent interface: every LCEL chain has .invoke/.stream/.batch

# The simplest LCEL chain: prompt → model → parser
simple_chain = chat_template | chat_openai | str_parser
# This is a Runnable. Call it with:
# result = simple_chain.invoke({"domain": "financial", "content": "..."})

# Extraction chain with Pydantic parsing
extraction_chain = extraction_prompt | chat_openai | pydantic_parser
# result = extraction_chain.invoke({"text": "John Smith, 45, CEO of Acme Corp"})
# result is an ExtractedPerson Pydantic instance (or dict if using JsonOutputParser)


# ============================================================
# SECTION 5: RUNNABLE PRIMITIVES
# ============================================================
# WHAT: Building blocks for complex LCEL chains.
# WHY:  Real pipelines need branching, transformation, and parallel steps.

# RunnablePassthrough: passes the input through unchanged
# Use case: when a downstream step needs the original input that was transformed
passthrough_example = RunnablePassthrough()

# RunnableLambda: wrap any Python function as a Runnable
def clean_text(text: str) -> str:
    """Pre-process text before sending to LLM."""
    return text.strip().replace("\n\n", "\n")

cleaning_step = RunnableLambda(clean_text)

# Chain with a preprocessing step:
# clean → format prompt → call model → parse output
chain_with_preprocessing = (
    RunnableLambda(lambda x: {"domain": "medical", "content": clean_text(x["content"])})
    | chat_template
    | chat_openai
    | str_parser
)

# RunnableParallel: run multiple chains simultaneously, merge results
# Use case: generate multiple versions of something in parallel, then compare
parallel_chain = RunnableParallel(
    # Both of these run CONCURRENTLY (async under the hood)
    summary=chat_template | chat_openai | str_parser,
    keywords=ChatPromptTemplate.from_messages([
        ("human", "Extract 5 keywords from: {content}. Return as comma-separated list.")
    ]) | chat_openai | str_parser,
)
# result = parallel_chain.invoke({"domain": "finance", "content": "..."})
# result == {"summary": "...", "keywords": "profit, revenue, growth, ..."}

# Branching with RunnableLambda:
# Pattern: classify first, then route to specialized chain
def route_by_intent(inputs: dict) -> Any:
    intent = inputs["intent"]
    if intent == "RETURN_REQUEST":
        return ChatPromptTemplate.from_messages([
            ("system", "You are a returns specialist. Help with the return process."),
            ("human",  "{user_message}"),
        ]) | chat_openai | str_parser
    elif intent == "ORDER_STATUS":
        return ChatPromptTemplate.from_messages([
            ("system", "You are a shipping tracker. Provide order status help."),
            ("human",  "{user_message}"),
        ]) | chat_openai | str_parser
    else:
        return ChatPromptTemplate.from_messages([
            ("system", "You are a general customer service agent."),
            ("human",  "{user_message}"),
        ]) | chat_openai | str_parser

# RunnablePassthrough.assign: add new keys to the input dict without losing existing ones
# This is essential for multi-step chains where each step adds data
add_intent_step = RunnablePassthrough.assign(
    intent=few_shot_template | chat_openai | str_parser
)
# After this step, input dict has both "user_message" AND "intent"

full_routing_chain = (
    add_intent_step                           # Add "intent" to dict
    | RunnableLambda(route_by_intent)         # Returns the appropriate chain
    | RunnablePassthrough()                   # Execute that chain
)


# ============================================================
# SECTION 6: INVOCATION METHODS
# ============================================================

def invocation_examples():
    """
    Every LCEL chain supports four invocation methods.
    Choose based on your use case.
    """
    chain = simple_chain  # any LCEL chain

    # .invoke(): synchronous, wait for full response
    # Use for: scripts, batch jobs, non-user-facing tasks
    result: str = chain.invoke({"domain": "tech", "content": "GPT-4 release"})

    # .stream(): synchronous streaming iterator
    # Use for: CLI tools, terminal output, when you want to print tokens as they arrive
    for chunk in chain.stream({"domain": "tech", "content": "GPT-4 release"}):
        print(chunk, end="", flush=True)

    # .batch(): process multiple inputs, optionally in parallel
    # Use for: bulk processing, nightly jobs, re-evaluation runs
    results: list[str] = chain.batch([
        {"domain": "tech",     "content": "GPT-4 release"},
        {"domain": "finance",  "content": "Q3 earnings"},
        {"domain": "medical",  "content": "New cancer treatment"},
    ], config={"max_concurrency": 5})  # Limit parallel API calls

    # .ainvoke() / .astream() / .abatch(): async versions
    # Use for: FastAPI endpoints, async web servers (prevents blocking event loop)
    import asyncio
    async def async_example():
        result = await chain.ainvoke({"domain": "tech", "content": "test"})
        async for chunk in chain.astream({"domain": "tech", "content": "test"}):
            print(chunk, end="")

    return result


# ============================================================
# SECTION 7: DOCUMENT LOADERS
# ============================================================
# WHAT: Load documents from various sources into LangChain's Document format.
# WHY:  Before you can RAG over your data, you need to load it.
#       Document has .page_content (str) and .metadata (dict with source, page, etc.)

from langchain_community.document_loaders import (
    WebBaseLoader,       # Scrape web pages (uses BeautifulSoup)
    PyPDFLoader,         # Load PDF files (requires pypdf)
    CSVLoader,           # Load CSV as one Document per row
    DirectoryLoader,     # Load all files in a directory
    TextLoader,          # Load plain text files
    # JSONLoader,        # Load JSON/JSONL with jq_schema path
    # UnstructuredWordDocumentLoader,  # .docx files
    # GitLoader,         # Load from a git repo
    # SlackDirectoryLoader,            # Slack export
    # NotionDirectoryLoader,           # Notion export
)

def load_examples():
    """Examples of loading documents from different sources."""

    # Web page: loads rendered text from a URL
    web_loader = WebBaseLoader("https://en.wikipedia.org/wiki/Transformer_(machine_learning_model)")
    web_docs = web_loader.load()
    # web_docs[0].page_content  → full text of the page
    # web_docs[0].metadata      → {"source": "https://...", "title": "..."}

    # PDF: one Document per page
    pdf_loader = PyPDFLoader("/path/to/document.pdf")
    pdf_docs = pdf_loader.load()
    # pdf_docs[2].metadata["page"] == 2

    # Directory: load all PDFs in a folder
    dir_loader = DirectoryLoader(
        path="/path/to/docs/",
        glob="**/*.pdf",           # Only PDFs, recursively
        loader_cls=PyPDFLoader,
        show_progress=True,
        use_multithreading=True,   # Parallel loading
        max_concurrency=4,
    )
    all_docs = dir_loader.load()

    # CSV: each row becomes a Document
    csv_loader = CSVLoader(
        file_path="/path/to/data.csv",
        source_column="url",       # Use this column as the source metadata
        content_columns=["title", "body"],  # Columns to include in page_content
    )
    csv_docs = csv_loader.load()

    return web_docs, pdf_docs, all_docs


# ============================================================
# SECTION 8: TEXT SPLITTERS
# ============================================================
# WHAT: Split long documents into smaller chunks for embedding.
# WHY:  LLMs have context limits. Vector search works better on focused chunks.
#       You can't embed a 100-page PDF as one unit — embed each chunk separately.

from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,  # Best general-purpose splitter
    CharacterTextSplitter,           # Simple, splits on one separator
    TokenTextSplitter,               # Split by token count (more precise)
    MarkdownHeaderTextSplitter,      # Split on Markdown headers (preserves structure)
    # SemanticChunker,               # Split on semantic boundaries (uses embeddings)
)

def splitting_examples():
    """
    RecursiveCharacterTextSplitter is the standard choice.
    It tries splitting on ["\n\n", "\n", " ", ""] in order,
    falling back to harder splits only when needed.
    This preserves paragraph and sentence boundaries when possible.
    """

    # Standard configuration for most use cases
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=512,      # Target chunk size in CHARACTERS (not tokens!)
                             # For 512 tokens: chunk_size ≈ 2000 chars (rough)
        chunk_overlap=50,    # Overlap between consecutive chunks
                             # Prevents context loss at chunk boundaries
                             # Rule of thumb: 10% of chunk_size
        length_function=len, # How to measure length (len = characters)
        # length_function=lambda x: len(tiktoken.encoding_for_model("gpt-4o-mini").encode(x))
        # ^^ Use this for exact token counting (slower but precise)
    )

    # Token-based splitter: more accurate for context window management
    token_splitter = TokenTextSplitter(
        model_name="gpt-4o-mini",
        chunk_size=512,        # TOKENS (not characters)
        chunk_overlap=50,
    )

    # Markdown-aware: split on headers, preserves document structure as metadata
    md_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("#",   "header_1"),
            ("##",  "header_2"),
            ("###", "header_3"),
        ]
    )

    sample_doc = [type("Doc", (), {
        "page_content": "Long document text " * 200,
        "metadata": {"source": "test.pdf"}
    })()]

    chunks = splitter.split_documents(sample_doc)
    # Each chunk is a Document with .page_content and inherited .metadata
    # chunk.metadata["source"] is preserved from the original document
    print(f"Split into {len(chunks)} chunks")
    return chunks


# ============================================================
# SECTION 9: PUTTING IT TOGETHER — SIMPLE RAG CHAIN
# ============================================================
# WHAT: Full document Q&A pipeline using LCEL.
#       (Full production RAG is covered in L03_rag_systems.py)

from langchain_community.vectorstores import Chroma

def build_simple_rag_chain(documents: list):
    """
    Build an in-memory RAG chain from a list of documents.
    Good for prototyping. For production: use Pinecone/pgvector and persist.
    """
    # 1. Split documents into chunks
    splitter = RecursiveCharacterTextSplitter(chunk_size=512, chunk_overlap=50)
    chunks = splitter.split_documents(documents)

    # 2. Embed chunks and store in Chroma (in-memory)
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    vectorstore = Chroma.from_documents(chunks, embeddings)

    # 3. Create a retriever (wrapper around vectorstore.similarity_search)
    retriever = vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={"k": 4},  # Return top-4 most similar chunks
    )

    # 4. RAG prompt: instruct model to use retrieved context
    rag_prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "Answer the question using ONLY the provided context. "
            "If the context doesn't contain the answer, say 'I don't know based on the provided information.' "
            "Do not hallucinate or use prior knowledge.\n\n"
            "Context:\n{context}"
        )),
        ("human", "{question}"),
    ])

    # 5. Format retrieved documents into a single string
    def format_docs(docs) -> str:
        return "\n\n---\n\n".join(
            f"Source: {doc.metadata.get('source', 'unknown')}\n{doc.page_content}"
            for doc in docs
        )

    # 6. Assemble the chain with LCEL
    # Flow: question → retrieve docs → format → fill prompt → call model → parse
    rag_chain = (
        {
            "context":  retriever | RunnableLambda(format_docs),
            "question": RunnablePassthrough(),
        }
        | rag_prompt
        | chat_openai
        | str_parser
    )

    return rag_chain
    # Usage: answer = rag_chain.invoke("What is the main topic of the document?")


# ============================================================
# SECTION 10: CRITICISM AND WHEN TO USE LANGCHAIN
# ============================================================
"""
WHY LANGCHAIN GETS CRITICIZED:

1. OVER-ABSTRACTION
   Calling a simple OpenAI API through 6 layers of abstractions makes
   debugging painful. When something breaks, you need to trace through
   LangChain's internals. The raw openai SDK error is now wrapped in
   LangChain's error, which is harder to read.

2. VERSION INSTABILITY
   LangChain broke APIs significantly between v0.0.x, v0.1, and v0.2.
   Code written 6 months ago likely uses deprecated patterns.
   Always pin versions: langchain==0.2.x

3. MAGIC BEHAVIOR
   Some chains do things invisibly (token counting, prompt modification,
   memory injection). When the LLM does something unexpected, it's
   hard to tell if the prompt was modified by LangChain.

4. COMPLEXITY FOR SIMPLE TASKS
   For a single-turn chat completion, using LangChain adds 3 import
   statements and an abstraction layer for zero benefit.

WHEN TO USE LANGCHAIN:
   ✓ Multi-step pipelines (RAG chains, agent loops)
   ✓ Need to swap LLM providers frequently (prototyping)
   ✓ Building document Q&A (excellent loaders and splitters)
   ✓ Team already standardized on it
   ✓ LCEL streaming/async is exactly what you need

WHEN NOT TO USE LANGCHAIN (use raw SDK):
   ✗ Simple one-shot completions
   ✗ Production code that needs to be auditable and debuggable
   ✗ When you need precise control over the request format
   ✗ Cost-sensitive code (LangChain can add unexpected API calls)
   ✗ When LangGraph would serve better (complex stateful workflows)

ALTERNATIVES:
   - Raw OpenAI SDK + tenacity = most control, least magic
   - LlamaIndex = better for document-heavy RAG (see L06)
   - LangGraph = better for agent workflows (see L05)
   - Haystack = strong alternative for RAG pipelines
   - DSPy = programmatic optimization of prompts (different paradigm)
"""


# ============================================================
# QUICK REFERENCE
# ============================================================
"""
CHEAT SHEET:

  Initialize model:
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

  Simple chain (LCEL):
    chain = prompt_template | llm | StrOutputParser()
    result = chain.invoke({"var1": "value1"})

  Add preprocessing:
    chain = RunnableLambda(preprocess) | prompt | llm | parser

  Add a step that injects new keys:
    chain = RunnablePassthrough.assign(new_key=some_chain) | next_step

  Run in parallel:
    chain = RunnableParallel(a=chain_a, b=chain_b)

  Streaming:
    for chunk in chain.stream(inputs): print(chunk, end="")

  Async (FastAPI):
    result = await chain.ainvoke(inputs)

  Document loading:
    docs = PyPDFLoader("file.pdf").load()
    chunks = RecursiveCharacterTextSplitter(chunk_size=512).split_documents(docs)

  Key imports:
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser, JsonOutputParser
    from langchain_core.runnables import RunnablePassthrough, RunnableLambda
"""

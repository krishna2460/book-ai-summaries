# Architecture

The Book Summarizer & Query Agent is a full-stack application leveraging a modular architecture designed for document ingestion, processing, and interactive querying.

## System Components

1. **Frontend (Next.js)**
   - Provides an interactive user interface for uploading documents, monitoring processing status, viewing summaries, and engaging in chat-based queries with the document text.
   - Communicates with the backend via REST API.

2. **Backend (FastAPI)**
   - Exposes RESTful endpoints for frontend interactions.
   - Manages asynchronous background tasks for heavy operations like document processing.
   - Contains route controllers, database models, and integration logic for external services (LLM).

3. **Database (PostgreSQL + pgvector)**
   - Stores application metadata (Users, Sessions, Documents, Queries, LLMUsage).
   - Utilizes `pgvector` for storing and efficiently querying document embeddings (vector search) for RAG.

4. **Orchestration (LangGraph)**
   - Manages complex multi-step workflows.
   - **Summarization Graph**: Implements a Map-Reduce pipeline to iteratively summarize document chunks without hitting LLM context limits.
   - **RAG Graph**: Orchestrates retrieval, evaluation of context sufficiency, potential broadening, and answer generation for user queries.

5. **LLM Provider (Azure OpenAI)**
   - Provides embeddings generation (`text-embedding-3-small`) and conversational AI capabilities (`gpt-4o-mini`).
   - Integrated with retry logic, cost tracking, and structured output parsing.

6. **Observability (Langfuse)**
   - Traces LLM calls for latency, cost, and debugging purposes.

## Flow Diagrams

*(A mermaid diagram could be added here illustrating the data flow from upload to summary generation, and from query submission to answer retrieval).*

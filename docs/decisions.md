# Architectural Decisions

## 1. Database Selection: PostgreSQL with pgvector
We chose PostgreSQL with the `pgvector` extension to serve as both our primary relational database and our vector store. 
- **Why**: This unifies our data layer, eliminating the need to synchronize a separate vector database (like Pinecone or Qdrant) with our relational metadata. It simplifies deployment and ensures transactional consistency between document metadata and embedded chunks.

## 2. LLM Orchestration: LangGraph
We utilize LangGraph for orchestrating LLM interactions instead of simple sequential chains.
- **Why**: LangGraph allows us to define complex, stateful, multi-actor applications with conditional routing and cycles. This is crucial for:
  - **Map-Reduce Summarization**: Iteratively summarizing chunks and reducing them without exceeding context windows.
  - **RAG with Broadening**: Conditionally expanding the search scope if initial retrieval yields insufficient context.

## 3. Asynchronous Processing
Document ingestion, embedding, and summarization are handled as background tasks.
- **Why**: These operations are computationally expensive and latency-heavy (especially LLM API calls). Offloading them ensures the `/upload` endpoint responds immediately (HTTP 202), providing a better user experience while the frontend polls for completion.

## 4. Session & Identity Management
We implemented a hybrid approach that supports both anonymous sessions (via cookies) and authenticated users (via JWT).
- **Why**: This reduces friction by allowing users to upload and process a book immediately without signing up. The `migrate-session` functionality ensures they don't lose their data if they decide to create an account later.

## 5. Deployment & Containerization
The application is fully containerized using Docker, with a multi-stage build for the Next.js frontend and a standard Python container for the FastAPI backend.
- **Why**: Containerization ensures consistency across environments (development, staging, production) and simplifies deployment to modern cloud platforms (e.g., Azure Container Apps, AWS ECS).

# Endpoints Documentation

## Authentication (`/auth`)

### `POST /auth/signup`
Creates a new user account.
- **Request Body**: `email`, `password`, `display_name` (optional)
- **Response**: `201 Created` with `{ "access_token": "..." }`

### `POST /auth/login`
Authenticates a user and returns a JWT.
- **Request Body**: `email`, `password`
- **Response**: `200 OK` with `{ "access_token": "..." }`

### `GET /auth/me`
Retrieves the profile of the currently authenticated user.
- **Headers**: `Authorization: Bearer <token>`
- **Response**: `200 OK` with User details.

### `POST /auth/migrate-session`
Migrates documents from an anonymous session to a newly authenticated user account.
- **Headers**: `Authorization: Bearer <token>`
- **Response**: `200 OK` with migration count.

## Documents (`/documents`)

### `POST /documents/upload`
Uploads a document for processing (summarization & embedding). Returns 202 Accepted while processing runs in the background.
- **Body**: `multipart/form-data` with `file` (PDF/DOCX)
- **Response**: `202 Accepted` with Document ID and initial status.

### `GET /documents`
Lists all documents for the current user or session.
- **Response**: `200 OK` with a list of Document objects.

### `GET /documents/{id}`
Retrieves full details of a specific document, including its status and summary.
- **Response**: `200 OK` with Document object.

### `GET /documents/{id}/status`
Lightweight endpoint to poll the status of a document.
- **Response**: `200 OK` with status and optional error message.

## Queries (`/documents/{id}/queries`)

### `POST /documents/{id}/query`
Submits a question against a specific document using RAG.
- **Request Body**: `{ "question": "..." }`
- **Response**: `200 OK` with Answer and Citations (chunk indices and pages).

### `GET /documents/{id}/queries`
Lists the history of queries for a specific document.
- **Response**: `200 OK` with a list of Query objects.

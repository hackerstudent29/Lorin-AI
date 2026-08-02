# MSAJCE Lorin AI Chatbot

Lorin AI is the official assistant chatbot developed for **Mohamed Sathak A.J. College of Engineering (MSAJCE)**, Chennai. It helps students, staff, and parents retrieve accurate information regarding admissions, transport bus routes, placement highlights, academic departments, and student clubs.

---

## Features
- **Conversational Assistant**: Understands user queries and resolves multi-turn pronouns seamlessly.
- **Accurate Grounding**: Answers are strictly grounded in official college records to prevent hallucinations.
- **Hybrid Retrieval**: Combines semantic dense search with keyword sparse search.
- **Self-Healing Feedback**: Processes thumbs-up/down ratings from users to automatically correct and re-cache responses.
- **Structured Outputs**: Formats schedules, timetables, and eligibility criteria into readable Markdown tables.

---

## Tech Stack
- **Frontend**: React 18, TypeScript, TailwindCSS, Framer Motion.
- **Backend**: Python, FastAPI, Uvicorn, Slowapi.
- **Database**: PostgreSQL (Supabase Cloud).
- **Vector Search**: Qdrant Cloud.

---

## Project Structure
- `/frontend`: React client code.
- `/backend`: FastAPI server code and dataset.
- `/backend/dataset`: Verified college documentation files.

---

## Getting Started

### Prerequisites
- Node.js (v18+)
- Python (v3.10+)

### Running the Frontend
1. Navigate to the `/frontend` directory:
   ```bash
   cd frontend
   ```
2. Install dependencies:
   ```bash
   npm install
   ```
3. Start the local development server:
   ```bash
   npm run dev
   ```

### Running the Backend
1. Navigate to the `/backend` directory:
   ```bash
   cd backend
   ```
2. Set up a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   # Activate virtual environment
   # On Windows:
   .venv\Scripts\activate
   # On macOS/Linux:
   source .venv/bin/activate
   
   pip install -r requirements.txt
   ```
3. Run the API server:
   ```bash
   python api_server.py
   ```

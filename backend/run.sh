#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate 2>/dev/null || python3 -m venv .venv && source .venv/bin/activate
pip install -q fastapi uvicorn pydantic pydantic-settings python-multipart faiss-cpu numpy pypdf python-docx openai dashscope langchain langchain-openai langchain-core
exec uvicorn app.main:app --reload --port 8000

import os
import json
import httpx
import asyncio
from typing import List, Optional
from app.core.config import settings
from app.logger import get_logger

logger = get_logger(__name__)

class CerebrasClient:
    """Wraps Cerebras Cloud API for high-speed text generation via direct REST calls."""
    
    def __init__(self):
        self.api_key = settings.cerebras_api_key
        self.api_url = "https://api.cerebras.ai/v1/chat/completions"

    async def generate(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        """Generate text using direct HTTP POST to Cerebras."""
        if not self.api_key:
            raise RuntimeError("CEREBRAS_API_KEY missing.")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": settings.cerebras_model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 4096,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(self.api_url, headers=headers, json=payload)
                if response.status_code == 401:
                    logger.error("Cerebras Authentication Failed")
                    raise RuntimeError("Cerebras Authentication Error")
                
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
            except Exception as e:
                logger.error(f"Cerebras Error: {e}")
                raise

async def generate_text(prompt: str, system_instruction: Optional[str] = None) -> str:
    """Routes ALL text generation tasks exclusively to Cerebras."""
    if not settings.cerebras_api_key:
        logger.error("CEREBRAS_API_KEY missing.")
        raise RuntimeError("CEREBRAS_API_KEY not configured")

    cerebras = CerebrasClient()
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            return await cerebras.generate(prompt, system_instruction=system_instruction)
        except Exception as e:
            if attempt < max_retries:
                wait = 2.0 * (attempt + 1)
                await asyncio.sleep(wait)
                continue
            raise RuntimeError(f"Cerebras exhausted retries: {e}")
    raise RuntimeError("Cerebras generation failed")

class LocalEmbeddingClient:
    """Provides local sentence embeddings to bypass API rate limits."""
    
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        self.model_name = model_name
        self._model = None
        
    @property
    def model(self):
        if self._model is None:
            try:
                from fastembed import TextEmbedding
                logger.info(f"Initializing Local Embedding Model: {self.model_name}")
                self._model = TextEmbedding(model_name=self.model_name)
            except ImportError:
                logger.error("fastembed not installed. Local embeddings disabled.")
                return None
        return self._model

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not self.model:
            return []
        try:
            return [list(e) for e in self.model.embed(texts)]
        except Exception as e:
            logger.error(f"Local embedding error: {e}")
            return []


class GeminiClient:
    """Handles interactions with Google Gemini API for text generation and embeddings."""

    def __init__(self, model_name: str = "gemini-2.0-flash"):
        self.api_key = settings.gemini_api_key
        self.model = model_name
        self.embed_model = "models/gemini-embedding-001" 
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    def embed(self, text: str) -> List[float]:
        """Generate embedding for a single string."""
        res = self.embed_batch([text])
        return res[0] if res else []

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a batch of strings (Optimized for 15 RPM)."""
        if not self.api_key:
            logger.error("Gemini API key missing.")
            return []

        url = f"{self.base_url}/{self.embed_model}:batchEmbedContents?key={self.api_key}"
        payload = {
            "requests": [
                {"model": self.embed_model, "content": {"parts": [{"text": t}]}}
                for t in texts
            ]
        }
        
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                return [e["values"] for e in data.get("embeddings", [])]
        except Exception as e:
            logger.error(f"Gemini embedding batch error: {e}")
            return []

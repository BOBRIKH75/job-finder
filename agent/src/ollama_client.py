"""Ollama client — local LLM for form analysis, cover letters, question answering."""
import json
import httpx

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:8b"


async def chat(prompt: str, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_URL, temperature: float = 0.3) -> str:
    """Send a chat message to Ollama and return the response."""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{base_url}/api/chat", json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": temperature},
        })
        resp.raise_for_status()
        return resp.json()["message"]["content"]


async def chat_json(prompt: str, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_URL) -> dict:
    """Chat with JSON output format."""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{base_url}/api/chat", json={
            "model": model,
            "messages": [{"role": "user", "content": prompt + "\n\nRespond in JSON only."}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        })
        resp.raise_for_status()
        return json.loads(resp.json()["message"]["content"])


async def generate_cover_letter(job_title: str, company: str, job_description: str, profile: dict) -> str:
    skills_str = ", ".join(profile.get("skills", [])[:20])
    prompt = f"""Write a concise cover letter (under 250 words) for:
Role: {job_title} at {company}
Key requirements: {job_description[:500]}
Candidate: {profile['name']}, {profile['years_experience']}+ years. Skills: {skills_str}
Work type: C2C contractor, Green Card holder.
Be specific to this role. No generic filler. Professional tone."""
    return await chat(prompt, temperature=0.5)


async def answer_question(question: str, profile: dict) -> str:
    skills_str = ", ".join(profile.get("skills", [])[:30])
    prompt = f"""Answer this job application question truthfully and concisely (2-4 sentences).
Candidate: {profile['name']}, {profile['title']}, {profile['years_experience']}+ years.
Skills: {skills_str}. Green Card holder, C2C contractor, rate ${profile['rate_min']}-${profile['rate_max']}/hr.

Question: {question}"""
    return await chat(prompt, temperature=0.3)


async def is_healthy(base_url: str = DEFAULT_URL) -> bool:
    """Check if Ollama is running."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{base_url}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False

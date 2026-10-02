"""Model router — selects the appropriate Groq model per operation with automatic multi-model failover."""
from __future__ import annotations
import asyncio
import logging
import threading
import time
import json
from typing import Any
import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from backend.agent.router.registry import registry
from backend.core.config import get_groq_api_key, get_gemma_api_key, get_groq_model

logger = logging.getLogger("nexus.model_router")

# Valid Groq Chat Completion model IDs matching the active account.
# These are used in the dynamic reasoning pool — picked round-robin on rate-limit or error.
# Valid reasoning models. Google Gemma is prioritized when GEMMA_API_KEY is configured.
FALLBACK_MODELS = [
    "google/gemma-4-26b-a4b-it",  # Google Gemma 4 26B — preferred ultra-fast streaming reasoning
    "openai/gpt-oss-20b",         # OpenAI GPT-OSS 20B on Groq — high token limit (8k OTPM) & fast
    "openai/gpt-oss-120b",        # OpenAI GPT-OSS 120B on Groq — heavy reasoning
    "qwen/qwen3.8-27b",           # Qwen 2.5 27B on Groq — fallback distillation
    "allam-2-7b",                 # Fallback lightweight model
]

VISION_FALLBACK_MODELS = [
    "llama-3.2-90b-vision-preview",
    "llama-3.2-11b-vision-preview",
]

GEMMA_VISION_MODEL_CANDIDATES = [
    "gemma-4-26b-a4b-it",
    "gemini-3.8-flash",
]


async def call_gemma_vision_fallback(prompt: str, data_url: str, timeout: float = 12.0) -> str:
    """Use a Google AI Studio vision-capable model as a fallback when Groq VLM fails."""
    gemma_key = get_gemma_api_key()
    if not gemma_key:
        raise RuntimeError("Gemma API key not configured.")

    last_error = None
    for model_name in GEMMA_VISION_MODEL_CANDIDATES:
        clean_model = model_name.replace("google/", "").replace("models/", "")
        payload = {
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inlineData": {"mimeType": "image/jpeg", "data": data_url.split(",", 1)[1] if "," in data_url else data_url}},
                ],
            }],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 300},
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload, headers={"x-goog-api-key": gemma_key})
                if resp.status_code != 200:
                    last_error = RuntimeError(f"Gemma vision fallback error ({resp.status_code}): {resp.text[:200]}")
                    continue
                data = resp.json()
                candidates = data.get("candidates") or []
                if not candidates:
                    last_error = RuntimeError(f"Gemma vision response did not include any candidates: {resp.text[:200]}")
                    continue
                parts = candidates[0].get("content", {}).get("parts") or []
                text_parts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("text")]
                if text_parts:
                    return "\n".join(text_parts).strip()
                if parts:
                    text = str(parts[0]).strip()
                    if text:
                        return text
                last_error = RuntimeError(f"Gemma vision response was empty for model '{model_name}'")
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError("Gemma vision fallback models were unavailable.")


async def stream_gemma_with_thoughts(
    messages: list[Any],
    task_id: Optional[str] = None,
    temperature: float = 0.1,
    model: str = "gemma-4-26b-a4b-it",
    timeout: float = 20.0,
    response_json: bool = False,
    on_thought_chunk: Optional[Any] = None,
) -> tuple[str, str]:
    """
    Invokes Google AI Studio streamGenerateContent endpoint for Gemma 4 models.
    Streams thought tokens in real-time over SSE to the frontend via push_event,
    and returns (final_content, accumulated_thought).
    """
    gemma_key = get_gemma_api_key()
    if not gemma_key:
        raise ValueError("Gemma API key not configured.")

    contents = []
    system_text = ""
    for m in messages:
        if isinstance(m, SystemMessage):
            system_text += m.content + "\n"
        elif isinstance(m, HumanMessage):
            contents.append({"role": "user", "parts": [{"text": m.content}]})
        elif isinstance(m, AIMessage):
            contents.append({"role": "model", "parts": [{"text": m.content}]})
        elif isinstance(m, dict):
            role = "user" if m.get("role") in ("user", "human") else "model"
            contents.append({"role": role, "parts": [{"text": m.get("content", "")}]})
        else:
            role = "user" if getattr(m, "type", "user") in ("user", "human") else "model"
            contents.append({"role": role, "parts": [{"text": getattr(m, "content", str(m))}]})

    if not contents and system_text:
        contents.append({"role": "user", "parts": [{"text": system_text}]})
        system_text = ""

    gen_config: dict[str, Any] = {
        "temperature": temperature,
        "maxOutputTokens": 2048,
    }
    if response_json:
        gen_config["responseMimeType"] = "application/json"

    payload = {
        "contents": contents,
        "generationConfig": gen_config,
    }
    if system_text:
        payload["system_instruction"] = {"parts": [{"text": system_text.strip()}]}

    clean_model = model.replace("google/", "").replace("models/", "")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:streamGenerateContent?alt=sse"

    accumulated_thought: list[str] = []
    accumulated_content: list[str] = []

    push_event_fn = None
    if task_id:
        try:
            from backend.api.nexus import push_event
            push_event_fn = push_event
        except Exception:
            pass

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=payload, headers={"x-goog-api-key": gemma_key}) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise RuntimeError(f"Google Gemma API error ({response.status_code}): {body.decode('utf-8', 'ignore')[:200]}")

            line_count = 0
            async for line in response.aiter_lines():
                line_count += 1
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if not data_str:
                    continue
                try:
                    chunk = json.loads(data_str)
                except Exception as ex:
                    logger.debug("[GemmaStream] JSON parse error: %s", ex)
                    continue

                candidates = chunk.get("candidates") or []
                if not candidates or "content" not in candidates[0]:
                    continue

                parts = candidates[0]["content"].get("parts") or []
                for p in parts:
                    is_thought = p.get("thought", False)
                    text = p.get("text", "")
                    if not text:
                        continue
                    if is_thought:
                        accumulated_thought.append(text)
                        full_thought = "".join(accumulated_thought)
                        if on_thought_chunk:
                            try:
                                if asyncio.iscoroutinefunction(on_thought_chunk):
                                    await on_thought_chunk(text, full_thought)
                                else:
                                    on_thought_chunk(text, full_thought)
                            except Exception:
                                pass
                        if push_event_fn and task_id:
                            try:
                                await push_event_fn(task_id, "reasoning_chunk", {
                                    "delta": text,
                                    "thought": full_thought,
                                })
                            except Exception:
                                pass
                    else:
                        accumulated_content.append(text)
            logger.info("[GemmaStream] Total lines: %d, thoughts: %d, content parts: %d", line_count, len(accumulated_thought), len(accumulated_content))

    final_content = "".join(accumulated_content).strip()
    full_thought = "".join(accumulated_thought).strip()
    if not final_content and full_thought:
        if "[" in full_thought and "]" in full_thought:
            final_content = full_thought[full_thought.index("[") : full_thought.rindex("]") + 1]
        elif "{" in full_thought and "}" in full_thought:
            final_content = full_thought[full_thought.index("{") : full_thought.rindex("}") + 1]
        else:
            final_content = full_thought
    return final_content, full_thought


async def call_google_gemma(
    messages: list[Any],
    temperature: float = 0.2,
    model: str = "gemma-4-26b-a4b-it",
    timeout: float = 18.0,
    response_json: bool = False,
) -> AIMessage:
    """Invokes Google AI Studio generateContent endpoint for Gemma 4 models."""
    gemma_key = get_gemma_api_key()
    if not gemma_key:
        raise ValueError("Gemma API key not configured. Open NEXUS Settings to add your key.")

    contents = []
    system_text = ""
    for m in messages:
        if isinstance(m, SystemMessage):
            system_text += m.content + "\n"
        elif isinstance(m, HumanMessage):
            contents.append({"role": "user", "parts": [{"text": m.content}]})
        elif isinstance(m, AIMessage):
            contents.append({"role": "model", "parts": [{"text": m.content}]})
        elif isinstance(m, dict):
            role = "user" if m.get("role") in ("user", "human") else "model"
            contents.append({"role": role, "parts": [{"text": m.get("content", "")}]})
        else:
            role = "user" if getattr(m, "type", "user") in ("user", "human") else "model"
            contents.append({"role": role, "parts": [{"text": getattr(m, "content", str(m))}]})

    if not contents and system_text:
        contents.append({"role": "user", "parts": [{"text": system_text}]})
        system_text = ""

    gen_config: dict[str, Any] = {
        "temperature": temperature,
        "maxOutputTokens": 2048,
    }
    # Only enforce JSON schema if explicitly requested or if prompt mentions JSON
    combined_prompt = (system_text + " " + " ".join(str(c.get("parts", [{}])[0].get("text", "")) for c in contents if isinstance(c, dict))).lower()
    if response_json or "json" in combined_prompt:
        gen_config["responseMimeType"] = "application/json"

    payload = {
        "contents": contents,
        "generationConfig": gen_config,
    }
    if system_text:
        payload["system_instruction"] = {"parts": [{"text": system_text.strip()}]}

    clean_model = model.replace("google/", "").replace("models/", "")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent"

    async with httpx.AsyncClient(timeout=timeout) as client:
        res = await client.post(url, json=payload, headers={"x-goog-api-key": gemma_key})
        if res.status_code != 200:
            raise RuntimeError(f"Google Gemma API error ({res.status_code}): {res.text[:200]}")
        data = res.json()
        candidates = data.get("candidates", [])
        if not candidates or "content" not in candidates[0]:
            raise RuntimeError(f"Google Gemma returned no content: {res.text[:200]}")
        
        parts = candidates[0]["content"].get("parts", [])
        # Gemma 4 thinking models return parts[0] with thought: True.
        # The actual output is in the non-thought part:
        content = ""
        for p in parts:
            if not p.get("thought") and p.get("text"):
                content = p.get("text").strip()
                break
        if not content and parts:
            for p in reversed(parts):
                if p.get("text"):
                    content = p.get("text").strip()
                    break
        return AIMessage(content=content)


class DynamicModelPool:
    # How long (seconds) to keep a model in cooldown after a rate-limit or timeout failure
    _COOLDOWN_SECONDS = 30.0

    def __init__(self):
        self.reasoning_pool = list(FALLBACK_MODELS)
        self.vision_pool = list(VISION_FALLBACK_MODELS)
        self.reasoning_idx = 0
        self.vision_idx = 0
        # Per-model cooldown timestamps: model_id -> epoch time when cooldown expires
        self._model_cooldowns: dict[str, float] = {}
        # Thread-safe lock for index mutations (concurrent requests can race)
        self._lock = threading.Lock()

    def _is_on_cooldown(self, model_id: str) -> bool:
        """Return True if the model is within its cooldown window."""
        expires = self._model_cooldowns.get(model_id, 0.0)
        return time.monotonic() < expires

    def _set_cooldown(self, model_id: str) -> None:
        """Place model on cooldown for _COOLDOWN_SECONDS."""
        self._model_cooldowns[model_id] = time.monotonic() + self._COOLDOWN_SECONDS

    def get_active_reasoning_model(self) -> str:
        gemma_key = get_gemma_api_key()
        with self._lock:
            pool = self.reasoning_pool
            n = len(pool)
            # Walk from current index, skipping any model on cooldown or misconfigured
            for offset in range(n):
                candidate = pool[(self.reasoning_idx + offset) % n]
                if candidate.startswith("google/") and not gemma_key:
                    continue
                if self._is_on_cooldown(candidate):
                    continue
                return candidate
            # All models on cooldown — return primary anyway (better than failing entirely)
            return pool[self.reasoning_idx % n]

    def get_active_vision_model(self) -> str:
        with self._lock:
            pool = self.vision_pool
            n = len(pool)
            for offset in range(n):
                candidate = pool[(self.vision_idx + offset) % n]
                if not self._is_on_cooldown(candidate):
                    return candidate
            return pool[self.vision_idx % n]

    def switch_reasoning_model(self, reason: str = "Rate limit (429)") -> str:
        with self._lock:
            old_model = self.reasoning_pool[self.reasoning_idx % len(self.reasoning_pool)]
            # Place the failing model on cooldown so a recover_system_state() reset
            # doesn't immediately re-select a still-rate-limited model
            self._set_cooldown(old_model)
            self.reasoning_idx += 1
            new_model = self.reasoning_pool[self.reasoning_idx % len(self.reasoning_pool)]
        notice = (
            f"\n{'='*70}\n"
            f"[NEXUS DYNAMIC MODEL SWITCH: REASONING & HEAVY LIFTING ENGINE]\n"
            f"Trigger: {reason}\n"
            f"Switch: '{old_model}' -> '{new_model}'\n"
            f"Action: Seamless auto-failover; continuing execution with zero disruption.\n"
            f"{'='*70}\n"
        )
        print(notice, flush=True)
        logger.warning("Dynamic model switch: %s -> %s (%s)", old_model, new_model, reason)
        try:
            from backend.agent.tools.web_automation.logger import auto_logger
            auto_logger.log_model_switch("reasoning", old_model, new_model, reason)
        except Exception:
            pass
        return new_model

    def switch_vision_model(self, reason: str = "Rate limit (429)") -> str:
        with self._lock:
            old_model = self.vision_pool[self.vision_idx % len(self.vision_pool)]
            self._set_cooldown(old_model)
            self.vision_idx += 1
            new_model = self.vision_pool[self.vision_idx % len(self.vision_pool)]
        notice = (
            f"\n{'='*70}\n"
            f"[NEXUS DYNAMIC MODEL SWITCH: VISION ENGINE]\n"
            f"Trigger: {reason}\n"
            f"Switch: '{old_model}' -> '{new_model}'\n"
            f"Action: Continuing validation seamlessly with new model.\n"
            f"{'='*70}\n"
        )
        print(notice, flush=True)
        logger.warning("Dynamic vision model switch: %s -> %s (%s)", old_model, new_model, reason)
        try:
            from backend.agent.tools.web_automation.logger import auto_logger
            auto_logger.log_model_switch("vision", old_model, new_model, reason)
        except Exception:
            pass
        return new_model


# Singleton pool
model_pool = DynamicModelPool()


def get_llm(
    operation: str = "reasoning",
    *,
    vision: bool = False,
    temperature: float = 0.3,
    structured: bool = False,
) -> Any:
    """Return a configured LLM with automatic multi-model failover on rate limits (429) or errors."""
    api_key = get_groq_api_key()
    if not api_key:
        raise RuntimeError("Groq API key not configured. Open NEXUS Settings to add it.")

    if vision:
        model_id = model_pool.get_active_vision_model()
    else:
        model_id = model_pool.get_active_reasoning_model()
        if model_id.startswith("google/"):
            model_id = get_groq_model("reasoning")

    groq_model_name = model_id
    primary_llm = ChatGroq(
        api_key=api_key,
        model=groq_model_name,
        temperature=temperature,
        max_retries=1,
    )

    fallbacks = [
        ChatGroq(
            api_key=api_key,
            model=fb,
            temperature=temperature,
            max_retries=1,
        )
        for fb in (FALLBACK_MODELS if not vision else VISION_FALLBACK_MODELS)
        if fb != model_id and not fb.startswith("google/")
    ]

    if fallbacks:
        return primary_llm.with_fallbacks(fallbacks)
    return primary_llm


async def ainvoke_with_dynamic_switch(
    messages: list[Any],
    operation: str = "reasoning",
    temperature: float = 0.2,
    max_attempts: int = 3,
    per_attempt_timeout: float = 18.0,
    max_tokens: int = 600,
    response_json: bool = False,
) -> Any:
    """
    Invokes LLM with instant automatic failover across models.
    Each attempt is hard-capped at per_attempt_timeout seconds via asyncio.wait_for
    so a hanging model can never block indefinitely.
    max_tokens respects model rate limits and clamps tokens on low-OTPM models.
    """
    groq_key = get_groq_api_key()
    gemma_key = get_gemma_api_key()

    if not groq_key and not gemma_key:
        raise RuntimeError("Neither Groq nor Gemma API key is configured. Open NEXUS Settings to add your key.")

    # For fast classification and tool execution decisions, prioritize Groq LPU (<500ms)
    if operation in ("fast", "tool") and groq_key:
        groq_model = get_groq_model(operation)
        fast_timeout = min(per_attempt_timeout, 8.0)
        fast_tokens = min(max_tokens, 250) if operation == "fast" else max_tokens
        try:
            llm = ChatGroq(
                api_key=groq_key,
                model=groq_model,
                temperature=temperature,
                max_retries=0,
                max_tokens=fast_tokens,
                request_timeout=fast_timeout,
            )
            return await asyncio.wait_for(llm.ainvoke(messages), timeout=fast_timeout + 1.0)
        except Exception as exc:
            err_str = str(exc).lower()
            is_rate_limit = "429" in err_str or "rate limit" in err_str or "otpm" in err_str
            if is_rate_limit:
                model_pool._set_cooldown(groq_model)
                logger.warning("[ModelRouter] Fast Groq call on '%s' rate-limited (429); placing on cooldown and failing over.", groq_model)
            else:
                logger.warning("[ModelRouter] Fast Groq call on '%s' failed (%s); falling back to reasoning pool.", groq_model, exc)

    last_error = None
    attempted_models = set()
    
    for attempt in range(max_attempts):
        current_model = model_pool.get_active_reasoning_model()
        
        # Prevent infinite loops: if we've tried all models, break
        if current_model in attempted_models and len(attempted_models) >= len(model_pool.reasoning_pool):
            break
        attempted_models.add(current_model)
        
        try:
            if current_model.startswith("google/gemma"):
                if not gemma_key:
                    model_pool.switch_reasoning_model(reason="Gemma API key not configured")
                    continue
                sub_model = current_model.split("/", 1)[1]
                return await asyncio.wait_for(
                    call_google_gemma(
                        messages,
                        temperature=temperature,
                        model=sub_model,
                        timeout=per_attempt_timeout,
                        response_json=response_json,
                    ),
                    timeout=per_attempt_timeout + 1.5,
                )
            else:
                if not groq_key:
                    model_pool.switch_reasoning_model(reason="Groq API key not configured")
                    continue
                # For models with tight OTPM (like qwen 1000 OTPM), limit requested tokens
                token_budget = min(max_tokens, 350) if "qwen" in current_model else max_tokens
                llm = ChatGroq(
                    api_key=groq_key,
                    model=current_model,
                    temperature=temperature,
                    max_retries=0,
                    max_tokens=token_budget,
                    request_timeout=per_attempt_timeout,
                )
                return await asyncio.wait_for(llm.ainvoke(messages), timeout=per_attempt_timeout + 1.5)
        except Exception as exc:
            err_str = str(exc).lower()
            exc_name = type(exc).__name__
            is_timeout = isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or any(
                x in err_str or x in exc_name.lower() for x in ("timeout", "timed out", "readtimeout", "asyncio")
            )
            is_rate_limit = "429" in err_str or "rate limit" in err_str or "quota" in err_str or "resource_exhausted" in err_str or "otpm" in err_str
            last_error = exc
            if is_rate_limit:
                reason = f"Rate limit (429) on '{current_model}'"
            elif is_timeout:
                reason = f"Hard timeout ({per_attempt_timeout}s) on '{current_model}'"
            else:
                detail = str(exc).strip() or exc_name
                reason = f"Model error on '{current_model}': {detail[:80]}"
            model_pool.switch_reasoning_model(reason=reason)
            await asyncio.sleep(0.1)

    raise last_error or RuntimeError("All models in dynamic reasoning pool exhausted.")


async def call_vision_with_dynamic_switch(
    prompt: str,
    data_url: str,
    max_tokens: int = 300,
    temperature: float = 0.0,
    max_attempts: int = 3,
) -> str:
    """
    Executes Groq VLM call with automatic instant failover if a rate limit (429) is hit,
    then tries a Google/Gemma vision fallback when Groq is unavailable or fails.
    """
    groq_key = get_groq_api_key()
    gemma_key = get_gemma_api_key()
    last_error = None

    if groq_key:
        from groq import Groq
        client = Groq(api_key=groq_key)
        for attempt in range(max_attempts):
            current_model = model_pool.get_active_vision_model()
            try:
                def _sync():
                    res = client.chat.completions.create(
                        model=current_model,
                        messages=[{
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": data_url}},
                            ],
                        }],
                        max_tokens=max_tokens,
                        temperature=temperature,
                    )
                    return res.choices[0].message.content

                return await asyncio.wait_for(asyncio.to_thread(_sync), timeout=14.0)
            except Exception as exc:
                last_error = exc
                err_str = str(exc).lower()
                is_rate_limit = "429" in err_str or "rate limit" in err_str or "quota" in err_str
                reason = f"Rate limit (429) on '{current_model}'" if is_rate_limit else f"Vision error ({exc})"
                model_pool.switch_vision_model(reason=reason)
                await asyncio.sleep(0.4)

    if gemma_key:
        try:
            return await call_gemma_vision_fallback(prompt, data_url)
        except Exception as gemma_exc:
            last_error = gemma_exc if last_error is None else last_error

    if last_error:
        raise last_error
    raise RuntimeError("Neither Groq nor Gemma vision models were available.")

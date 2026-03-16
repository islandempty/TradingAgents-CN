"""
统一模型解析服务。

收口 quick/deep/test 模型的 provider、base_url、api_key 和运行参数解析逻辑，
避免多个服务各自维护一套重复且不一致的映射规则。
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from app.core.database import get_mongo_db, get_mongo_db_sync

logger = logging.getLogger("app.services.model_resolver")


DEFAULT_QUICK_MODEL = "glm-3-turbo"
DEFAULT_DEEP_MODEL = "glm-4"

PROVIDER_ALIASES = {
    "bigmodel": "zhipu",
    "glm": "zhipu",
    "qwen": "dashscope",
    "alibaba": "dashscope",
}

DEFAULT_PROVIDER_BY_MODEL = {
    "qwen-turbo": "dashscope",
    "qwen-plus": "dashscope",
    "qwen-max": "dashscope",
    "qwen-plus-latest": "dashscope",
    "qwen-max-longcontext": "dashscope",
    "gpt-3.5-turbo": "openai",
    "gpt-4": "openai",
    "gpt-4-turbo": "openai",
    "gpt-4o": "openai",
    "gpt-4o-mini": "openai",
    "gemini-pro": "google",
    "gemini-2.0-flash": "google",
    "gemini-2.0-flash-thinking-exp": "google",
    "deepseek-chat": "deepseek",
    "deepseek-coder": "deepseek",
    "glm-4": "zhipu",
    "glm-4-plus": "zhipu",
    "glm-4.6": "zhipu",
    "glm-3-turbo": "zhipu",
    "chatglm3-6b": "zhipu",
}

DEFAULT_BASE_URLS = {
    "google": "https://generativelanguage.googleapis.com/v1beta",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com",
    "anthropic": "https://api.anthropic.com",
    "openrouter": "https://openrouter.ai/api/v1",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "qianfan": "https://qianfan.baidubce.com/v2",
    "302ai": "https://api.302.ai/v1",
    "oneapi": "https://api.openai.com/v1",
    "newapi": "https://api.openai.com/v1",
    "custom_aggregator": "https://api.openai.com/v1",
    "custom_openai": "https://api.openai.com/v1",
    "ollama": "http://localhost:11434/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
}

ENV_KEY_MAP = {
    "google": "GOOGLE_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "siliconflow": "SILICONFLOW_API_KEY",
    "qianfan": "QIANFAN_API_KEY",
    "302ai": "AI302_API_KEY",
    "oneapi": "ONEAPI_API_KEY",
    "newapi": "NEWAPI_API_KEY",
    "custom_aggregator": "CUSTOM_AGGREGATOR_API_KEY",
    "custom_openai": "CUSTOM_OPENAI_API_KEY",
    "ollama": "OLLAMA_API_KEY",
    "zhipu": "ZHIPU_API_KEY",
}

DEFAULT_TEST_MODELS = {
    "zhipu": DEFAULT_QUICK_MODEL,
    "siliconflow": "Qwen/Qwen2.5-7B-Instruct",
    "default": "gpt-3.5-turbo",
}


def canonicalize_provider(provider: Optional[str]) -> str:
    raw = (provider or "").strip().lower()
    return PROVIDER_ALIASES.get(raw, raw)


def get_default_provider_by_model(model_name: str) -> str:
    provider = DEFAULT_PROVIDER_BY_MODEL.get(model_name, "zhipu")
    return canonicalize_provider(provider)


def get_default_backend_url(provider: Optional[str]) -> str:
    normalized = canonicalize_provider(provider)
    return DEFAULT_BASE_URLS.get(normalized, DEFAULT_BASE_URLS["openai"])


def get_env_api_key_for_provider(provider: Optional[str]) -> Optional[str]:
    normalized = canonicalize_provider(provider)
    env_key = ENV_KEY_MAP.get(normalized)
    if env_key:
        value = os.getenv(env_key)
        if is_effective_secret(value):
            return value
    return None


def is_effective_secret(secret: Optional[str]) -> bool:
    return bool(secret and secret.strip() and secret != "your-api-key")


def get_default_test_model(provider: Optional[str], requested: Optional[str] = None) -> str:
    if requested:
        return requested
    normalized = canonicalize_provider(provider)
    return DEFAULT_TEST_MODELS.get(normalized, DEFAULT_TEST_MODELS["default"])


@dataclass
class ResolvedModelEndpoint:
    provider: str
    model_name: str
    api_base: str
    api_key: Optional[str]
    max_tokens: int = 4000
    temperature: float = 0.7
    timeout: int = 180
    retry_times: int = 3
    provider_source: str = "default"
    config_source: str = "default"

    def to_runtime_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResolvedModelPair:
    quick: ResolvedModelEndpoint
    deep: ResolvedModelEndpoint


def _build_endpoint_from_docs(
    model_name: str,
    model_doc: Optional[Dict[str, Any]],
    provider_doc: Optional[Dict[str, Any]],
    provider_hint: Optional[str] = None,
) -> ResolvedModelEndpoint:
    provider = canonicalize_provider(
        (model_doc or {}).get("provider") or provider_hint or (provider_doc or {}).get("name") or get_default_provider_by_model(model_name)
    )
    model_api_key = (model_doc or {}).get("api_key")
    provider_api_key = (provider_doc or {}).get("api_key")
    api_key = model_api_key if is_effective_secret(model_api_key) else None
    provider_source = "default"

    if api_key:
        provider_source = "model_config"
    elif is_effective_secret(provider_api_key):
        api_key = provider_api_key
        provider_source = "provider_config"
    else:
        api_key = get_env_api_key_for_provider(provider)
        if api_key:
            provider_source = "environment"

    api_base = (
        (model_doc or {}).get("api_base")
        or (provider_doc or {}).get("default_base_url")
        or get_default_backend_url(provider)
    )

    config_source = "default"
    if model_doc:
        config_source = "model_config"
    elif provider_doc:
        config_source = "provider_config"

    return ResolvedModelEndpoint(
        provider=provider,
        model_name=model_name,
        api_base=api_base,
        api_key=api_key,
        max_tokens=int((model_doc or {}).get("max_tokens", 4000)),
        temperature=float((model_doc or {}).get("temperature", 0.7)),
        timeout=int((model_doc or {}).get("timeout", 180)),
        retry_times=int((model_doc or {}).get("retry_times", 3)),
        provider_source=provider_source,
        config_source=config_source,
    )


async def resolve_model_endpoint(
    model_name: Optional[str],
    provider_hint: Optional[str] = None,
) -> ResolvedModelEndpoint:
    resolved_name = model_name or DEFAULT_QUICK_MODEL
    db = get_mongo_db()
    config_doc = await db.system_configs.find_one({"is_active": True}, sort=[("version", -1)])

    model_doc = None
    provider_doc = None
    if config_doc:
        for item in config_doc.get("llm_configs", []):
            if item.get("model_name") == resolved_name:
                model_doc = item
                break

    provider = canonicalize_provider(
        (model_doc or {}).get("provider") or provider_hint or get_default_provider_by_model(resolved_name)
    )
    provider_doc = await db.llm_providers.find_one({"name": provider})
    return _build_endpoint_from_docs(resolved_name, model_doc, provider_doc, provider_hint)


def resolve_model_endpoint_sync(
    model_name: Optional[str],
    provider_hint: Optional[str] = None,
) -> ResolvedModelEndpoint:
    resolved_name = model_name or DEFAULT_QUICK_MODEL
    db = get_mongo_db_sync()
    config_doc = db.system_configs.find_one({"is_active": True}, sort=[("version", -1)])

    model_doc = None
    if config_doc:
        for item in config_doc.get("llm_configs", []):
            if item.get("model_name") == resolved_name:
                model_doc = item
                break

    provider = canonicalize_provider(
        (model_doc or {}).get("provider") or provider_hint or get_default_provider_by_model(resolved_name)
    )
    provider_doc = db.llm_providers.find_one({"name": provider})
    return _build_endpoint_from_docs(resolved_name, model_doc, provider_doc, provider_hint)


async def resolve_model_pair(
    quick_model: Optional[str] = None,
    deep_model: Optional[str] = None,
) -> ResolvedModelPair:
    quick = await resolve_model_endpoint(quick_model or DEFAULT_QUICK_MODEL)
    deep = await resolve_model_endpoint(deep_model or DEFAULT_DEEP_MODEL)
    return ResolvedModelPair(quick=quick, deep=deep)


def resolve_model_pair_sync(
    quick_model: Optional[str] = None,
    deep_model: Optional[str] = None,
) -> ResolvedModelPair:
    quick = resolve_model_endpoint_sync(quick_model or DEFAULT_QUICK_MODEL)
    deep = resolve_model_endpoint_sync(deep_model or DEFAULT_DEEP_MODEL)
    return ResolvedModelPair(quick=quick, deep=deep)


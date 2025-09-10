"""LLM API Client abstraction layer.

Provides unified interface for Claude and OpenAI APIs with async HTTP clients,
error handling, and response validation.
"""
from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Union

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)


class LLMProvider(Enum):
    """Supported LLM providers."""
    CLAUDE = "claude"
    OPENAI = "openai"


@dataclass
class LLMResponse:
    """Standardized LLM response format."""
    content: str
    tokens_used: int
    cost_estimate: float
    provider: LLMProvider
    model: str
    timestamp: datetime
    metadata: Dict[str, Any]


@dataclass
class LLMConfig:
    """LLM configuration settings."""
    provider: LLMProvider
    api_key: str
    model: str
    base_url: Optional[str] = None
    timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0


class LLMClientError(Exception):
    """Base exception for LLM client errors."""
    pass


class LLMRateLimitError(LLMClientError):
    """Rate limit exceeded exception."""
    pass


class LLMTokenLimitError(LLMClientError):
    """Token limit exceeded exception."""
    pass


class LLMClient(ABC):
    """Abstract base class for LLM clients."""
    
    def __init__(self, hass: HomeAssistant, config: LLMConfig):
        """Initialize LLM client."""
        self._hass = hass
        self._config = config
        self._session = async_get_clientsession(hass)
    
    @abstractmethod
    async def complete(
        self, 
        messages: List[Dict[str, str]], 
        **kwargs
    ) -> LLMResponse:
        """Complete a chat conversation."""
        pass
    
    @abstractmethod
    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text."""
        pass
    
    @abstractmethod
    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost for token usage."""
        pass


class ClaudeClient(LLMClient):
    """Claude API client implementation."""
    
    BASE_URL = "https://api.anthropic.com/v1"
    
    # Token pricing (per 1K tokens) - update as needed
    PRICING = {
        "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
        "claude-3-haiku-20240307": {"input": 0.00025, "output": 0.00125},
    }
    
    async def complete(
        self, 
        messages: List[Dict[str, str]], 
        **kwargs
    ) -> LLMResponse:
        """Complete using Claude API."""
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._config.api_key,
            "anthropic-version": "2023-06-01"
        }
        
        # Convert OpenAI format to Claude format
        system_message = ""
        claude_messages = []
        
        for msg in messages:
            if msg["role"] == "system":
                system_message = msg["content"]
            else:
                claude_messages.append(msg)
        
        payload = {
            "model": self._config.model,
            "max_tokens": kwargs.get("max_tokens", 4000),
            "temperature": kwargs.get("temperature", 0.7),
            "messages": claude_messages
        }
        
        if system_message:
            payload["system"] = system_message
        
        start_time = datetime.now()
        
        try:
            async with self._session.post(
                f"{self.BASE_URL}/messages",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=self._config.timeout)
            ) as response:
                if response.status == 429:
                    raise LLMRateLimitError("Claude API rate limit exceeded")
                
                response.raise_for_status()
                result = await response.json()
                
                content = result["content"][0]["text"]
                input_tokens = result["usage"]["input_tokens"]
                output_tokens = result["usage"]["output_tokens"]
                
                return LLMResponse(
                    content=content,
                    tokens_used=input_tokens + output_tokens,
                    cost_estimate=self.estimate_cost(input_tokens, output_tokens),
                    provider=LLMProvider.CLAUDE,
                    model=self._config.model,
                    timestamp=start_time,
                    metadata={
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "response_time": (datetime.now() - start_time).total_seconds()
                    }
                )
                
        except aiohttp.ClientError as e:
            _LOGGER.error("Claude API client error: %s", e)
            raise LLMClientError(f"Claude API error: {e}") from e
        except asyncio.TimeoutError as e:
            _LOGGER.error("Claude API timeout")
            raise LLMClientError("Claude API timeout") from e
    
    def estimate_tokens(self, text: str) -> int:
        """Estimate token count (rough approximation)."""
        # Claude uses roughly 4 characters per token
        return len(text) // 4
    
    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost based on token usage."""
        if self._config.model not in self.PRICING:
            return 0.0
            
        pricing = self.PRICING[self._config.model]
        input_cost = (input_tokens / 1000) * pricing["input"]
        output_cost = (output_tokens / 1000) * pricing["output"]
        
        return input_cost + output_cost


class OpenAIClient(LLMClient):
    """OpenAI API client implementation."""
    
    BASE_URL = "https://api.openai.com/v1"
    
    # Token pricing (per 1K tokens) - update as needed
    PRICING = {
        "gpt-4": {"input": 0.03, "output": 0.06},
        "gpt-4-turbo": {"input": 0.01, "output": 0.03},
        "gpt-3.5-turbo": {"input": 0.001, "output": 0.002},
    }
    
    async def complete(
        self, 
        messages: List[Dict[str, str]], 
        **kwargs
    ) -> LLMResponse:
        """Complete using OpenAI API."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._config.api_key}"
        }
        
        payload = {
            "model": self._config.model,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", 4000),
            "temperature": kwargs.get("temperature", 0.7)
        }
        
        start_time = datetime.now()
        
        try:
            async with self._session.post(
                f"{self.BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=self._config.timeout)
            ) as response:
                if response.status == 429:
                    raise LLMRateLimitError("OpenAI API rate limit exceeded")
                
                response.raise_for_status()
                result = await response.json()
                
                content = result["choices"][0]["message"]["content"]
                input_tokens = result["usage"]["prompt_tokens"]
                output_tokens = result["usage"]["completion_tokens"]
                
                return LLMResponse(
                    content=content,
                    tokens_used=input_tokens + output_tokens,
                    cost_estimate=self.estimate_cost(input_tokens, output_tokens),
                    provider=LLMProvider.OPENAI,
                    model=self._config.model,
                    timestamp=start_time,
                    metadata={
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "response_time": (datetime.now() - start_time).total_seconds()
                    }
                )
                
        except aiohttp.ClientError as e:
            _LOGGER.error("OpenAI API client error: %s", e)
            raise LLMClientError(f"OpenAI API error: {e}") from e
        except asyncio.TimeoutError as e:
            _LOGGER.error("OpenAI API timeout")
            raise LLMClientError("OpenAI API timeout") from e
    
    def estimate_tokens(self, text: str) -> int:
        """Estimate token count (rough approximation)."""
        # GPT models use roughly 4 characters per token
        return len(text) // 4
    
    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost based on token usage."""
        if self._config.model not in self.PRICING:
            return 0.0
            
        pricing = self.PRICING[self._config.model]
        input_cost = (input_tokens / 1000) * pricing["input"]
        output_cost = (output_tokens / 1000) * pricing["output"]
        
        return input_cost + output_cost


class LLMClientFactory:
    """Factory for creating LLM clients."""
    
    @staticmethod
    def create_client(hass: HomeAssistant, config: LLMConfig) -> LLMClient:
        """Create appropriate LLM client based on provider."""
        if config.provider == LLMProvider.CLAUDE:
            return ClaudeClient(hass, config)
        elif config.provider == LLMProvider.OPENAI:
            return OpenAIClient(hass, config)
        else:
            raise ValueError(f"Unsupported LLM provider: {config.provider}")


class ResilientLLMClient:
    """Wrapper that provides retry logic and fallback capabilities."""
    
    def __init__(
        self, 
        primary_client: LLMClient, 
        fallback_client: Optional[LLMClient] = None
    ):
        """Initialize resilient client with primary and optional fallback."""
        self._primary = primary_client
        self._fallback = fallback_client
    
    async def complete(
        self, 
        messages: List[Dict[str, str]], 
        **kwargs
    ) -> LLMResponse:
        """Complete with retry and fallback logic."""
        # Try primary client with retries
        for attempt in range(self._primary._config.max_retries):
            try:
                return await self._primary.complete(messages, **kwargs)
            except LLMRateLimitError:
                if attempt < self._primary._config.max_retries - 1:
                    await asyncio.sleep(
                        self._primary._config.retry_delay * (2 ** attempt)
                    )
                    continue
                # If primary rate limited and fallback available, try fallback
                if self._fallback:
                    _LOGGER.warning(
                        "Primary LLM rate limited, trying fallback"
                    )
                    break
                raise
            except LLMClientError as e:
                if attempt < self._primary._config.max_retries - 1:
                    _LOGGER.warning(
                        "LLM request failed (attempt %d/%d): %s", 
                        attempt + 1, 
                        self._primary._config.max_retries, 
                        e
                    )
                    await asyncio.sleep(
                        self._primary._config.retry_delay * (2 ** attempt)
                    )
                    continue
                # If all retries failed and fallback available
                if self._fallback:
                    _LOGGER.warning(
                        "Primary LLM failed after retries, trying fallback"
                    )
                    break
                raise
        
        # Try fallback if available
        if self._fallback:
            try:
                return await self._fallback.complete(messages, **kwargs)
            except LLMClientError as e:
                _LOGGER.error("Both primary and fallback LLMs failed: %s", e)
                raise
        
        # Should not reach here
        raise LLMClientError("All LLM attempts failed")
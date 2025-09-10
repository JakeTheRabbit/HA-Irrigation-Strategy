"""LLM Integration for AppDaemon Crop Steering.

Provides LLM-enhanced decision making for autonomous irrigation control
while maintaining the existing rule-based safety systems.
"""
from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "LLMEnhancedCropSteering"
]
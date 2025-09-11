"""GPT-4o Configuration and Integration for Crop Steering System.

Implements GPT-4o specific features including temperature control,
verbosity management, and optimized pricing for 2024 models.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Any

_LOGGER = logging.getLogger(__name__)


class GPT4oModel(Enum):
    """GPT-4o model variants with 2024 pricing."""
    MINI = "gpt-4o-mini"     # $0.15/1M input, $0.60/1M output
    STANDARD = "gpt-4o"      # $2.50/1M input, $10.00/1M output


class AnalysisDepth(Enum):
    """GPT-4o analysis depth levels."""
    BASIC = "basic"         # Fast, basic logic
    STANDARD = "standard"   # Standard analysis
    DETAILED = "detailed"   # Deeper analysis


class Verbosity(Enum):
    """GPT-4o verbosity control."""
    LOW = "low"             # Concise responses
    MEDIUM = "medium"       # Include explanations
    HIGH = "high"           # Detailed analysis


@dataclass
class GPT4oConfig:
    """GPT-4o specific configuration."""
    
    # Model selection
    default_model: GPT4oModel = GPT4oModel.MINI
    emergency_model: GPT4oModel = GPT4oModel.STANDARD
    
    # Analysis configuration
    default_analysis: AnalysisDepth = AnalysisDepth.BASIC
    emergency_analysis: AnalysisDepth = AnalysisDepth.DETAILED
    
    # Verbosity configuration
    default_verbosity: Verbosity = Verbosity.LOW
    enhanced_verbosity: Verbosity = Verbosity.MEDIUM
    emergency_verbosity: Verbosity = Verbosity.HIGH
    
    # Context window management
    max_input_tokens: int = 8000      # Well under 272K limit
    max_output_tokens: int = 2000     # Well under 128K limit
    
    # Temperature settings
    default_temperature: float = 0.1   # Consistent decisions
    enhanced_temperature: float = 0.3  # Some creativity
    emergency_temperature: float = 0.5 # More exploration
    
    # Caching configuration (90% discount!)
    enable_caching: bool = True
    cache_ttl_minutes: int = 1440     # 24 hours
    similarity_threshold: float = 0.95
    
    # Function calling (GPT-4o feature)
    enable_function_calling: bool = True
    function_schema: Optional[str] = None


class GPT4oCostCalculator:
    """Calculate costs for GPT-4o models."""
    
    # 2024 Pricing (per million tokens)
    PRICING = {
        GPT4oModel.MINI: {"input": 0.15, "output": 0.60},
        GPT4oModel.STANDARD: {"input": 2.50, "output": 10.00}
    }
    
    @classmethod
    def calculate_cost(
        cls,
        model: GPT4oModel,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0
    ) -> float:
        """Calculate cost for a GPT-4o API call.
        
        Args:
            model: GPT-4o model variant
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            cached_tokens: Number of cached input tokens
            
        Returns:
            Total cost in USD
        """
        pricing = cls.PRICING[model]
        
        # Calculate input cost with caching discount
        uncached_tokens = input_tokens - cached_tokens
        input_cost = (uncached_tokens * pricing["input"] / 1_000_000)
        
        # Add cached token cost (90% discount)
        if cached_tokens > 0:
            cached_cost = (cached_tokens * pricing["input"] * 0.1 / 1_000_000)
            input_cost += cached_cost
        
        # Calculate output cost
        output_cost = (output_tokens * pricing["output"] / 1_000_000)
        
        return input_cost + output_cost
    
    @classmethod
    def estimate_daily_cost(
        cls,
        model: GPT4oModel,
        calls_per_day: int,
        avg_input_tokens: int = 1000,
        avg_output_tokens: int = 200,
        cache_hit_rate: float = 0.5
    ) -> float:
        """Estimate daily cost for GPT-4o usage.
        
        Args:
            model: GPT-4o model variant
            calls_per_day: Number of API calls per day
            avg_input_tokens: Average input tokens per call
            avg_output_tokens: Average output tokens per call
            cache_hit_rate: Percentage of calls hitting cache
            
        Returns:
            Estimated daily cost in USD
        """
        cached_calls = int(calls_per_day * cache_hit_rate)
        uncached_calls = calls_per_day - cached_calls
        
        # Calculate uncached cost
        uncached_cost = uncached_calls * cls.calculate_cost(
            model, avg_input_tokens, avg_output_tokens, 0
        )
        
        # Calculate cached cost (90% discount on input)
        cached_cost = cached_calls * cls.calculate_cost(
            model, avg_input_tokens, avg_output_tokens, avg_input_tokens
        )
        
        return uncached_cost + cached_cost


class GPT4oDecisionRouter:
    """Route decisions to appropriate GPT-4o models based on urgency."""
    
    def __init__(self, config: GPT4oConfig):
        """Initialize the decision router.
        
        Args:
            config: GPT-4o configuration
        """
        self.config = config
    
    def select_model(
        self,
        urgency: str = "normal",
        vwc: float = None,
        ec: float = None,
        confidence_required: float = 0.7
    ) -> Tuple[GPT4oModel, AnalysisDepth, Verbosity]:
        """Select appropriate model based on conditions.
        
        Args:
            urgency: Decision urgency level
            vwc: Current VWC percentage
            ec: Current EC value
            confidence_required: Required confidence level
            
        Returns:
            Tuple of (model, analysis_depth, verbosity)
        """
        # Emergency conditions - use best model
        if self._is_emergency(vwc, ec):
            return (
                self.config.emergency_model,
                self.config.emergency_analysis,
                self.config.emergency_verbosity
            )
        
        # Enhanced conditions - use standard model
        if urgency in ["high", "complex"] or confidence_required > 0.8:
            return (
                self.config.emergency_model,
                self.config.emergency_analysis,
                self.config.emergency_verbosity
            )
        
        # Default conditions - use mini model
        return (
            self.config.default_model,
            self.config.default_analysis,
            self.config.default_verbosity
        )
    
    def _is_emergency(self, vwc: float = None, ec: float = None) -> bool:
        """Check if conditions warrant emergency response.
        
        Args:
            vwc: Current VWC percentage
            ec: Current EC value
            
        Returns:
            True if emergency conditions detected
        """
        if vwc is not None:
            if vwc < 35 or vwc > 85:  # Critical moisture levels
                return True
        
        if ec is not None:
            if ec > 6.0:  # Dangerous salt levels
                return True
        
        return False


def create_gpt4o_prompt(
    context: Dict[str, Any],
    model: GPT4oModel,
    analysis_depth: AnalysisDepth,
    verbosity: Verbosity
) -> str:
    """Create optimized prompt for GPT-4o.
    
    Args:
        context: Irrigation context data
        model: GPT-4o model being used
        analysis_depth: Analysis depth level
        verbosity: Response verbosity level
        
    Returns:
        Formatted prompt string
    """
    # Adjust prompt based on model capabilities
    if model == GPT4oModel.MINI:
        # Simple, direct prompt for mini
        prompt = f"""
Irrigation Decision (Quick Analysis):
VWC: {context.get('vwc', 0)}%
EC: {context.get('ec', 0)} mS/cm
Phase: {context.get('phase', 'Unknown')}

Should irrigate? Reply: YES/NO, duration (seconds), confidence (0-1)
"""
    
    else:  # GPT4oModel.STANDARD
        # Comprehensive prompt for standard
        prompt = f"""
Expert Crop Steering Irrigation Analysis

Complete Context:
{json.dumps(context, indent=2)}

Analyze all factors and provide:
1. Irrigation decision (YES/NO)
2. Optimal duration (seconds)
3. Scientific reasoning (2-3 sentences)
4. Risk assessment
5. Confidence level (0-1)
6. Alternative recommendations

Consider plant physiology, environmental conditions, and optimization goals.
"""
    
    
    # Add analysis depth and verbosity hints
    prompt += f"\n[Analysis: {analysis_depth.value}, Verbosity: {verbosity.value}]"
    
    return prompt


# Example usage configuration
DEFAULT_GPT4O_CONFIG = GPT4oConfig(
    default_model=GPT4oModel.MINI,
    emergency_model=GPT4oModel.STANDARD,
    max_input_tokens=8000,
    enable_caching=True,
    cache_ttl_minutes=1440  # 24 hours
)
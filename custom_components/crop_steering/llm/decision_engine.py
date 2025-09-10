"""LLM Decision Engine for Crop Steering System.

Integrates LLM capabilities with the existing rule-based irrigation system,
providing enhanced decision making while maintaining safety-first approach.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .client import (
    LLMClient, 
    LLMClientFactory, 
    LLMConfig, 
    LLMProvider, 
    ResilientLLMClient,
    LLMClientError
)
from .cost_optimizer import CostOptimizer, BudgetConfig, CostTier
from .prompts import PromptManager, PromptType, PromptComplexity, PromptContext

_LOGGER = logging.getLogger(__name__)


@dataclass
class LLMDecision:
    """LLM decision response structure."""
    decision: str  # "irrigate", "wait", "emergency", "phase_change"
    confidence: float  # 0-100
    reasoning: str
    shot_size_ml: Optional[int] = None
    urgency: str = "medium"  # "low", "medium", "high", "emergency"
    next_check_minutes: int = 15
    warnings: List[str] = None
    parameters: Dict[str, Any] = None
    llm_metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        """Initialize default values."""
        if self.warnings is None:
            self.warnings = []
        if self.parameters is None:
            self.parameters = {}
        if self.llm_metadata is None:
            self.llm_metadata = {}


class LLMDecisionEngine:
    """Enhanced decision engine combining LLM insights with rule-based safety."""
    
    def __init__(
        self,
        hass: HomeAssistant,
        llm_config: LLMConfig,
        budget_config: BudgetConfig,
        fallback_llm_config: Optional[LLMConfig] = None
    ):
        """Initialize LLM decision engine."""
        self._hass = hass
        self._llm_config = llm_config
        self._budget_config = budget_config
        
        # Initialize components
        self._prompt_manager = PromptManager()
        self._cost_optimizer = CostOptimizer(hass, budget_config)
        
        # Create LLM clients
        primary_client = LLMClientFactory.create_client(hass, llm_config)
        fallback_client = None
        if fallback_llm_config:
            fallback_client = LLMClientFactory.create_client(hass, fallback_llm_config)
        
        self._llm_client = ResilientLLMClient(primary_client, fallback_client)
        
        # Performance tracking
        self._decision_history: List[Dict] = []
        self._performance_metrics = {
            "total_decisions": 0,
            "llm_decisions": 0,
            "rule_decisions": 0,
            "total_cost": 0.0,
            "avg_confidence": 0.0,
            "error_count": 0
        }
        
        # Safety thresholds for rule-based fallbacks
        self._safety_thresholds = {
            "min_confidence": 70.0,  # Minimum LLM confidence to trust decision
            "max_vwc_critical": 80.0,  # Critical VWC level
            "min_vwc_critical": 40.0,  # Critical low VWC level
            "max_ec_critical": 5.0,    # Critical EC level
            "emergency_response_time": 300  # 5 minutes for emergency response
        }
    
    async def initialize(self) -> None:
        """Initialize the decision engine."""
        try:
            await self._cost_optimizer.initialize()
            _LOGGER.info("LLM Decision Engine initialized successfully")
        except Exception as e:
            _LOGGER.error("Failed to initialize LLM Decision Engine: %s", e)
            raise
    
    async def make_irrigation_decision(
        self,
        zone_id: int,
        current_phase: str,
        sensor_data: Dict[str, Any],
        system_config: Dict[str, Any],
        historical_data: Optional[Dict[str, Any]] = None,
        emergency: bool = False
    ) -> LLMDecision:
        """Make irrigation decision combining LLM analysis with rule-based safety."""
        try:
            _LOGGER.debug("Making irrigation decision for zone %d", zone_id)
            
            # First, check critical safety conditions
            safety_decision = self._check_safety_conditions(zone_id, sensor_data, emergency)
            if safety_decision:
                return safety_decision
            
            # Determine if we should use LLM or fallback to rules
            use_llm, reason = await self._should_use_llm(emergency)
            
            if use_llm:
                llm_decision = await self._get_llm_decision(
                    zone_id, current_phase, sensor_data, system_config, historical_data, emergency
                )
                
                # Validate LLM decision against safety rules
                validated_decision = self._validate_llm_decision(llm_decision, sensor_data, system_config)
                
                # Record usage for cost tracking
                if hasattr(llm_decision, "llm_metadata") and "response" in llm_decision.llm_metadata:
                    await self._cost_optimizer.record_usage(
                        llm_decision.llm_metadata["response"],
                        "irrigation_decision",
                        zone_id
                    )
                
                return validated_decision
            else:
                _LOGGER.info("Using rule-based decision for zone %d: %s", zone_id, reason)
                return self._get_rule_based_decision(
                    zone_id, current_phase, sensor_data, system_config, reason
                )
                
        except Exception as e:
            _LOGGER.error("Error in irrigation decision for zone %d: %s", zone_id, e)
            # Fallback to rule-based decision on error
            return self._get_rule_based_decision(
                zone_id, current_phase, sensor_data, system_config, f"Error fallback: {e}"
            )
    
    async def _should_use_llm(self, emergency: bool = False) -> Tuple[bool, str]:
        """Determine if LLM should be used based on budget and conditions."""
        # Always use rules for emergencies unless specifically configured
        if emergency and self._budget_config.cost_tier != CostTier.PREMIUM:
            return False, "Emergency - using fast rule-based response"
        
        # Check budget availability
        estimated_cost = 0.02  # Rough estimate for irrigation decision
        budget_ok, budget_reason = await self._cost_optimizer.check_budget_availability(
            estimated_cost, "emergency" if emergency else "irrigation_decision"
        )
        
        if not budget_ok:
            return False, f"Budget limit: {budget_reason}"
        
        # Check cost tier settings
        recommendation = self._cost_optimizer.get_cost_optimization_recommendation(
            "irrigation_decision", estimated_cost
        )
        
        use_llm, _, details = recommendation
        if not use_llm:
            return False, details.get("reason", "Cost optimization fallback")
        
        return True, "Budget and conditions allow LLM usage"
    
    async def _get_llm_decision(
        self,
        zone_id: int,
        current_phase: str,
        sensor_data: Dict[str, Any],
        system_config: Dict[str, Any],
        historical_data: Optional[Dict[str, Any]] = None,
        emergency: bool = False
    ) -> LLMDecision:
        """Get decision from LLM."""
        try:
            # Determine prompt complexity based on budget settings
            complexity = self._prompt_manager.get_recommended_complexity(
                "irrigation_decision",
                self._budget_config.cost_tier.value,
                "emergency" if emergency else "medium"
            )
            
            # Create prompt context
            context = PromptContext(
                zone_id=zone_id,
                current_phase=current_phase,
                sensor_data=sensor_data,
                historical_data=historical_data,
                system_config=system_config,
                timestamp=datetime.now()
            )
            
            # Generate prompt
            prompt_data = self._prompt_manager.generate_prompt(
                PromptType.IRRIGATION_DECISION,
                context,
                complexity
            )
            
            # Prepare messages for LLM
            messages = [
                {"role": "system", "content": prompt_data["system"]},
                {"role": "user", "content": prompt_data["user"]}
            ]
            
            # Get LLM response
            response = await self._llm_client.complete(
                messages,
                max_tokens=2000,
                temperature=0.3  # Lower temperature for more consistent decisions
            )
            
            # Parse LLM response
            decision = self._parse_llm_response(response.content, zone_id)
            
            # Add LLM metadata
            decision.llm_metadata = {
                "response": response,
                "prompt_type": "irrigation_decision",
                "complexity": complexity.value,
                "provider": response.provider.value,
                "model": response.model,
                "tokens_used": response.tokens_used,
                "cost": response.cost_estimate
            }
            
            # Update performance metrics
            self._performance_metrics["llm_decisions"] += 1
            self._performance_metrics["total_cost"] += response.cost_estimate
            
            return decision
            
        except Exception as e:
            _LOGGER.error("LLM decision failed for zone %d: %s", zone_id, e)
            self._performance_metrics["error_count"] += 1
            raise
    
    def _parse_llm_response(self, response_content: str, zone_id: int) -> LLMDecision:
        """Parse LLM response into decision structure."""
        try:
            # Try to parse as JSON first
            if response_content.strip().startswith('{'):
                data = json.loads(response_content)
            else:
                # Handle non-JSON responses
                data = self._extract_decision_from_text(response_content)
            
            # Validate required fields
            decision = data.get("decision", "wait").lower()
            confidence = float(data.get("confidence", 50))
            reasoning = data.get("reasoning", "LLM analysis")
            
            # Validate decision options
            valid_decisions = ["irrigate", "wait", "emergency", "phase_change"]
            if decision not in valid_decisions:
                _LOGGER.warning("Invalid LLM decision '%s', defaulting to 'wait'", decision)
                decision = "wait"
                confidence = min(confidence, 50)  # Reduce confidence for invalid decision
            
            return LLMDecision(
                decision=decision,
                confidence=confidence,
                reasoning=reasoning,
                shot_size_ml=data.get("shot_size_ml"),
                urgency=data.get("urgency", "medium"),
                next_check_minutes=data.get("next_check_minutes", 15),
                warnings=data.get("warnings", []),
                parameters=data.get("parameters", {})
            )
            
        except Exception as e:
            _LOGGER.error("Failed to parse LLM response: %s", e)
            return LLMDecision(
                decision="wait",
                confidence=0,
                reasoning=f"Failed to parse LLM response: {e}",
                urgency="low"
            )
    
    def _extract_decision_from_text(self, text: str) -> Dict[str, Any]:
        """Extract decision information from unstructured text response."""
        text_lower = text.lower()
        
        # Extract decision
        decision = "wait"  # default
        if "irrigate" in text_lower or "irrigation" in text_lower:
            decision = "irrigate"
        elif "emergency" in text_lower:
            decision = "emergency"
        elif "phase" in text_lower and "change" in text_lower:
            decision = "phase_change"
        
        # Extract confidence (look for percentages)
        confidence = 50  # default
        import re
        conf_match = re.search(r'(\d+)%', text)
        if conf_match:
            confidence = min(100, max(0, int(conf_match.group(1))))
        
        # Extract reasoning (use first sentence or paragraph)
        reasoning = text.split('.')[0] if '.' in text else text[:100]
        
        return {
            "decision": decision,
            "confidence": confidence,
            "reasoning": reasoning.strip()
        }
    
    def _check_safety_conditions(
        self, 
        zone_id: int, 
        sensor_data: Dict[str, Any], 
        emergency: bool
    ) -> Optional[LLMDecision]:
        """Check critical safety conditions that override LLM decisions."""
        vwc_avg = (sensor_data.get("vwc_front", 0) + sensor_data.get("vwc_back", 0)) / 2
        ec_avg = (sensor_data.get("ec_front", 0) + sensor_data.get("ec_back", 0)) / 2
        
        # Critical high VWC - stop irrigation immediately
        if vwc_avg > self._safety_thresholds["max_vwc_critical"]:
            return LLMDecision(
                decision="wait",
                confidence=100,
                reasoning=f"SAFETY: Critical high VWC ({vwc_avg:.1f}%) - irrigation disabled",
                urgency="high",
                warnings=[f"VWC above critical threshold ({self._safety_thresholds['max_vwc_critical']}%)"]
            )
        
        # Critical low VWC - emergency irrigation
        if vwc_avg < self._safety_thresholds["min_vwc_critical"]:
            return LLMDecision(
                decision="irrigate",
                confidence=100,
                reasoning=f"SAFETY: Critical low VWC ({vwc_avg:.1f}%) - emergency irrigation required",
                shot_size_ml=50,  # Conservative emergency shot
                urgency="emergency",
                next_check_minutes=5,
                warnings=[f"VWC below critical threshold ({self._safety_thresholds['min_vwc_critical']}%)"]
            )
        
        # Critical high EC - dilution may be needed
        if ec_avg > self._safety_thresholds["max_ec_critical"]:
            return LLMDecision(
                decision="irrigate",
                confidence=90,
                reasoning=f"SAFETY: High EC ({ec_avg:.2f}) - dilution irrigation",
                shot_size_ml=25,  # Small dilution shot
                urgency="high",
                next_check_minutes=10,
                warnings=[f"EC above critical threshold ({self._safety_thresholds['max_ec_critical']})"]
            )
        
        return None  # No safety override needed
    
    def _validate_llm_decision(
        self, 
        llm_decision: LLMDecision, 
        sensor_data: Dict[str, Any], 
        system_config: Dict[str, Any]
    ) -> LLMDecision:
        """Validate LLM decision against safety rules and constraints."""
        validated_decision = llm_decision
        
        # Check confidence threshold
        if llm_decision.confidence < self._safety_thresholds["min_confidence"]:
            validated_decision.decision = "wait"
            validated_decision.reasoning += f" [Low confidence {llm_decision.confidence:.1f}% - defaulting to wait]"
            validated_decision.warnings.append(f"LLM confidence below threshold ({self._safety_thresholds['min_confidence']}%)")
        
        # Validate shot size if irrigating
        if validated_decision.decision == "irrigate":
            max_shot = system_config.get("max_shot_size_ml", 200)
            min_shot = system_config.get("min_shot_size_ml", 10)
            
            if validated_decision.shot_size_ml:
                # Clamp shot size to safe limits
                if validated_decision.shot_size_ml > max_shot:
                    validated_decision.shot_size_ml = max_shot
                    validated_decision.warnings.append(f"Shot size limited to maximum ({max_shot}mL)")
                elif validated_decision.shot_size_ml < min_shot:
                    validated_decision.shot_size_ml = min_shot
                    validated_decision.warnings.append(f"Shot size increased to minimum ({min_shot}mL)")
            else:
                # Use system default if not specified
                validated_decision.shot_size_ml = system_config.get("default_shot_size_ml", 100)
        
        # Validate next check interval
        if validated_decision.next_check_minutes < 1:
            validated_decision.next_check_minutes = 1
        elif validated_decision.next_check_minutes > 60:
            validated_decision.next_check_minutes = 60
        
        return validated_decision
    
    def _get_rule_based_decision(
        self,
        zone_id: int,
        current_phase: str,
        sensor_data: Dict[str, Any],
        system_config: Dict[str, Any],
        reason: str
    ) -> LLMDecision:
        """Generate rule-based decision as fallback."""
        vwc_avg = (sensor_data.get("vwc_front", 0) + sensor_data.get("vwc_back", 0)) / 2
        vwc_threshold = system_config.get("vwc_threshold", 60)
        target_vwc = system_config.get("target_vwc", 65)
        
        # Simple rule-based logic
        if vwc_avg < vwc_threshold:
            shot_size = system_config.get("default_shot_size_ml", 100)
            
            # Adjust shot size based on how far below threshold
            vwc_deficit = vwc_threshold - vwc_avg
            if vwc_deficit > 10:
                shot_size = int(shot_size * 1.5)  # Larger shot for bigger deficit
            elif vwc_deficit < 3:
                shot_size = int(shot_size * 0.7)  # Smaller shot for small deficit
            
            return LLMDecision(
                decision="irrigate",
                confidence=80,
                reasoning=f"Rule-based: VWC {vwc_avg:.1f}% below threshold {vwc_threshold}%. {reason}",
                shot_size_ml=shot_size,
                urgency="medium",
                next_check_minutes=15
            )
        else:
            return LLMDecision(
                decision="wait",
                confidence=75,
                reasoning=f"Rule-based: VWC {vwc_avg:.1f}% above threshold {vwc_threshold}%. {reason}",
                urgency="low",
                next_check_minutes=30
            )
    
    async def analyze_phase_transition(
        self,
        zone_id: int,
        current_phase: str,
        sensor_data: Dict[str, Any],
        system_config: Dict[str, Any],
        phase_history: Optional[Dict[str, Any]] = None
    ) -> LLMDecision:
        """Analyze if phase transition should occur."""
        try:
            # Check if LLM should be used
            use_llm, reason = await self._should_use_llm(False)
            
            if use_llm:
                # Create context for phase analysis
                context = PromptContext(
                    zone_id=zone_id,
                    current_phase=current_phase,
                    sensor_data=sensor_data,
                    historical_data=phase_history,
                    system_config=system_config,
                    timestamp=datetime.now()
                )
                
                # Generate phase transition prompt
                prompt_data = self._prompt_manager.generate_prompt(
                    PromptType.PHASE_TRANSITION,
                    context,
                    PromptComplexity.STANDARD
                )
                
                messages = [
                    {"role": "system", "content": prompt_data["system"]},
                    {"role": "user", "content": prompt_data["user"]}
                ]
                
                response = await self._llm_client.complete(messages, max_tokens=1500)
                decision = self._parse_llm_response(response.content, zone_id)
                
                # Record usage
                await self._cost_optimizer.record_usage(response, "phase_transition", zone_id)
                
                return decision
            else:
                # Rule-based phase transition logic
                return self._get_rule_based_phase_decision(
                    zone_id, current_phase, sensor_data, system_config, reason
                )
                
        except Exception as e:
            _LOGGER.error("Phase transition analysis failed for zone %d: %s", zone_id, e)
            return LLMDecision(
                decision="wait",
                confidence=50,
                reasoning=f"Phase analysis error - maintaining current phase: {e}",
                urgency="low"
            )
    
    def _get_rule_based_phase_decision(
        self,
        zone_id: int,
        current_phase: str,
        sensor_data: Dict[str, Any],
        system_config: Dict[str, Any],
        reason: str
    ) -> LLMDecision:
        """Rule-based phase transition logic."""
        # Simplified phase transition rules
        vwc_avg = (sensor_data.get("vwc_front", 0) + sensor_data.get("vwc_back", 0)) / 2
        target_vwc = system_config.get("target_vwc", 65)
        
        # Basic phase transition logic
        if current_phase == "P0" and vwc_avg < target_vwc * 0.9:  # 90% of target
            return LLMDecision(
                decision="phase_change",
                confidence=75,
                reasoning=f"Rule-based P0→P1: VWC {vwc_avg:.1f}% indicates dryback complete. {reason}",
                parameters={"next_phase": "P1"},
                urgency="medium"
            )
        elif current_phase == "P1" and vwc_avg >= target_vwc:
            return LLMDecision(
                decision="phase_change",
                confidence=75,
                reasoning=f"Rule-based P1→P2: Target VWC {target_vwc}% reached. {reason}",
                parameters={"next_phase": "P2"},
                urgency="medium"
            )
        else:
            return LLMDecision(
                decision="wait",
                confidence=70,
                reasoning=f"Rule-based: Phase {current_phase} conditions not met for transition. {reason}",
                urgency="low"
            )
    
    async def get_usage_report(self, days: int = 7) -> Dict[str, Any]:
        """Get comprehensive usage and performance report."""
        cost_report = await self._cost_optimizer.generate_usage_report(days)
        
        # Add decision engine specific metrics
        cost_report["decision_engine_metrics"] = self._performance_metrics.copy()
        
        # Calculate efficiency metrics
        total_decisions = self._performance_metrics["total_decisions"]
        if total_decisions > 0:
            cost_report["decision_engine_metrics"]["llm_usage_rate"] = (
                self._performance_metrics["llm_decisions"] / total_decisions
            )
            cost_report["decision_engine_metrics"]["avg_cost_per_decision"] = (
                self._performance_metrics["total_cost"] / self._performance_metrics["llm_decisions"]
                if self._performance_metrics["llm_decisions"] > 0 else 0
            )
            cost_report["decision_engine_metrics"]["error_rate"] = (
                self._performance_metrics["error_count"] / total_decisions
            )
        
        return cost_report
    
    def update_safety_thresholds(self, new_thresholds: Dict[str, float]) -> None:
        """Update safety thresholds for decision validation."""
        self._safety_thresholds.update(new_thresholds)
        _LOGGER.info("Updated safety thresholds: %s", new_thresholds)
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get current system status and health."""
        return {
            "llm_client_status": "active",
            "cost_optimizer_status": "active",
            "budget_config": {
                "daily_limit": self._budget_config.daily_limit,
                "cost_tier": self._budget_config.cost_tier.value
            },
            "safety_thresholds": self._safety_thresholds.copy(),
            "performance_metrics": self._performance_metrics.copy(),
            "provider": self._llm_config.provider.value,
            "model": self._llm_config.model
        }
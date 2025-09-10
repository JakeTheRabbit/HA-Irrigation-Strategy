"""AI Safety Patterns and Constraints for Crop Steering System.

Establishes comprehensive safety constraints, validation patterns, and fail-safe
mechanisms for AI decision systems in agricultural automation.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, IntEnum
from typing import (
    Any, 
    Dict, 
    List, 
    Optional, 
    Tuple, 
    Callable,
    Union,
    Protocol,
    runtime_checkable
)

from ..types.ml_pipeline import IrrigationPrediction, PhaseTransitionPrediction, ModelPrediction
from ..types.learning_system import LearningOutcome, Pattern, AdaptationAction

_LOGGER = logging.getLogger(__name__)

class SafetyLevel(IntEnum):
    """Safety constraint levels."""
    ADVISORY = 1      # Warning only
    PREVENTIVE = 2    # Prevent action, allow override
    PROTECTIVE = 3    # Force safe action
    EMERGENCY = 4     # Emergency shutdown/override
    CRITICAL = 5      # System halt

class ConstraintType(Enum):
    """Types of safety constraints."""
    PHYSICAL_LIMITS = "physical_limits"          # Hardware/physical constraints
    BIOLOGICAL_LIMITS = "biological_limits"     # Plant biology constraints
    TEMPORAL_LIMITS = "temporal_limits"         # Time-based constraints
    RESOURCE_LIMITS = "resource_limits"         # Resource usage constraints
    OPERATIONAL_LIMITS = "operational_limits"   # System operation constraints
    CONFIDENCE_LIMITS = "confidence_limits"     # AI confidence constraints
    LEARNING_LIMITS = "learning_limits"         # Learning system constraints

class ViolationType(Enum):
    """Types of constraint violations."""
    HARD_VIOLATION = "hard_violation"           # Absolute constraint violation
    SOFT_VIOLATION = "soft_violation"           # Threshold exceeded but recoverable
    TREND_VIOLATION = "trend_violation"         # Concerning trend detected
    CUMULATIVE_VIOLATION = "cumulative_violation" # Multiple minor violations
    PREDICTIVE_VIOLATION = "predictive_violation" # Predicted future violation

@dataclass(frozen=True)
class SafetyConstraint:
    """Immutable safety constraint definition."""
    constraint_id: str
    name: str
    description: str
    
    # Constraint definition
    constraint_type: ConstraintType
    safety_level: SafetyLevel
    
    # Constraint bounds
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    target_value: Optional[float] = None
    tolerance: float = 0.0
    
    # Applicability
    applies_to_zones: List[int] = field(default_factory=list)  # Empty = all zones
    applies_to_phases: List[str] = field(default_factory=list)  # Empty = all phases
    applies_to_crops: List[str] = field(default_factory=list)  # Empty = all crops
    
    # Temporal constraints
    time_window: Optional[timedelta] = None     # Time window for constraint
    cooldown_period: Optional[timedelta] = None # Minimum time between violations
    
    # Override permissions
    user_override_allowed: bool = False
    expert_override_required: bool = False
    emergency_override_timeout: Optional[timedelta] = None
    
    # Monitoring
    monitoring_frequency: timedelta = timedelta(minutes=1)
    alert_threshold_ratio: float = 0.9  # Alert when approaching violation
    
    def validate_value(self, value: float, context: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Validate a value against this constraint."""
        # Check applicability
        zone_id = context.get('zone_id', 1)
        if self.applies_to_zones and zone_id not in self.applies_to_zones:
            return True, None  # Constraint doesn't apply
        
        phase = context.get('phase', '')
        if self.applies_to_phases and phase not in self.applies_to_phases:
            return True, None  # Constraint doesn't apply
        
        crop_type = context.get('crop_type', '')
        if self.applies_to_crops and crop_type not in self.applies_to_crops:
            return True, None  # Constraint doesn't apply
        
        # Validate bounds
        if self.min_value is not None and value < self.min_value - self.tolerance:
            return False, f"Value {value} below minimum {self.min_value} (tolerance: {self.tolerance})"
        
        if self.max_value is not None and value > self.max_value + self.tolerance:
            return False, f"Value {value} above maximum {self.max_value} (tolerance: {self.tolerance})"
        
        return True, None

@dataclass
class ConstraintViolation:
    """Record of a safety constraint violation."""
    violation_id: str = field(default_factory=lambda: f"violation_{datetime.now().isoformat()}")
    timestamp: datetime = field(default_factory=datetime.now)
    
    # Violation details
    constraint: SafetyConstraint = field(default_factory=lambda: SafetyConstraint("", "", "", ConstraintType.PHYSICAL_LIMITS, SafetyLevel.ADVISORY))
    violation_type: ViolationType = ViolationType.HARD_VIOLATION
    
    # Context
    zone_id: int = 1
    phase: str = ""
    violating_value: Optional[float] = None
    expected_value: Optional[float] = None
    
    # Decision context (if violation from AI decision)
    decision_id: Optional[str] = None
    model_confidence: Optional[float] = None
    model_reasoning: str = ""
    
    # Severity assessment
    severity_score: float = 1.0  # 0-10 scale
    potential_harm: str = "unknown"
    
    # Response actions
    immediate_actions_taken: List[str] = field(default_factory=list)
    override_applied: bool = False
    override_authority: Optional[str] = None
    
    # Resolution
    resolved: bool = False
    resolution_time: Optional[datetime] = None
    resolution_method: str = ""

class SafetyAction(Enum):
    """Safety actions that can be taken."""
    BLOCK_DECISION = "block_decision"
    FORCE_SAFE_VALUE = "force_safe_value" 
    TRIGGER_EMERGENCY_STOP = "trigger_emergency_stop"
    ALERT_OPERATOR = "alert_operator"
    REDUCE_AUTONOMY_LEVEL = "reduce_autonomy_level"
    FALLBACK_TO_RULES = "fallback_to_rules"
    REQUEST_CONFIRMATION = "request_confirmation"
    LOG_WARNING = "log_warning"

@runtime_checkable
class SafetyGuard(Protocol):
    """Protocol for safety guard implementations."""
    
    def validate_decision(
        self, 
        decision: Union[IrrigationPrediction, PhaseTransitionPrediction],
        context: Dict[str, Any]
    ) -> Tuple[bool, List[ConstraintViolation]]:
        """Validate a decision against safety constraints."""
        ...
    
    def get_safety_actions(
        self, 
        violations: List[ConstraintViolation]
    ) -> List[Tuple[SafetyAction, Dict[str, Any]]]:
        """Determine safety actions for violations."""
        ...
    
    def apply_safety_override(
        self, 
        original_decision: Any,
        violations: List[ConstraintViolation]
    ) -> Any:
        """Apply safety override to make decision safe."""
        ...

class IrrigationSafetyGuard:
    """Safety guard for irrigation decisions."""
    
    def __init__(self):
        self.constraints = self._initialize_constraints()
        self.violation_history: List[ConstraintViolation] = []
        
    def _initialize_constraints(self) -> List[SafetyConstraint]:
        """Initialize irrigation safety constraints."""
        return [
            # Critical VWC limits
            SafetyConstraint(
                constraint_id="vwc_critical_low",
                name="Critical Low VWC",
                description="VWC must not drop below critical levels",
                constraint_type=ConstraintType.BIOLOGICAL_LIMITS,
                safety_level=SafetyLevel.CRITICAL,
                min_value=35.0,
                tolerance=2.0,
                user_override_allowed=False,
                emergency_override_timeout=timedelta(minutes=30)
            ),
            SafetyConstraint(
                constraint_id="vwc_critical_high",
                name="Critical High VWC",
                description="VWC must not exceed saturation levels",
                constraint_type=ConstraintType.BIOLOGICAL_LIMITS,
                safety_level=SafetyLevel.CRITICAL,
                max_value=85.0,
                tolerance=3.0,
                user_override_allowed=False
            ),
            
            # EC safety limits
            SafetyConstraint(
                constraint_id="ec_toxicity_limit",
                name="EC Toxicity Limit",
                description="EC must not reach toxic levels",
                constraint_type=ConstraintType.BIOLOGICAL_LIMITS,
                safety_level=SafetyLevel.PROTECTIVE,
                max_value=6.0,
                tolerance=0.2,
                user_override_allowed=True,
                expert_override_required=True
            ),
            
            # Irrigation volume limits
            SafetyConstraint(
                constraint_id="max_shot_volume",
                name="Maximum Shot Volume",
                description="Single irrigation shot cannot exceed safe volume",
                constraint_type=ConstraintType.PHYSICAL_LIMITS,
                safety_level=SafetyLevel.PREVENTIVE,
                max_value=500.0,  # mL
                tolerance=50.0,
                user_override_allowed=True
            ),
            SafetyConstraint(
                constraint_id="min_shot_volume",
                name="Minimum Effective Shot Volume",
                description="Irrigation shots must be large enough to be effective",
                constraint_type=ConstraintType.OPERATIONAL_LIMITS,
                safety_level=SafetyLevel.ADVISORY,
                min_value=10.0,  # mL
                tolerance=2.0,
                user_override_allowed=True
            ),
            
            # Frequency limits
            SafetyConstraint(
                constraint_id="irrigation_frequency_limit",
                name="Irrigation Frequency Limit",
                description="Minimum time between irrigations",
                constraint_type=ConstraintType.TEMPORAL_LIMITS,
                safety_level=SafetyLevel.PREVENTIVE,
                min_value=300.0,  # 5 minutes in seconds
                tolerance=60.0,   # 1 minute tolerance
                time_window=timedelta(minutes=10),
                user_override_allowed=True
            ),
            
            # Daily volume limits
            SafetyConstraint(
                constraint_id="daily_water_limit",
                name="Daily Water Limit",
                description="Maximum water usage per day per zone",
                constraint_type=ConstraintType.RESOURCE_LIMITS,
                safety_level=SafetyLevel.PROTECTIVE,
                max_value=5000.0,  # 5L per day
                tolerance=500.0,
                time_window=timedelta(days=1),
                user_override_allowed=True,
                expert_override_required=True
            ),
            
            # Confidence limits
            SafetyConstraint(
                constraint_id="min_ai_confidence",
                name="Minimum AI Confidence",
                description="AI decisions must meet minimum confidence threshold",
                constraint_type=ConstraintType.CONFIDENCE_LIMITS,
                safety_level=SafetyLevel.PREVENTIVE,
                min_value=0.6,  # 60% confidence
                tolerance=0.1,
                user_override_allowed=True
            ),
            
            # Emergency response constraints
            SafetyConstraint(
                constraint_id="emergency_response_time",
                name="Emergency Response Time",
                description="Emergency situations must be addressed quickly",
                constraint_type=ConstraintType.TEMPORAL_LIMITS,
                safety_level=SafetyLevel.EMERGENCY,
                max_value=300.0,  # 5 minutes
                tolerance=60.0,
                applies_to_phases=["Emergency"]
            )
        ]
    
    def validate_decision(
        self, 
        decision: IrrigationPrediction,
        context: Dict[str, Any]
    ) -> Tuple[bool, List[ConstraintViolation]]:
        """Validate irrigation decision against safety constraints."""
        violations = []
        
        # Context setup
        zone_id = context.get('zone_id', 1)
        phase = context.get('phase', 'P2')
        sensor_data = context.get('sensor_data', {})
        
        # Check VWC constraints
        avg_vwc = context.get('vwc_average', 0.0)
        if avg_vwc > 0:
            vwc_violations = self._check_vwc_constraints(avg_vwc, decision, zone_id, phase)
            violations.extend(vwc_violations)
        
        # Check EC constraints
        avg_ec = context.get('ec_average', 0.0)
        if avg_ec > 0:
            ec_violations = self._check_ec_constraints(avg_ec, decision, zone_id, phase)
            violations.extend(ec_violations)
        
        # Check irrigation volume constraints
        if decision.should_irrigate and decision.shot_size_ml:
            volume_violations = self._check_volume_constraints(decision.shot_size_ml, zone_id, phase)
            violations.extend(volume_violations)
        
        # Check frequency constraints
        last_irrigation = context.get('last_irrigation_time')
        if last_irrigation and decision.should_irrigate:
            freq_violations = self._check_frequency_constraints(last_irrigation, zone_id, phase)
            violations.extend(freq_violations)
        
        # Check confidence constraints
        confidence_violations = self._check_confidence_constraints(decision.confidence, zone_id, phase)
        violations.extend(confidence_violations)
        
        # Check daily limits
        daily_usage = context.get('daily_water_usage_ml', 0.0)
        if decision.should_irrigate and decision.shot_size_ml:
            projected_usage = daily_usage + decision.shot_size_ml
            daily_violations = self._check_daily_limits(projected_usage, zone_id, phase)
            violations.extend(daily_violations)
        
        # Record violations
        for violation in violations:
            violation.decision_id = context.get('decision_id', '')
            violation.model_confidence = decision.confidence
            violation.model_reasoning = decision.reasoning
            self.violation_history.append(violation)
        
        return len(violations) == 0, violations
    
    def _check_vwc_constraints(
        self, 
        vwc: float, 
        decision: IrrigationPrediction, 
        zone_id: int, 
        phase: str
    ) -> List[ConstraintViolation]:
        """Check VWC-related constraints."""
        violations = []
        context = {'zone_id': zone_id, 'phase': phase}
        
        # Critical low VWC
        low_constraint = self._get_constraint("vwc_critical_low")
        if low_constraint:
            is_valid, error = low_constraint.validate_value(vwc, context)
            if not is_valid and not decision.should_irrigate:
                violations.append(ConstraintViolation(
                    constraint=low_constraint,
                    violation_type=ViolationType.HARD_VIOLATION,
                    zone_id=zone_id,
                    phase=phase,
                    violating_value=vwc,
                    expected_value=low_constraint.min_value,
                    severity_score=9.0,  # Critical
                    potential_harm="Plant death from dehydration",
                    immediate_actions_taken=["Force irrigation"]
                ))
        
        # Critical high VWC
        high_constraint = self._get_constraint("vwc_critical_high")
        if high_constraint:
            is_valid, error = high_constraint.validate_value(vwc, context)
            if not is_valid and decision.should_irrigate:
                violations.append(ConstraintViolation(
                    constraint=high_constraint,
                    violation_type=ViolationType.HARD_VIOLATION,
                    zone_id=zone_id,
                    phase=phase,
                    violating_value=vwc,
                    expected_value=high_constraint.max_value,
                    severity_score=8.0,  # High
                    potential_harm="Root rot and plant death from over-watering",
                    immediate_actions_taken=["Block irrigation"]
                ))
        
        return violations
    
    def _check_ec_constraints(
        self, 
        ec: float, 
        decision: IrrigationPrediction, 
        zone_id: int, 
        phase: str
    ) -> List[ConstraintViolation]:
        """Check EC-related constraints."""
        violations = []
        context = {'zone_id': zone_id, 'phase': phase}
        
        ec_constraint = self._get_constraint("ec_toxicity_limit")
        if ec_constraint:
            is_valid, error = ec_constraint.validate_value(ec, context)
            if not is_valid:
                # High EC should trigger dilution irrigation
                if not decision.should_irrigate or (decision.shot_size_ml and decision.shot_size_ml < 25):
                    violations.append(ConstraintViolation(
                        constraint=ec_constraint,
                        violation_type=ViolationType.HARD_VIOLATION,
                        zone_id=zone_id,
                        phase=phase,
                        violating_value=ec,
                        expected_value=ec_constraint.max_value,
                        severity_score=7.0,
                        potential_harm="Nutrient toxicity and plant stress",
                        immediate_actions_taken=["Force dilution irrigation"]
                    ))
        
        return violations
    
    def _check_volume_constraints(
        self, 
        shot_size: int, 
        zone_id: int, 
        phase: str
    ) -> List[ConstraintViolation]:
        """Check irrigation volume constraints."""
        violations = []
        context = {'zone_id': zone_id, 'phase': phase}
        
        # Check maximum volume
        max_constraint = self._get_constraint("max_shot_volume")
        if max_constraint:
            is_valid, error = max_constraint.validate_value(float(shot_size), context)
            if not is_valid:
                violations.append(ConstraintViolation(
                    constraint=max_constraint,
                    violation_type=ViolationType.HARD_VIOLATION,
                    zone_id=zone_id,
                    phase=phase,
                    violating_value=float(shot_size),
                    expected_value=max_constraint.max_value,
                    severity_score=6.0,
                    potential_harm="Over-watering and potential root damage",
                    immediate_actions_taken=["Reduce shot size"]
                ))
        
        # Check minimum volume
        min_constraint = self._get_constraint("min_shot_volume")
        if min_constraint:
            is_valid, error = min_constraint.validate_value(float(shot_size), context)
            if not is_valid:
                violations.append(ConstraintViolation(
                    constraint=min_constraint,
                    violation_type=ViolationType.SOFT_VIOLATION,
                    zone_id=zone_id,
                    phase=phase,
                    violating_value=float(shot_size),
                    expected_value=min_constraint.min_value,
                    severity_score=3.0,
                    potential_harm="Ineffective irrigation",
                    immediate_actions_taken=["Increase shot size or skip irrigation"]
                ))
        
        return violations
    
    def _check_frequency_constraints(
        self, 
        last_irrigation: datetime, 
        zone_id: int, 
        phase: str
    ) -> List[ConstraintViolation]:
        """Check irrigation frequency constraints."""
        violations = []
        context = {'zone_id': zone_id, 'phase': phase}
        
        freq_constraint = self._get_constraint("irrigation_frequency_limit")
        if freq_constraint:
            time_since = (datetime.now() - last_irrigation).total_seconds()
            is_valid, error = freq_constraint.validate_value(time_since, context)
            if not is_valid:
                violations.append(ConstraintViolation(
                    constraint=freq_constraint,
                    violation_type=ViolationType.HARD_VIOLATION,
                    zone_id=zone_id,
                    phase=phase,
                    violating_value=time_since,
                    expected_value=freq_constraint.min_value,
                    severity_score=5.0,
                    potential_harm="Too frequent irrigation may cause root stress",
                    immediate_actions_taken=["Delay irrigation"]
                ))
        
        return violations
    
    def _check_confidence_constraints(
        self, 
        confidence: float, 
        zone_id: int, 
        phase: str
    ) -> List[ConstraintViolation]:
        """Check AI confidence constraints."""
        violations = []
        context = {'zone_id': zone_id, 'phase': phase}
        
        conf_constraint = self._get_constraint("min_ai_confidence")
        if conf_constraint:
            is_valid, error = conf_constraint.validate_value(confidence, context)
            if not is_valid:
                violations.append(ConstraintViolation(
                    constraint=conf_constraint,
                    violation_type=ViolationType.SOFT_VIOLATION,
                    zone_id=zone_id,
                    phase=phase,
                    violating_value=confidence,
                    expected_value=conf_constraint.min_value,
                    severity_score=4.0,
                    potential_harm="Unreliable AI decision",
                    immediate_actions_taken=["Fallback to rule-based decision"]
                ))
        
        return violations
    
    def _check_daily_limits(
        self, 
        projected_usage: float, 
        zone_id: int, 
        phase: str
    ) -> List[ConstraintViolation]:
        """Check daily resource usage limits."""
        violations = []
        context = {'zone_id': zone_id, 'phase': phase}
        
        daily_constraint = self._get_constraint("daily_water_limit")
        if daily_constraint:
            is_valid, error = daily_constraint.validate_value(projected_usage, context)
            if not is_valid:
                violations.append(ConstraintViolation(
                    constraint=daily_constraint,
                    violation_type=ViolationType.HARD_VIOLATION,
                    zone_id=zone_id,
                    phase=phase,
                    violating_value=projected_usage,
                    expected_value=daily_constraint.max_value,
                    severity_score=6.0,
                    potential_harm="Excessive water usage",
                    immediate_actions_taken=["Block irrigation", "Alert operator"]
                ))
        
        return violations
    
    def _get_constraint(self, constraint_id: str) -> Optional[SafetyConstraint]:
        """Get constraint by ID."""
        for constraint in self.constraints:
            if constraint.constraint_id == constraint_id:
                return constraint
        return None
    
    def get_safety_actions(
        self, 
        violations: List[ConstraintViolation]
    ) -> List[Tuple[SafetyAction, Dict[str, Any]]]:
        """Determine safety actions for violations."""
        actions = []
        
        for violation in violations:
            if violation.constraint.safety_level == SafetyLevel.CRITICAL:
                if "vwc_critical_low" in violation.constraint.constraint_id:
                    actions.append((SafetyAction.FORCE_SAFE_VALUE, {
                        "parameter": "should_irrigate",
                        "value": True,
                        "reason": "Critical low VWC requires immediate irrigation"
                    }))
                elif "vwc_critical_high" in violation.constraint.constraint_id:
                    actions.append((SafetyAction.BLOCK_DECISION, {
                        "reason": "Critical high VWC prohibits irrigation"
                    }))
                    
            elif violation.constraint.safety_level == SafetyLevel.EMERGENCY:
                actions.append((SafetyAction.TRIGGER_EMERGENCY_STOP, {
                    "reason": f"Emergency constraint violated: {violation.constraint.name}"
                }))
                
            elif violation.constraint.safety_level == SafetyLevel.PROTECTIVE:
                if "max_shot_volume" in violation.constraint.constraint_id:
                    actions.append((SafetyAction.FORCE_SAFE_VALUE, {
                        "parameter": "shot_size_ml",
                        "value": int(violation.constraint.max_value),
                        "reason": "Shot size exceeds safe limit"
                    }))
                elif "daily_water_limit" in violation.constraint.constraint_id:
                    actions.append((SafetyAction.BLOCK_DECISION, {
                        "reason": "Daily water limit exceeded"
                    }))
                    actions.append((SafetyAction.ALERT_OPERATOR, {
                        "message": f"Zone {violation.zone_id} exceeded daily water limit"
                    }))
                    
            elif violation.constraint.safety_level == SafetyLevel.PREVENTIVE:
                if "min_ai_confidence" in violation.constraint.constraint_id:
                    actions.append((SafetyAction.FALLBACK_TO_RULES, {
                        "reason": "AI confidence below threshold"
                    }))
                elif "irrigation_frequency_limit" in violation.constraint.constraint_id:
                    actions.append((SafetyAction.BLOCK_DECISION, {
                        "reason": "Too frequent irrigation attempt",
                        "retry_after_seconds": int(violation.constraint.min_value - violation.violating_value)
                    }))
                    
            elif violation.constraint.safety_level == SafetyLevel.ADVISORY:
                actions.append((SafetyAction.LOG_WARNING, {
                    "message": f"Advisory violation: {violation.constraint.name}",
                    "suggestion": "Consider manual review"
                }))
        
        return actions
    
    def apply_safety_override(
        self, 
        original_decision: IrrigationPrediction,
        violations: List[ConstraintViolation]
    ) -> IrrigationPrediction:
        """Apply safety override to make decision safe."""
        safe_decision = IrrigationPrediction(
            should_irrigate=original_decision.should_irrigate,
            shot_size_ml=original_decision.shot_size_ml,
            confidence=original_decision.confidence,
            urgency_score=original_decision.urgency_score,
            reasoning=original_decision.reasoning + " [SAFETY OVERRIDE APPLIED]"
        )
        
        # Apply safety actions
        actions = self.get_safety_actions(violations)
        
        for action, params in actions:
            if action == SafetyAction.BLOCK_DECISION:
                safe_decision.should_irrigate = False
                safe_decision.shot_size_ml = None
                safe_decision.reasoning += f" - BLOCKED: {params.get('reason', 'Safety constraint')}"
                
            elif action == SafetyAction.FORCE_SAFE_VALUE:
                param = params.get('parameter')
                value = params.get('value')
                if param == "should_irrigate":
                    safe_decision.should_irrigate = value
                elif param == "shot_size_ml":
                    safe_decision.shot_size_ml = value
                safe_decision.reasoning += f" - FORCED {param}={value}: {params.get('reason', 'Safety')}"
                
            elif action == SafetyAction.FALLBACK_TO_RULES:
                safe_decision.confidence = 0.5  # Lower confidence for rule-based
                safe_decision.reasoning += f" - RULE FALLBACK: {params.get('reason', 'Safety fallback')}"
        
        # Adjust urgency if safety overrides applied
        if len(actions) > 0:
            critical_actions = [a for a, p in actions if a in [SafetyAction.TRIGGER_EMERGENCY_STOP, SafetyAction.FORCE_SAFE_VALUE]]
            if critical_actions:
                safe_decision.urgency_score = min(1.0, safe_decision.urgency_score + 0.3)
        
        return safe_decision

class LearningSafetyGuard:
    """Safety guard for learning system adaptations."""
    
    def __init__(self):
        self.learning_constraints = self._initialize_learning_constraints()
    
    def _initialize_learning_constraints(self) -> List[SafetyConstraint]:
        """Initialize learning system safety constraints."""
        return [
            SafetyConstraint(
                constraint_id="max_parameter_change",
                name="Maximum Parameter Change",
                description="Limit how much parameters can change in single adaptation",
                constraint_type=ConstraintType.LEARNING_LIMITS,
                safety_level=SafetyLevel.PROTECTIVE,
                max_value=0.2,  # 20% maximum change
                tolerance=0.05,
                user_override_allowed=True,
                expert_override_required=True
            ),
            
            SafetyConstraint(
                constraint_id="min_learning_confidence",
                name="Minimum Learning Confidence",
                description="Learning outcomes must meet confidence threshold",
                constraint_type=ConstraintType.CONFIDENCE_LIMITS,
                safety_level=SafetyLevel.PREVENTIVE,
                min_value=0.75,
                tolerance=0.05,
                user_override_allowed=True
            ),
            
            SafetyConstraint(
                constraint_id="max_adaptations_per_day",
                name="Maximum Daily Adaptations",
                description="Limit number of system adaptations per day",
                constraint_type=ConstraintType.TEMPORAL_LIMITS,
                safety_level=SafetyLevel.PROTECTIVE,
                max_value=5.0,
                time_window=timedelta(days=1),
                user_override_allowed=True
            )
        ]
    
    def validate_learning_outcome(
        self, 
        outcome: LearningOutcome,
        context: Dict[str, Any]
    ) -> Tuple[bool, List[ConstraintViolation]]:
        """Validate learning outcome against safety constraints."""
        violations = []
        
        # Check parameter change limits
        for param, (old_val, new_val) in outcome.parameters_optimized.items():
            if old_val != 0:  # Avoid division by zero
                change_ratio = abs(new_val - old_val) / abs(old_val)
                if change_ratio > 0.2:  # 20% change limit
                    violations.append(ConstraintViolation(
                        constraint=self._get_learning_constraint("max_parameter_change"),
                        violation_type=ViolationType.HARD_VIOLATION,
                        violating_value=change_ratio,
                        expected_value=0.2,
                        severity_score=6.0,
                        potential_harm="Excessive parameter change may destabilize system"
                    ))
        
        # Check confidence limits
        if outcome.confidence_score < 0.75:
            violations.append(ConstraintViolation(
                constraint=self._get_learning_constraint("min_learning_confidence"),
                violation_type=ViolationType.SOFT_VIOLATION,
                violating_value=outcome.confidence_score,
                expected_value=0.75,
                severity_score=4.0,
                potential_harm="Low confidence learning may introduce errors"
            ))
        
        return len(violations) == 0, violations
    
    def _get_learning_constraint(self, constraint_id: str) -> Optional[SafetyConstraint]:
        """Get learning constraint by ID."""
        for constraint in self.learning_constraints:
            if constraint.constraint_id == constraint_id:
                return constraint
        return None

# Safety pattern definitions
AGRICULTURAL_SAFETY_PATTERNS = {
    "irrigation_decision_patterns": [
        {
            "pattern": "critical_vwc_response",
            "description": "Always respond to critical VWC levels",
            "conditions": {"vwc_average": {"<": 35.0}},
            "required_action": "immediate_irrigation",
            "safety_level": "critical"
        },
        {
            "pattern": "saturation_prevention",
            "description": "Prevent over-watering at high VWC",
            "conditions": {"vwc_average": {">": 80.0}},
            "prohibited_action": "irrigation",
            "safety_level": "critical"
        }
    ],
    
    "ai_confidence_patterns": [
        {
            "pattern": "low_confidence_fallback",
            "description": "Fallback to rules when AI confidence is low",
            "conditions": {"ai_confidence": {"<": 0.6}},
            "required_action": "rule_based_fallback",
            "safety_level": "preventive"
        }
    ],
    
    "temporal_safety_patterns": [
        {
            "pattern": "irrigation_frequency_limit",
            "description": "Enforce minimum time between irrigations",
            "conditions": {"time_since_last_irrigation": {"<": 300}},  # 5 minutes
            "prohibited_action": "irrigation",
            "safety_level": "preventive"
        }
    ]
}

def create_comprehensive_safety_framework() -> Dict[str, Any]:
    """Create comprehensive safety framework configuration."""
    return {
        "irrigation_safety": {
            "guard": IrrigationSafetyGuard(),
            "enabled": True,
            "enforcement_level": "strict"
        },
        "learning_safety": {
            "guard": LearningSafetyGuard(),
            "enabled": True,
            "enforcement_level": "moderate"
        },
        "safety_patterns": AGRICULTURAL_SAFETY_PATTERNS,
        "monitoring": {
            "enabled": True,
            "alert_channels": ["log", "notification", "email"],
            "violation_retention_days": 30
        },
        "emergency_procedures": {
            "auto_shutdown_on_critical": True,
            "operator_notification_required": True,
            "expert_override_timeout_hours": 2
        }
    }
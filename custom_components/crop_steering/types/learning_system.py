"""Type-safe interfaces for the learning system.

Defines comprehensive types for learning outcomes, pattern recognition,
and adaptive system behavior in the crop steering system.
"""
from __future__ import annotations

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
    Union, 
    Callable,
    TypeVar,
    Generic,
    Protocol,
    runtime_checkable
)

from .ml_pipeline import FeatureVector, ModelPrediction, ModelEvaluationMetrics

# Type variables
PatternT = TypeVar('PatternT')
OutcomeT = TypeVar('OutcomeT')

class LearningStrategy(Enum):
    """Learning strategies for system adaptation."""
    ONLINE_LEARNING = "online_learning"
    BATCH_LEARNING = "batch_learning" 
    REINFORCEMENT_LEARNING = "reinforcement_learning"
    TRANSFER_LEARNING = "transfer_learning"
    FEDERATED_LEARNING = "federated_learning"
    ENSEMBLE_LEARNING = "ensemble_learning"

class PatternType(Enum):
    """Types of patterns the system can learn."""
    TEMPORAL = "temporal"           # Time-based patterns
    SPATIAL = "spatial"            # Zone-based patterns  
    CAUSAL = "causal"              # Cause-effect relationships
    SEASONAL = "seasonal"          # Seasonal/cyclic patterns
    ANOMALY = "anomaly"            # Anomaly patterns
    OPTIMIZATION = "optimization"   # Performance optimization patterns
    CORRELATION = "correlation"     # Feature correlation patterns

class ConfidenceLevel(IntEnum):
    """Confidence levels for learned patterns."""
    VERY_LOW = 1
    LOW = 2
    MEDIUM = 3
    HIGH = 4
    VERY_HIGH = 5

class LearningOutcomeType(Enum):
    """Types of learning outcomes."""
    PATTERN_DISCOVERED = "pattern_discovered"
    PARAMETER_OPTIMIZED = "parameter_optimized"
    MODEL_IMPROVED = "model_improved"
    ANOMALY_DETECTED = "anomaly_detected"
    CORRELATION_FOUND = "correlation_found"
    RULE_REFINED = "rule_refined"
    PREDICTION_CORRECTED = "prediction_corrected"

class AdaptationAction(Enum):
    """Actions the system can take based on learning."""
    UPDATE_THRESHOLDS = "update_thresholds"
    RETRAIN_MODEL = "retrain_model"
    ADJUST_SCHEDULE = "adjust_schedule"
    MODIFY_RULES = "modify_rules"
    ADD_FEATURE = "add_feature"
    REMOVE_FEATURE = "remove_feature"
    CHANGE_STRATEGY = "change_strategy"
    ALERT_OPERATOR = "alert_operator"

@dataclass
class LearningContext:
    """Context information for learning processes."""
    timestamp: datetime = field(default_factory=datetime.now)
    zone_id: int = 0
    crop_type: str = "Cannabis_Athena"
    growth_stage: str = "vegetative"
    
    # Environmental context
    season: str = "spring"
    light_schedule: str = "18/6"
    temperature_avg: Optional[float] = None
    humidity_avg: Optional[float] = None
    
    # System context
    system_version: str = "2.3.1"
    configuration_hash: str = ""
    data_quality_score: float = 1.0
    
    # Learning session metadata
    learning_session_id: str = ""
    parent_context_id: Optional[str] = None

@dataclass 
class Pattern(Generic[PatternT]):
    """Generic pattern representation."""
    pattern_id: str
    pattern_type: PatternType
    pattern_data: PatternT
    
    # Pattern metadata
    name: str = ""
    description: str = ""
    discovered_at: datetime = field(default_factory=datetime.now)
    last_validated: Optional[datetime] = None
    
    # Confidence and validation
    confidence_level: ConfidenceLevel = ConfidenceLevel.MEDIUM
    statistical_significance: Optional[float] = None
    validation_count: int = 0
    failure_count: int = 0
    
    # Applicability
    applicable_zones: List[int] = field(default_factory=list)
    applicable_crops: List[str] = field(default_factory=list)
    applicable_conditions: Dict[str, Any] = field(default_factory=dict)
    
    # Usage tracking
    usage_count: int = 0
    last_used: Optional[datetime] = None
    success_rate: float = 0.0
    
    # Pattern evolution
    version: int = 1
    parent_pattern_id: Optional[str] = None
    derived_patterns: List[str] = field(default_factory=list)

@dataclass
class TemporalPattern:
    """Pattern in temporal data."""
    sequence_length: int
    frequency: timedelta
    amplitude: float
    phase_offset: timedelta = timedelta(0)
    
    # Pattern characteristics
    is_cyclic: bool = False
    trend_direction: str = "stable"  # increasing, decreasing, stable
    volatility: float = 0.0
    
    # Predictive information
    next_occurrence: Optional[datetime] = None
    confidence_interval: Tuple[float, float] = (0.0, 1.0)

@dataclass
class CausalPattern:
    """Cause-effect relationship pattern."""
    cause_features: List[str]
    effect_features: List[str]
    
    # Relationship strength
    correlation_strength: float = 0.0
    causation_confidence: float = 0.0
    time_lag: timedelta = timedelta(0)
    
    # Conditions
    required_conditions: Dict[str, Any] = field(default_factory=dict)
    blocking_conditions: Dict[str, Any] = field(default_factory=dict)
    
    # Effect prediction
    effect_magnitude: Dict[str, float] = field(default_factory=dict)
    effect_duration: timedelta = timedelta(hours=1)

@dataclass
class OptimizationPattern:
    """Performance optimization pattern."""
    optimization_target: str  # irrigation_efficiency, plant_health, etc.
    parameter_adjustments: Dict[str, float]
    
    # Performance impact
    baseline_performance: float = 0.0
    improved_performance: float = 0.0
    improvement_ratio: float = 1.0
    
    # Constraints
    resource_cost: float = 0.0
    risk_level: str = "low"  # low, medium, high
    reversibility: bool = True
    
    # Validation
    tested_scenarios: int = 0
    success_scenarios: int = 0

@dataclass
class LearningOutcome:
    """Result of a learning process."""
    outcome_id: str = field(default_factory=lambda: f"outcome_{datetime.now().isoformat()}")
    outcome_type: LearningOutcomeType = LearningOutcomeType.PATTERN_DISCOVERED
    timestamp: datetime = field(default_factory=datetime.now)
    
    # Learning details
    learning_strategy: LearningStrategy = LearningStrategy.ONLINE_LEARNING
    input_data_size: int = 0
    processing_time: timedelta = timedelta(0)
    
    # Outcome data
    patterns_discovered: List[Pattern] = field(default_factory=list)
    parameters_optimized: Dict[str, Tuple[float, float]] = field(default_factory=dict)  # param: (old, new)
    model_improvements: Dict[str, ModelEvaluationMetrics] = field(default_factory=dict)
    
    # Impact assessment
    expected_benefit: float = 0.0
    confidence_score: float = 0.0
    risk_assessment: str = "low"
    
    # Implementation
    adaptation_actions: List[AdaptationAction] = field(default_factory=list)
    auto_applied: bool = False
    requires_approval: bool = False
    
    # Validation
    validation_method: str = ""
    validation_results: Dict[str, Any] = field(default_factory=dict)
    
    # Context
    learning_context: Optional[LearningContext] = None

@dataclass
class FeedbackEvent:
    """User or system feedback on decisions/outcomes."""
    event_id: str = field(default_factory=lambda: f"feedback_{datetime.now().isoformat()}")
    timestamp: datetime = field(default_factory=datetime.now)
    
    # Feedback target
    target_decision_id: Optional[str] = None
    target_prediction_id: Optional[str] = None
    target_pattern_id: Optional[str] = None
    
    # Feedback content
    feedback_type: str = "quality"  # quality, accuracy, efficiency, safety
    feedback_score: float = 0.0  # -1 to 1, or 0-100 scale
    feedback_text: str = ""
    
    # Feedback source
    source_type: str = "user"  # user, system, automated, expert
    source_confidence: float = 1.0
    
    # Context
    zone_id: int = 0
    phase: str = ""
    environmental_conditions: Dict[str, Any] = field(default_factory=dict)
    
    # Processing status
    processed: bool = False
    incorporated: bool = False
    learning_impact: Optional[str] = None

@runtime_checkable
class PatternMatcher(Protocol, Generic[PatternT]):
    """Protocol for pattern matching implementations."""
    
    def find_patterns(
        self, 
        data: List[Dict[str, Any]], 
        pattern_types: List[PatternType]
    ) -> List[Pattern[PatternT]]:
        """Find patterns in data."""
        ...
    
    def match_pattern(
        self, 
        data: Dict[str, Any], 
        pattern: Pattern[PatternT]
    ) -> Tuple[bool, float]:
        """Check if data matches a pattern."""
        ...
    
    def validate_pattern(
        self, 
        pattern: Pattern[PatternT], 
        validation_data: List[Dict[str, Any]]
    ) -> Tuple[bool, Dict[str, Any]]:
        """Validate pattern against new data."""
        ...

@runtime_checkable  
class LearningEngine(Protocol):
    """Protocol for learning engine implementations."""
    
    def learn_from_outcome(
        self, 
        decision_id: str,
        actual_outcome: Dict[str, Any],
        context: LearningContext
    ) -> LearningOutcome:
        """Learn from decision outcome."""
        ...
    
    def learn_from_feedback(
        self, 
        feedback: FeedbackEvent
    ) -> LearningOutcome:
        """Learn from user/system feedback."""
        ...
    
    def discover_patterns(
        self, 
        data: List[Dict[str, Any]],
        context: LearningContext
    ) -> List[Pattern]:
        """Discover new patterns in data."""
        ...
    
    def optimize_parameters(
        self, 
        target_metric: str,
        current_parameters: Dict[str, float],
        context: LearningContext
    ) -> Dict[str, float]:
        """Optimize system parameters."""
        ...
    
    def get_learning_summary(self, days: int = 7) -> Dict[str, Any]:
        """Get summary of recent learning activities."""
        ...

@dataclass
class AdaptiveThreshold:
    """Threshold that adapts based on learning."""
    name: str
    current_value: float
    default_value: float
    
    # Adaptation bounds
    min_value: float
    max_value: float
    adaptation_rate: float = 0.1  # How quickly to adapt
    
    # Learning tracking
    adjustment_history: List[Tuple[datetime, float, str]] = field(default_factory=list)  # time, value, reason
    performance_correlation: float = 0.0  # Correlation with performance
    
    # Validation
    last_validated: Optional[datetime] = None
    validation_frequency: timedelta = timedelta(days=1)
    
    def adapt(self, feedback_score: float, learning_rate: Optional[float] = None) -> float:
        """Adapt threshold based on feedback."""
        rate = learning_rate or self.adaptation_rate
        
        if feedback_score > 0.5:  # Positive feedback
            adjustment = rate * feedback_score
        else:  # Negative feedback
            adjustment = -rate * (1 - feedback_score)
        
        new_value = max(self.min_value, min(self.max_value, self.current_value + adjustment))
        
        if new_value != self.current_value:
            self.adjustment_history.append((
                datetime.now(), 
                new_value, 
                f"Feedback adaptation: {feedback_score:.2f}"
            ))
            self.current_value = new_value
        
        return self.current_value

@dataclass
class LearningConfiguration:
    """Configuration for the learning system."""
    # Learning strategies
    enabled_strategies: List[LearningStrategy] = field(
        default_factory=lambda: [
            LearningStrategy.ONLINE_LEARNING,
            LearningStrategy.BATCH_LEARNING
        ]
    )
    
    # Pattern discovery
    min_pattern_confidence: float = 0.7
    max_patterns_per_session: int = 10
    pattern_validation_window: timedelta = timedelta(days=7)
    
    # Adaptation settings
    auto_adaptation_enabled: bool = True
    adaptation_approval_threshold: float = 0.9
    max_parameter_change: float = 0.2  # Max 20% change per adaptation
    
    # Learning frequency
    online_learning_interval: timedelta = timedelta(hours=1)
    batch_learning_schedule: str = "daily"  # daily, weekly
    pattern_discovery_schedule: str = "weekly"
    
    # Data requirements
    min_data_points: int = 100
    data_quality_threshold: float = 0.8
    historical_data_window: timedelta = timedelta(days=30)
    
    # Safety settings
    enable_safety_checks: bool = True
    rollback_on_performance_drop: bool = True
    performance_drop_threshold: float = 0.1  # 10% performance drop triggers rollback
    
    # Feedback processing
    feedback_weight_user: float = 1.0
    feedback_weight_system: float = 0.5
    feedback_weight_expert: float = 2.0

@runtime_checkable
class AdaptiveSystem(Protocol):
    """Protocol for adaptive system implementations."""
    
    def adapt_to_learning(self, learning_outcome: LearningOutcome) -> bool:
        """Adapt system based on learning outcome."""
        ...
    
    def get_adaptive_parameters(self) -> Dict[str, AdaptiveThreshold]:
        """Get all adaptive parameters."""
        ...
    
    def rollback_adaptation(self, adaptation_id: str) -> bool:
        """Rollback a specific adaptation."""
        ...
    
    def validate_adaptation(self, days: int = 7) -> Dict[str, Any]:
        """Validate recent adaptations."""
        ...

# Utility functions for learning system
def calculate_pattern_strength(
    pattern: Pattern,
    validation_data: List[Dict[str, Any]]
) -> float:
    """Calculate the strength of a pattern based on validation data."""
    if pattern.validation_count == 0:
        return 0.0
    
    success_rate = pattern.success_rate
    confidence = pattern.confidence_level.value / 5.0  # Normalize to 0-1
    statistical_sig = pattern.statistical_significance or 0.5
    
    # Weighted combination
    strength = (success_rate * 0.4 + confidence * 0.3 + statistical_sig * 0.3)
    return min(1.0, max(0.0, strength))

def merge_learning_outcomes(outcomes: List[LearningOutcome]) -> LearningOutcome:
    """Merge multiple learning outcomes into a single outcome."""
    if not outcomes:
        return LearningOutcome()
    
    merged = LearningOutcome(
        outcome_type=LearningOutcomeType.MODEL_IMPROVED,  # Generic merged type
        timestamp=datetime.now()
    )
    
    # Aggregate patterns
    all_patterns = []
    for outcome in outcomes:
        all_patterns.extend(outcome.patterns_discovered)
    merged.patterns_discovered = all_patterns
    
    # Aggregate parameters
    all_params = {}
    for outcome in outcomes:
        all_params.update(outcome.parameters_optimized)
    merged.parameters_optimized = all_params
    
    # Calculate average confidence
    confidences = [o.confidence_score for o in outcomes if o.confidence_score > 0]
    merged.confidence_score = sum(confidences) / len(confidences) if confidences else 0.0
    
    # Combine adaptation actions
    all_actions = []
    for outcome in outcomes:
        all_actions.extend(outcome.adaptation_actions)
    merged.adaptation_actions = list(set(all_actions))  # Remove duplicates
    
    return merged

def validate_learning_outcome(outcome: LearningOutcome) -> Tuple[bool, List[str]]:
    """Validate a learning outcome for consistency and safety."""
    errors = []
    
    # Check confidence score
    if not 0.0 <= outcome.confidence_score <= 1.0:
        errors.append(f"Invalid confidence score: {outcome.confidence_score}")
    
    # Validate patterns
    for pattern in outcome.patterns_discovered:
        if pattern.confidence_level.value < 1:
            errors.append(f"Pattern {pattern.pattern_id} has invalid confidence level")
    
    # Check parameter changes
    for param, (old_val, new_val) in outcome.parameters_optimized.items():
        if abs(new_val - old_val) / abs(old_val) > 0.5:  # More than 50% change
            errors.append(f"Parameter {param} change too large: {old_val} -> {new_val}")
    
    # Validate adaptation actions
    if AdaptationAction.ALERT_OPERATOR in outcome.adaptation_actions and outcome.auto_applied:
        errors.append("Cannot auto-apply adaptation that requires operator alert")
    
    return len(errors) == 0, errors
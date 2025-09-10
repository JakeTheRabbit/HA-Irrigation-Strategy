"""Data models for persistent memory and learning system.

Defines comprehensive data structures for storing all irrigation decisions,
plant responses, and learning outcomes for continuous system improvement.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from enum import Enum
from uuid import uuid4, UUID

class DecisionType(Enum):
    """Types of decisions made by the system."""
    IRRIGATION = "irrigation"
    PHASE_TRANSITION = "phase_transition" 
    EMERGENCY_RESPONSE = "emergency_response"
    SCHEDULE_ADJUSTMENT = "schedule_adjustment"
    PARAMETER_TUNING = "parameter_tuning"

class DecisionSource(Enum):
    """Source that made the decision."""
    LLM_ENGINE = "llm_engine"
    RULE_BASED = "rule_based"
    HYBRID = "hybrid"
    HUMAN_OVERRIDE = "human_override"
    SAFETY_OVERRIDE = "safety_override"

class OutcomeType(Enum):
    """Types of outcomes to track."""
    EXCELLENT = "excellent"
    GOOD = "good"
    ACCEPTABLE = "acceptable"
    POOR = "poor"
    FAILURE = "failure"

class PatternCategory(Enum):
    """Categories of learned patterns."""
    DRYBACK_BEHAVIOR = "dryback_behavior"
    GROWTH_PHASE = "growth_phase"
    ENVIRONMENTAL_RESPONSE = "environmental_response"
    NUTRIENT_UPTAKE = "nutrient_uptake"
    STRESS_INDICATORS = "stress_indicators"
    OPTIMIZATION_RULE = "optimization_rule"

@dataclass
class SensorReading:
    """Temporal sensor data with metadata."""
    id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    zone_id: int = 0
    
    # Core sensor data
    vwc_front: Optional[float] = None
    vwc_back: Optional[float] = None
    ec_front: Optional[float] = None
    ec_back: Optional[float] = None
    temperature: Optional[float] = None
    light_level: Optional[float] = None
    
    # Calculated metrics
    vwc_average: Optional[float] = None
    ec_average: Optional[float] = None
    ec_ratio: Optional[float] = None
    dryback_rate: Optional[float] = None
    
    # Environmental context
    lights_on: bool = False
    ambient_temperature: Optional[float] = None
    humidity: Optional[float] = None
    vpd: Optional[float] = None  # Vapor Pressure Deficit
    
    # Quality indicators
    data_quality: float = 1.0  # 0-1 quality score
    outlier_flags: List[str] = field(default_factory=list)
    validation_status: str = "valid"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SensorReading:
        """Create from dictionary."""
        if "timestamp" in data and isinstance(data["timestamp"], str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)

@dataclass 
class IrrigationDecision:
    """Complete record of an irrigation decision and its context."""
    id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    zone_id: int = 0
    
    # Decision details
    decision_type: DecisionType = DecisionType.IRRIGATION
    decision_source: DecisionSource = DecisionSource.RULE_BASED
    decision: str = "wait"  # irrigate, wait, emergency, phase_change
    confidence: float = 0.0
    reasoning: str = ""
    
    # Irrigation parameters (if applicable)
    shot_size_ml: Optional[int] = None
    duration_seconds: Optional[int] = None
    pressure_bar: Optional[float] = None
    urgency: str = "medium"
    
    # Context at decision time
    current_phase: str = "P2"
    sensor_snapshot: Optional[SensorReading] = None
    system_config: Dict[str, Any] = field(default_factory=dict)
    environmental_conditions: Dict[str, Any] = field(default_factory=dict)
    
    # Decision metadata
    llm_metadata: Optional[Dict[str, Any]] = None
    processing_time_ms: Optional[float] = None
    model_version: Optional[str] = None
    rule_set_version: Optional[str] = None
    
    # Execution tracking
    executed: bool = False
    execution_time: Optional[datetime] = None
    execution_success: bool = True
    execution_error: Optional[str] = None
    
    # Follow-up scheduling
    next_check_minutes: int = 15
    next_decision_id: Optional[str] = None  # Link to subsequent decision
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        data["decision_type"] = self.decision_type.value
        data["decision_source"] = self.decision_source.value
        if self.execution_time:
            data["execution_time"] = self.execution_time.isoformat()
        if self.sensor_snapshot:
            data["sensor_snapshot"] = self.sensor_snapshot.to_dict()
        return data

@dataclass
class PhaseTransition:
    """Record of phase transition with full context."""
    id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    zone_id: int = 0
    
    # Transition details
    from_phase: str = "P2"
    to_phase: str = "P2" 
    trigger_reason: str = ""
    decision_source: DecisionSource = DecisionSource.RULE_BASED
    confidence: float = 0.0
    
    # Phase duration tracking
    phase_duration_hours: Optional[float] = None
    phase_start_time: Optional[datetime] = None
    
    # Context data
    sensor_data: Optional[SensorReading] = None
    irrigation_history: List[str] = field(default_factory=list)  # Recent decision IDs
    performance_metrics: Dict[str, Any] = field(default_factory=dict)
    
    # Outcome tracking (populated later)
    success: Optional[bool] = None
    outcome_notes: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        data["decision_source"] = self.decision_source.value
        if self.phase_start_time:
            data["phase_start_time"] = self.phase_start_time.isoformat()
        if self.sensor_data:
            data["sensor_data"] = self.sensor_data.to_dict()
        return data

@dataclass
class PlantResponse:
    """Plant response measurements and analysis."""
    id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    zone_id: int = 0
    
    # Response timeframe
    response_start: datetime = field(default_factory=datetime.now)
    response_end: Optional[datetime] = None
    measurement_window_hours: float = 1.0
    
    # Related decision/action
    trigger_decision_id: Optional[str] = None
    trigger_action: str = ""
    
    # Measured responses
    vwc_change: Optional[float] = None  # Change in VWC over window
    ec_change: Optional[float] = None   # Change in EC over window
    uptake_rate: Optional[float] = None  # Water uptake rate mL/hr
    nutrient_uptake_rate: Optional[float] = None  # EC change rate
    
    # Plant stress indicators
    stress_level: float = 0.0  # 0-10 scale
    stress_indicators: List[str] = field(default_factory=list)
    recovery_time_minutes: Optional[float] = None
    
    # Growth indicators (if available)
    growth_rate: Optional[float] = None
    biomass_change: Optional[float] = None
    leaf_temperature: Optional[float] = None
    
    # Quality assessment
    response_quality: OutcomeType = OutcomeType.ACCEPTABLE
    measurement_confidence: float = 1.0
    notes: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        data["response_start"] = self.response_start.isoformat()
        data["response_quality"] = self.response_quality.value
        if self.response_end:
            data["response_end"] = self.response_end.isoformat()
        return data

@dataclass
class LearningOutcome:
    """Complete learning cycle outcome with feedback."""
    id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    zone_id: int = 0
    
    # Learning cycle components
    decision_id: str = ""
    plant_response_id: Optional[str] = None
    outcome_type: OutcomeType = OutcomeType.ACCEPTABLE
    
    # Performance metrics
    target_achieved: bool = False
    performance_score: float = 0.0  # 0-100
    efficiency_score: float = 0.0   # Resource efficiency
    
    # What was learned
    insights: List[str] = field(default_factory=list)
    patterns_discovered: List[str] = field(default_factory=list)
    parameter_adjustments: Dict[str, Any] = field(default_factory=dict)
    
    # Model improvement
    model_accuracy_before: Optional[float] = None
    model_accuracy_after: Optional[float] = None
    confidence_calibration: Dict[str, float] = field(default_factory=dict)
    
    # Failure analysis (if applicable)
    failure_reasons: List[str] = field(default_factory=list)
    corrective_actions: List[str] = field(default_factory=list)
    
    # Feedback incorporation
    user_feedback: Optional[str] = None
    expert_validation: Optional[bool] = None
    automated_validation: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        data["outcome_type"] = self.outcome_type.value
        return data

@dataclass
class AgriculturePattern:
    """Learned agricultural pattern with context."""
    id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    
    # Pattern identification
    pattern_name: str = ""
    pattern_category: PatternCategory = PatternCategory.OPTIMIZATION_RULE
    description: str = ""
    
    # Pattern definition
    conditions: Dict[str, Any] = field(default_factory=dict)
    actions: Dict[str, Any] = field(default_factory=dict)
    expected_outcomes: Dict[str, Any] = field(default_factory=dict)
    
    # Validation and confidence
    confidence_score: float = 0.0
    sample_size: int = 0
    validation_results: List[str] = field(default_factory=list)
    
    # Applicability
    crop_types: List[str] = field(default_factory=list)
    growth_stages: List[str] = field(default_factory=list)
    environmental_constraints: Dict[str, Any] = field(default_factory=dict)
    
    # Performance tracking
    success_rate: float = 0.0
    usage_count: int = 0
    last_used: Optional[datetime] = None
    
    # Pattern evolution
    version: int = 1
    parent_pattern_id: Optional[str] = None
    derived_patterns: List[str] = field(default_factory=list)
    
    # Statistical validation
    statistical_significance: Optional[float] = None
    p_value: Optional[float] = None
    effect_size: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        data["pattern_category"] = self.pattern_category.value
        if self.last_used:
            data["last_used"] = self.last_used.isoformat()
        return data

@dataclass
class MemorySnapshot:
    """Complete system state snapshot for debugging and analysis."""
    id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    
    # System state
    active_zones: List[int] = field(default_factory=list)
    current_phases: Dict[int, str] = field(default_factory=dict)
    system_config: Dict[str, Any] = field(default_factory=dict)
    
    # Performance metrics
    decision_accuracy_7d: float = 0.0
    irrigation_efficiency_7d: float = 0.0
    learning_velocity: float = 0.0
    
    # Model status
    active_models: Dict[str, Any] = field(default_factory=dict)
    model_performance: Dict[str, float] = field(default_factory=dict)
    pattern_library_size: int = 0
    
    # Resource utilization
    storage_usage_mb: float = 0.0
    api_costs_daily: float = 0.0
    processing_time_avg_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data
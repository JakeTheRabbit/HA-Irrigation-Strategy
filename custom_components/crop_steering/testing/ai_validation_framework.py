"""Comprehensive testing and validation framework for AI decision systems.

Provides simulation environments, safety validation, and comprehensive testing
for machine learning models in agricultural automation contexts.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Callable, Union
from enum import Enum
from contextlib import asynccontextmanager

import numpy as np
from numpy.typing import NDArray

from ..types.ml_pipeline import (
    FeatureVector, 
    IrrigationPrediction, 
    PhaseTransitionPrediction,
    AnomalyDetection,
    MLModel,
    ModelPrediction
)
from ..types.learning_system import LearningOutcome, Pattern, FeedbackEvent

_LOGGER = logging.getLogger(__name__)

class TestSeverity(Enum):
    """Test failure severity levels."""
    CRITICAL = "critical"    # System unsafe, must not deploy
    HIGH = "high"           # Major functionality broken
    MEDIUM = "medium"       # Some features impacted
    LOW = "low"            # Minor issues, acceptable
    INFO = "info"          # Informational only

class ValidationResult(Enum):
    """Validation test results."""
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning" 
    SKIP = "skip"
    ERROR = "error"

class SimulationMode(Enum):
    """Simulation execution modes."""
    REAL_TIME = "real_time"         # Simulates actual time passage
    ACCELERATED = "accelerated"     # Fast simulation for testing
    BATCH = "batch"                 # Process all at once
    INTERACTIVE = "interactive"     # Step-by-step debugging

@dataclass
class TestCase:
    """Individual test case definition."""
    test_id: str
    name: str
    description: str
    
    # Test configuration
    severity: TestSeverity = TestSeverity.MEDIUM
    timeout_seconds: float = 30.0
    retry_count: int = 0
    
    # Test data
    input_data: Dict[str, Any] = field(default_factory=dict)
    expected_output: Optional[Dict[str, Any]] = None
    validation_rules: List[Callable[[Any], bool]] = field(default_factory=list)
    
    # Test context
    zone_id: int = 1
    phase: str = "P2"
    environmental_conditions: Dict[str, Any] = field(default_factory=dict)
    
    # Execution tracking
    created_at: datetime = field(default_factory=datetime.now)
    last_run: Optional[datetime] = None
    execution_count: int = 0

@dataclass
class TestResult:
    """Result of a test execution."""
    test_case_id: str
    result: ValidationResult
    severity: TestSeverity
    
    # Execution details
    execution_time: timedelta = timedelta(0)
    timestamp: datetime = field(default_factory=datetime.now)
    
    # Result data
    actual_output: Optional[Any] = None
    error_message: Optional[str] = None
    stack_trace: Optional[str] = None
    
    # Validation details
    assertions_passed: int = 0
    assertions_failed: int = 0
    validation_details: List[str] = field(default_factory=list)
    
    # Performance metrics
    memory_usage_mb: Optional[float] = None
    cpu_usage_percent: Optional[float] = None
    prediction_confidence: Optional[float] = None

@dataclass
class PlantSimulationState:
    """Simulated plant state for testing."""
    # Current conditions
    vwc_front: float = 65.0
    vwc_back: float = 63.0
    ec_front: float = 2.8
    ec_back: float = 2.9
    temperature: float = 24.0
    
    # Plant health indicators
    stress_level: float = 2.0  # 0-10 scale
    growth_rate: float = 1.0   # Relative growth rate
    nutrient_uptake_rate: float = 1.0
    water_uptake_rate: float = 1.0
    
    # Environmental factors
    light_intensity: float = 800.0  # PPFD
    ambient_temperature: float = 24.0
    humidity: float = 60.0
    co2_level: float = 1200.0
    
    # System parameters
    substrate_volume: float = 10.0  # Liters
    dripper_flow_rate: float = 2.0  # L/hr
    last_irrigation: Optional[datetime] = None
    
    # Simulation metadata
    simulation_time: datetime = field(default_factory=datetime.now)
    time_acceleration: float = 1.0

class PlantSimulator:
    """Simulates plant response to irrigation decisions."""
    
    def __init__(self, initial_state: Optional[PlantSimulationState] = None):
        self.state = initial_state or PlantSimulationState()
        self._response_models = self._initialize_response_models()
        self._random_factors = True
        
    def _initialize_response_models(self) -> Dict[str, Callable]:
        """Initialize plant response models."""
        return {
            "vwc_response": self._simulate_vwc_response,
            "ec_response": self._simulate_ec_response, 
            "stress_response": self._simulate_stress_response,
            "growth_response": self._simulate_growth_response
        }
    
    def apply_irrigation(self, volume_ml: int, duration_seconds: int) -> PlantSimulationState:
        """Simulate irrigation impact on plant state."""
        # Calculate VWC increase
        volume_liters = volume_ml / 1000.0
        vwc_increase = (volume_liters / self.state.substrate_volume) * 100
        
        # Apply with some randomness if enabled
        if self._random_factors:
            vwc_increase *= random.uniform(0.85, 1.15)
        
        # Update VWC (with absorption and distribution)
        self.state.vwc_front = min(85.0, self.state.vwc_front + vwc_increase * 0.6)
        self.state.vwc_back = min(85.0, self.state.vwc_back + vwc_increase * 0.4)
        
        # EC dilution effect
        dilution_factor = 1.0 - (volume_liters / (self.state.substrate_volume * 2))
        self.state.ec_front *= max(0.7, dilution_factor)
        self.state.ec_back *= max(0.7, dilution_factor)
        
        # Update stress (irrigation reduces stress if needed)
        if self.state.vwc_front < 55.0 or self.state.vwc_back < 55.0:
            self.state.stress_level = max(0.0, self.state.stress_level - 1.0)
        
        self.state.last_irrigation = datetime.now()
        return self.state
    
    def advance_time(self, time_delta: timedelta) -> PlantSimulationState:
        """Advance simulation time and update plant state."""
        hours_elapsed = time_delta.total_seconds() / 3600.0
        
        # VWC decrease due to plant uptake and evaporation
        uptake_rate = self.state.water_uptake_rate * (1.0 + self.state.stress_level * 0.1)
        vwc_decrease = uptake_rate * hours_elapsed * 2.0  # Base 2% per hour uptake
        
        self.state.vwc_front = max(30.0, self.state.vwc_front - vwc_decrease)
        self.state.vwc_back = max(30.0, self.state.vwc_back - vwc_decrease * 0.8)
        
        # EC concentration increases as water is consumed
        if self.state.vwc_front > 35.0:  # Only if plant is not severely stressed
            ec_increase = self.state.nutrient_uptake_rate * hours_elapsed * 0.2
            self.state.ec_front = min(6.0, self.state.ec_front + ec_increase)
            self.state.ec_back = min(6.0, self.state.ec_back + ec_increase * 0.9)
        
        # Update stress based on conditions
        self._update_stress_level()
        
        # Update growth rate
        self._update_growth_rate()
        
        self.state.simulation_time += time_delta
        return self.state
    
    def _simulate_vwc_response(self, irrigation_volume: float) -> float:
        """Model VWC response to irrigation."""
        return (irrigation_volume / 1000.0) / self.state.substrate_volume * 100
    
    def _simulate_ec_response(self, irrigation_volume: float) -> float:
        """Model EC response to irrigation."""
        dilution = irrigation_volume / (self.state.substrate_volume * 1000)
        return -self.state.ec_front * dilution * 0.5
    
    def _simulate_stress_response(self) -> None:
        """Update plant stress based on current conditions."""
        stress_factors = []
        
        # VWC stress
        avg_vwc = (self.state.vwc_front + self.state.vwc_back) / 2
        if avg_vwc < 45.0:
            stress_factors.append(2.0)  # High stress
        elif avg_vwc < 55.0:
            stress_factors.append(1.0)  # Medium stress
        elif avg_vwc > 75.0:
            stress_factors.append(0.5)  # Over-watering stress
        
        # EC stress
        avg_ec = (self.state.ec_front + self.state.ec_back) / 2
        if avg_ec > 4.0:
            stress_factors.append(1.5)
        elif avg_ec > 5.0:
            stress_factors.append(3.0)
        
        # Temperature stress
        if self.state.temperature > 28.0 or self.state.temperature < 20.0:
            stress_factors.append(1.0)
        
        # Calculate overall stress
        if stress_factors:
            self.state.stress_level = min(10.0, sum(stress_factors))
        else:
            # Gradual recovery if no stress factors
            self.state.stress_level = max(0.0, self.state.stress_level - 0.1)
    
    def _update_stress_level(self) -> None:
        """Update plant stress level based on current conditions."""
        self._simulate_stress_response()
    
    def _update_growth_rate(self) -> None:
        """Update growth rate based on stress and conditions."""
        if self.state.stress_level < 2.0:
            self.state.growth_rate = 1.2  # Optimal conditions
        elif self.state.stress_level < 5.0:
            self.state.growth_rate = 1.0  # Normal conditions
        elif self.state.stress_level < 8.0:
            self.state.growth_rate = 0.7  # Stressed
        else:
            self.state.growth_rate = 0.3  # Severely stressed
    
    def get_sensor_reading(self, add_noise: bool = True) -> Dict[str, float]:
        """Generate sensor reading with optional noise."""
        reading = {
            "vwc_front": self.state.vwc_front,
            "vwc_back": self.state.vwc_back,
            "ec_front": self.state.ec_front,
            "ec_back": self.state.ec_back,
            "temperature": self.state.temperature
        }
        
        if add_noise:
            for key in reading:
                noise_factor = 0.02  # 2% noise
                noise = random.uniform(-noise_factor, noise_factor)
                reading[key] *= (1.0 + noise)
        
        return reading
    
    def inject_anomaly(self, anomaly_type: str, severity: float = 1.0) -> None:
        """Inject simulated anomalies for testing."""
        if anomaly_type == "sensor_failure":
            # Simulate sensor giving constant/wrong readings
            self.state.vwc_front = 0.0 if severity > 0.8 else self.state.vwc_front * (1 - severity)
        
        elif anomaly_type == "pump_failure":
            # Reduce irrigation effectiveness
            self.state.water_uptake_rate *= (1 + severity)
        
        elif anomaly_type == "nutrient_lockout":
            # Simulate nutrient uptake issues
            self.state.nutrient_uptake_rate *= (1 - severity)
            self.state.stress_level += severity * 3.0
        
        elif anomaly_type == "heat_stress":
            # Temperature spike
            self.state.temperature += severity * 10.0
            self.state.stress_level += severity * 2.0

class AIDecisionValidator:
    """Validates AI decision making against safety and performance criteria."""
    
    def __init__(self):
        self.safety_rules = self._initialize_safety_rules()
        self.performance_thresholds = self._initialize_performance_thresholds()
    
    def _initialize_safety_rules(self) -> List[Callable]:
        """Initialize safety validation rules."""
        return [
            self._validate_vwc_limits,
            self._validate_ec_limits,
            self._validate_irrigation_volume,
            self._validate_frequency_limits,
            self._validate_emergency_response
        ]
    
    def _initialize_performance_thresholds(self) -> Dict[str, Tuple[float, float]]:
        """Initialize performance thresholds (min, max)."""
        return {
            "irrigation_efficiency": (0.7, 1.0),
            "water_usage_optimization": (0.8, 1.0),
            "plant_stress_minimization": (0.0, 3.0),
            "prediction_accuracy": (0.75, 1.0),
            "response_time_ms": (0.0, 5000.0)
        }
    
    def validate_decision(
        self, 
        decision: Union[IrrigationPrediction, PhaseTransitionPrediction],
        context: Dict[str, Any],
        plant_state: PlantSimulationState
    ) -> TestResult:
        """Comprehensive decision validation."""
        test_result = TestResult(
            test_case_id=f"decision_validation_{datetime.now().isoformat()}",
            result=ValidationResult.PASS,
            severity=TestSeverity.HIGH
        )
        
        start_time = datetime.now()
        
        try:
            # Safety validation
            safety_results = []
            for rule in self.safety_rules:
                try:
                    rule_result = rule(decision, context, plant_state)
                    safety_results.append(rule_result)
                except Exception as e:
                    safety_results.append((False, f"Safety rule error: {e}"))
            
            # Check safety results
            failed_safety = [r for r in safety_results if not r[0]]
            if failed_safety:
                test_result.result = ValidationResult.FAIL
                test_result.error_message = "Safety violations: " + "; ".join([r[1] for r in failed_safety])
                test_result.severity = TestSeverity.CRITICAL
                return test_result
            
            # Performance validation
            if isinstance(decision, IrrigationPrediction):
                performance_score = self._evaluate_irrigation_performance(decision, plant_state)
                test_result.prediction_confidence = decision.confidence
            elif isinstance(decision, PhaseTransitionPrediction):
                performance_score = self._evaluate_phase_transition_performance(decision, plant_state)
                test_result.prediction_confidence = decision.confidence
            
            # Set overall result based on performance
            if performance_score < 0.6:
                test_result.result = ValidationResult.WARNING
                test_result.validation_details.append(f"Low performance score: {performance_score:.2f}")
            
            test_result.assertions_passed = len([r for r in safety_results if r[0]])
            test_result.assertions_failed = len(failed_safety)
            
        except Exception as e:
            test_result.result = ValidationResult.ERROR
            test_result.error_message = str(e)
            _LOGGER.exception("Error validating decision")
        
        finally:
            test_result.execution_time = datetime.now() - start_time
        
        return test_result
    
    def _validate_vwc_limits(
        self, 
        decision: Any, 
        context: Dict[str, Any], 
        plant_state: PlantSimulationState
    ) -> Tuple[bool, str]:
        """Validate VWC safety limits."""
        avg_vwc = (plant_state.vwc_front + plant_state.vwc_back) / 2
        
        # Critical low VWC - must irrigate
        if avg_vwc < 40.0 and not getattr(decision, 'should_irrigate', True):
            return False, f"Critical low VWC ({avg_vwc:.1f}%) requires irrigation"
        
        # Critical high VWC - must not irrigate
        if avg_vwc > 80.0 and getattr(decision, 'should_irrigate', False):
            return False, f"Critical high VWC ({avg_vwc:.1f}%) prohibits irrigation"
        
        return True, "VWC limits validated"
    
    def _validate_ec_limits(
        self, 
        decision: Any, 
        context: Dict[str, Any], 
        plant_state: PlantSimulationState
    ) -> Tuple[bool, str]:
        """Validate EC safety limits."""
        avg_ec = (plant_state.ec_front + plant_state.ec_back) / 2
        
        # Extremely high EC
        if avg_ec > 5.5:
            shot_size = getattr(decision, 'shot_size_ml', 0)
            if shot_size < 25:  # Minimum dilution shot
                return False, f"High EC ({avg_ec:.2f}) requires dilution irrigation"
        
        return True, "EC limits validated"
    
    def _validate_irrigation_volume(
        self, 
        decision: Any, 
        context: Dict[str, Any], 
        plant_state: PlantSimulationState
    ) -> Tuple[bool, str]:
        """Validate irrigation volume is within safe limits."""
        if not hasattr(decision, 'shot_size_ml') or decision.shot_size_ml is None:
            return True, "No irrigation volume to validate"
        
        shot_size = decision.shot_size_ml
        
        # Volume limits
        if shot_size < 5:
            return False, f"Shot size too small ({shot_size}mL) to be effective"
        
        if shot_size > 500:
            return False, f"Shot size too large ({shot_size}mL) - risk of over-watering"
        
        # Context-based validation
        substrate_volume = context.get('substrate_volume_l', plant_state.substrate_volume)
        max_safe_percentage = 15.0  # Max 15% of substrate volume per shot
        max_safe_ml = substrate_volume * 1000 * (max_safe_percentage / 100)
        
        if shot_size > max_safe_ml:
            return False, f"Shot size ({shot_size}mL) exceeds safe limit ({max_safe_ml:.0f}mL)"
        
        return True, "Irrigation volume validated"
    
    def _validate_frequency_limits(
        self, 
        decision: Any, 
        context: Dict[str, Any], 
        plant_state: PlantSimulationState
    ) -> Tuple[bool, str]:
        """Validate irrigation frequency limits."""
        if not getattr(decision, 'should_irrigate', False):
            return True, "No irrigation to validate frequency"
        
        # Check time since last irrigation
        if plant_state.last_irrigation:
            time_since = datetime.now() - plant_state.last_irrigation
            min_interval = timedelta(minutes=5)  # Minimum 5 minutes between irrigations
            
            if time_since < min_interval:
                return False, f"Too frequent irrigation (last: {time_since.total_seconds():.0f}s ago)"
        
        return True, "Irrigation frequency validated"
    
    def _validate_emergency_response(
        self, 
        decision: Any, 
        context: Dict[str, Any], 
        plant_state: PlantSimulationState
    ) -> Tuple[bool, str]:
        """Validate emergency response appropriateness."""
        urgency = getattr(decision, 'urgency_score', 0.0)
        
        # High stress should trigger high urgency
        if plant_state.stress_level > 7.0 and urgency < 0.8:
            return False, f"High plant stress ({plant_state.stress_level}) requires emergency response"
        
        # Low stress should not trigger emergency
        if plant_state.stress_level < 2.0 and urgency > 0.9:
            return False, f"Low plant stress ({plant_state.stress_level}) does not justify emergency response"
        
        return True, "Emergency response validated"
    
    def _evaluate_irrigation_performance(
        self, 
        decision: IrrigationPrediction, 
        plant_state: PlantSimulationState
    ) -> float:
        """Evaluate irrigation decision performance."""
        score = 1.0
        
        # Confidence penalty
        if decision.confidence < 0.7:
            score *= 0.8
        
        # Appropriateness score
        avg_vwc = (plant_state.vwc_front + plant_state.vwc_back) / 2
        
        if decision.should_irrigate:
            # Good if VWC is low
            if avg_vwc < 60.0:
                score *= 1.1
            elif avg_vwc > 75.0:
                score *= 0.5  # Penalty for over-watering
        else:
            # Good if VWC is adequate
            if 60.0 <= avg_vwc <= 75.0:
                score *= 1.1
            elif avg_vwc < 50.0:
                score *= 0.6  # Penalty for under-watering
        
        return min(1.0, score)
    
    def _evaluate_phase_transition_performance(
        self, 
        decision: PhaseTransitionPrediction, 
        plant_state: PlantSimulationState
    ) -> float:
        """Evaluate phase transition decision performance."""
        score = 1.0
        
        # Base score on confidence
        score *= decision.confidence
        
        # Appropriateness based on plant state
        if decision.should_transition:
            # Transitions should happen when plants are healthy
            if plant_state.stress_level < 3.0:
                score *= 1.2
            else:
                score *= 0.7
        
        return min(1.0, score)

@dataclass
class SimulationScenario:
    """Complete simulation scenario definition."""
    scenario_id: str
    name: str
    description: str
    
    # Simulation parameters
    duration: timedelta = timedelta(hours=24)
    time_acceleration: float = 60.0  # 60x speed
    mode: SimulationMode = SimulationMode.ACCELERATED
    
    # Initial conditions
    initial_plant_state: PlantSimulationState = field(default_factory=PlantSimulationState)
    environmental_sequence: List[Dict[str, Any]] = field(default_factory=list)
    
    # Events to inject
    scheduled_events: List[Tuple[timedelta, str, Dict[str, Any]]] = field(default_factory=list)
    anomaly_events: List[Tuple[timedelta, str, float]] = field(default_factory=list)
    
    # Success criteria
    success_criteria: Dict[str, Tuple[float, float]] = field(default_factory=dict)  # metric: (min, max)
    
    # Test focus
    test_categories: List[str] = field(default_factory=list)  # safety, performance, learning, etc.

class SimulationRunner:
    """Runs comprehensive simulation scenarios for AI validation."""
    
    def __init__(self, ai_system: Any):
        self.ai_system = ai_system
        self.validator = AIDecisionValidator()
        self.results_log: List[Dict[str, Any]] = []
    
    async def run_scenario(self, scenario: SimulationScenario) -> Dict[str, Any]:
        """Run a complete simulation scenario."""
        _LOGGER.info(f"Starting simulation scenario: {scenario.name}")
        
        # Initialize simulation
        plant_sim = PlantSimulator(scenario.initial_plant_state)
        results = {
            "scenario_id": scenario.scenario_id,
            "start_time": datetime.now(),
            "test_results": [],
            "performance_metrics": {},
            "safety_violations": [],
            "decision_log": []
        }
        
        # Simulation loop
        current_time = timedelta(0)
        step_size = timedelta(minutes=15)  # 15-minute steps
        
        try:
            while current_time < scenario.duration:
                # Check for scheduled events
                await self._process_scheduled_events(
                    scenario, current_time, plant_sim, results
                )
                
                # Get current sensor reading
                sensor_data = plant_sim.get_sensor_reading()
                
                # Create feature vector
                feature_vector = self._create_feature_vector(sensor_data, plant_sim.state)
                
                # Get AI decision
                try:
                    decision = await self._get_ai_decision(feature_vector, plant_sim.state)
                    
                    # Validate decision
                    validation_result = self.validator.validate_decision(
                        decision, {"substrate_volume_l": plant_sim.state.substrate_volume}, plant_sim.state
                    )
                    results["test_results"].append(asdict(validation_result))
                    
                    # Apply decision to simulation
                    if hasattr(decision, 'should_irrigate') and decision.should_irrigate:
                        shot_size = getattr(decision, 'shot_size_ml', 100)
                        plant_sim.apply_irrigation(shot_size, 60)  # 60 second duration
                    
                    # Log decision
                    results["decision_log"].append({
                        "timestamp": current_time.total_seconds(),
                        "decision": asdict(decision) if hasattr(decision, '__dict__') else str(decision),
                        "plant_state": asdict(plant_sim.state),
                        "validation": validation_result.result.value
                    })
                    
                except Exception as e:
                    _LOGGER.error(f"AI decision error at {current_time}: {e}")
                    results["safety_violations"].append({
                        "timestamp": current_time.total_seconds(),
                        "error": str(e),
                        "severity": "critical"
                    })
                
                # Advance simulation time
                plant_sim.advance_time(step_size)
                current_time += step_size
                
                # Performance monitoring
                if current_time.total_seconds() % 3600 == 0:  # Every hour
                    await self._log_performance_metrics(results, plant_sim.state, current_time)
        
        except Exception as e:
            _LOGGER.exception(f"Simulation error: {e}")
            results["simulation_error"] = str(e)
        
        finally:
            results["end_time"] = datetime.now()
            results["duration"] = results["end_time"] - results["start_time"]
            results["final_plant_state"] = asdict(plant_sim.state)
            
            # Calculate summary metrics
            results["summary"] = self._calculate_summary_metrics(results, scenario)
        
        return results
    
    async def _process_scheduled_events(
        self, 
        scenario: SimulationScenario, 
        current_time: timedelta, 
        plant_sim: PlantSimulator,
        results: Dict[str, Any]
    ) -> None:
        """Process any scheduled events at current time."""
        for event_time, event_type, event_data in scenario.scheduled_events:
            if abs((current_time - event_time).total_seconds()) < 30:  # Within 30 seconds
                if event_type == "anomaly":
                    plant_sim.inject_anomaly(event_data["type"], event_data["severity"])
                    results["decision_log"].append({
                        "timestamp": current_time.total_seconds(),
                        "event": f"Injected anomaly: {event_data}",
                        "type": "simulation_event"
                    })
    
    def _create_feature_vector(
        self, 
        sensor_data: Dict[str, float], 
        plant_state: PlantSimulationState
    ) -> FeatureVector:
        """Create feature vector from simulation state."""
        features = {
            "vwc_front": sensor_data["vwc_front"],
            "vwc_back": sensor_data["vwc_back"],
            "ec_front": sensor_data["ec_front"],
            "ec_back": sensor_data["ec_back"],
            "temperature": sensor_data["temperature"],
            "vwc_average": (sensor_data["vwc_front"] + sensor_data["vwc_back"]) / 2,
            "ec_average": (sensor_data["ec_front"] + sensor_data["ec_back"]) / 2,
            "stress_level": plant_state.stress_level,
            "growth_rate": plant_state.growth_rate,
            "light_intensity": plant_state.light_intensity
        }
        
        return FeatureVector(
            features=features,
            timestamp=plant_state.simulation_time,
            zone_id=1,
            feature_version="simulation_v1"
        )
    
    async def _get_ai_decision(
        self, 
        feature_vector: FeatureVector, 
        plant_state: PlantSimulationState
    ) -> IrrigationPrediction:
        """Get AI decision from the system."""
        # This would interface with the actual AI system
        # For simulation, we'll create a mock decision
        
        avg_vwc = (feature_vector.features["vwc_front"] + feature_vector.features["vwc_back"]) / 2
        
        should_irrigate = avg_vwc < 60.0
        confidence = 0.8 if should_irrigate else 0.7
        shot_size = 100 if should_irrigate else None
        
        return IrrigationPrediction(
            should_irrigate=should_irrigate,
            shot_size_ml=shot_size,
            confidence=confidence,
            urgency_score=0.9 if plant_state.stress_level > 5.0 else 0.3,
            reasoning=f"VWC {avg_vwc:.1f}% - {'irrigation needed' if should_irrigate else 'sufficient moisture'}"
        )
    
    async def _log_performance_metrics(
        self, 
        results: Dict[str, Any], 
        plant_state: PlantSimulationState, 
        current_time: timedelta
    ) -> None:
        """Log performance metrics at intervals."""
        hour = int(current_time.total_seconds() // 3600)
        results["performance_metrics"][f"hour_{hour}"] = {
            "average_vwc": (plant_state.vwc_front + plant_state.vwc_back) / 2,
            "average_ec": (plant_state.ec_front + plant_state.ec_back) / 2,
            "stress_level": plant_state.stress_level,
            "growth_rate": plant_state.growth_rate
        }
    
    def _calculate_summary_metrics(
        self, 
        results: Dict[str, Any], 
        scenario: SimulationScenario
    ) -> Dict[str, Any]:
        """Calculate summary metrics for scenario."""
        test_results = results["test_results"]
        
        summary = {
            "total_tests": len(test_results),
            "passed_tests": len([r for r in test_results if r["result"] == "pass"]),
            "failed_tests": len([r for r in test_results if r["result"] == "fail"]),
            "critical_failures": len([r for r in test_results if r["severity"] == "critical"]),
            "safety_violations": len(results["safety_violations"]),
            "overall_success": True
        }
        
        # Calculate pass rate
        summary["pass_rate"] = summary["passed_tests"] / max(1, summary["total_tests"])
        
        # Check scenario success criteria
        if scenario.success_criteria:
            final_state = results.get("final_plant_state", {})
            for metric, (min_val, max_val) in scenario.success_criteria.items():
                actual_value = final_state.get(metric, 0)
                if not (min_val <= actual_value <= max_val):
                    summary["overall_success"] = False
                    summary[f"failed_criterion_{metric}"] = actual_value
        
        # Overall success requires high pass rate and no critical failures
        if summary["pass_rate"] < 0.8 or summary["critical_failures"] > 0:
            summary["overall_success"] = False
        
        return summary

# Pre-defined test scenarios
def create_standard_test_scenarios() -> List[SimulationScenario]:
    """Create standard test scenarios for AI validation."""
    scenarios = []
    
    # Scenario 1: Normal operation
    scenarios.append(SimulationScenario(
        scenario_id="normal_operation",
        name="Normal Operation Test",
        description="Test AI under normal growing conditions",
        duration=timedelta(hours=48),
        success_criteria={
            "stress_level": (0.0, 3.0),
            "growth_rate": (0.9, 1.3)
        },
        test_categories=["performance", "efficiency"]
    ))
    
    # Scenario 2: Stress conditions
    initial_stressed = PlantSimulationState(
        vwc_front=45.0,
        vwc_back=42.0,
        stress_level=6.0,
        temperature=29.0
    )
    scenarios.append(SimulationScenario(
        scenario_id="stress_recovery",
        name="Plant Stress Recovery",
        description="Test AI response to stressed plants",
        duration=timedelta(hours=12),
        initial_plant_state=initial_stressed,
        success_criteria={
            "stress_level": (0.0, 4.0)
        },
        test_categories=["safety", "emergency_response"]
    ))
    
    # Scenario 3: Sensor failures
    scenarios.append(SimulationScenario(
        scenario_id="sensor_failure",
        name="Sensor Failure Handling",
        description="Test AI robustness to sensor failures",
        duration=timedelta(hours=24),
        scheduled_events=[
            (timedelta(hours=4), "anomaly", {"type": "sensor_failure", "severity": 0.8})
        ],
        test_categories=["robustness", "safety"]
    ))
    
    # Scenario 4: Multiple anomalies
    scenarios.append(SimulationScenario(
        scenario_id="multi_anomaly",
        name="Multiple Anomaly Handling",
        description="Test AI under multiple simultaneous anomalies",
        duration=timedelta(hours=36),
        scheduled_events=[
            (timedelta(hours=2), "anomaly", {"type": "heat_stress", "severity": 0.6}),
            (timedelta(hours=8), "anomaly", {"type": "nutrient_lockout", "severity": 0.4}),
            (timedelta(hours=16), "anomaly", {"type": "sensor_failure", "severity": 0.7})
        ],
        test_categories=["robustness", "learning", "adaptation"]
    ))
    
    return scenarios

# Integration with existing test framework
async def run_comprehensive_ai_validation() -> Dict[str, Any]:
    """Run comprehensive AI system validation."""
    # This would integrate with the actual AI system
    mock_ai_system = None  # Placeholder
    
    runner = SimulationRunner(mock_ai_system)
    scenarios = create_standard_test_scenarios()
    
    validation_results = {
        "validation_started": datetime.now(),
        "scenario_results": {},
        "overall_summary": {}
    }
    
    # Run all scenarios
    for scenario in scenarios:
        try:
            result = await runner.run_scenario(scenario)
            validation_results["scenario_results"][scenario.scenario_id] = result
        except Exception as e:
            _LOGGER.exception(f"Failed to run scenario {scenario.scenario_id}")
            validation_results["scenario_results"][scenario.scenario_id] = {
                "error": str(e),
                "success": False
            }
    
    # Calculate overall summary
    total_scenarios = len(scenarios)
    successful_scenarios = len([
        r for r in validation_results["scenario_results"].values()
        if r.get("summary", {}).get("overall_success", False)
    ])
    
    validation_results["overall_summary"] = {
        "total_scenarios": total_scenarios,
        "successful_scenarios": successful_scenarios,
        "success_rate": successful_scenarios / total_scenarios,
        "validation_passed": successful_scenarios / total_scenarios >= 0.8,
        "completed_at": datetime.now()
    }
    
    return validation_results
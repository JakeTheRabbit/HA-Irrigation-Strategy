"""Type-safe interfaces for ML pipeline integration.

Provides comprehensive type definitions for machine learning model integration,
feature engineering, and decision tree systems in the crop steering system.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, IntEnum
from typing import (
    Any, 
    Callable, 
    Dict, 
    List, 
    Optional, 
    Tuple, 
    Union, 
    Generic, 
    TypeVar, 
    Protocol,
    runtime_checkable
)
import numpy as np
from numpy.typing import NDArray

# Type variables for generic ML components
T = TypeVar('T')
ModelInput = TypeVar('ModelInput')
ModelOutput = TypeVar('ModelOutput')
FeatureType = Union[float, int, str, bool]

class MLFramework(Enum):
    """Supported ML frameworks."""
    SCIKIT_LEARN = "scikit_learn"
    TENSORFLOW = "tensorflow" 
    PYTORCH = "pytorch"
    XGBOOST = "xgboost"
    LIGHTGBM = "lightgbm"

class ModelType(Enum):
    """Types of ML models."""
    REGRESSION = "regression"
    CLASSIFICATION = "classification"
    CLUSTERING = "clustering"
    REINFORCEMENT_LEARNING = "reinforcement_learning"
    TIME_SERIES = "time_series"
    ANOMALY_DETECTION = "anomaly_detection"

class ModelStatus(Enum):
    """Model lifecycle status."""
    TRAINING = "training"
    VALIDATING = "validating"
    DEPLOYED = "deployed"
    DEPRECATED = "deprecated"
    FAILED = "failed"
    RETRAINING = "retraining"

class FeatureImportance(IntEnum):
    """Feature importance levels."""
    CRITICAL = 5
    HIGH = 4
    MEDIUM = 3
    LOW = 2
    MINIMAL = 1

@dataclass(frozen=True)
class ModelVersion:
    """Immutable model version identifier."""
    major: int
    minor: int
    patch: int
    build: Optional[str] = None
    
    def __str__(self) -> str:
        version = f"{self.major}.{self.minor}.{self.patch}"
        return f"{version}-{self.build}" if self.build else version
    
    def __lt__(self, other: ModelVersion) -> bool:
        """Compare versions for ordering."""
        return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)

@dataclass
class FeatureDefinition:
    """Type-safe feature definition."""
    name: str
    dtype: type
    description: str
    importance: FeatureImportance = FeatureImportance.MEDIUM
    
    # Feature validation
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    allowed_values: Optional[List[Any]] = None
    nullable: bool = False
    
    # Feature engineering
    transform_func: Optional[Callable[[Any], FeatureType]] = None
    aggregation_window: Optional[timedelta] = None
    feature_group: Optional[str] = None
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)
    
    def validate_value(self, value: Any) -> bool:
        """Validate feature value against constraints."""
        if value is None:
            return self.nullable
        
        if self.min_value is not None and value < self.min_value:
            return False
        
        if self.max_value is not None and value > self.max_value:
            return False
        
        if self.allowed_values is not None and value not in self.allowed_values:
            return False
        
        return True

@dataclass
class FeatureVector:
    """Type-safe feature vector with metadata."""
    features: Dict[str, FeatureType]
    timestamp: datetime
    zone_id: int
    feature_version: str
    
    # Quality indicators
    completeness: float = 1.0  # 0-1 ratio of non-null features
    confidence: float = 1.0    # 0-1 confidence in feature quality
    validation_errors: List[str] = field(default_factory=list)
    
    def get_feature(self, name: str, default: Optional[FeatureType] = None) -> FeatureType:
        """Safely get feature value."""
        return self.features.get(name, default)
    
    def to_numpy(self, feature_order: List[str]) -> NDArray[np.floating]:
        """Convert to numpy array for ML models."""
        return np.array([
            float(self.features.get(name, 0.0)) 
            for name in feature_order
        ], dtype=np.float64)

@runtime_checkable 
class MLModel(Protocol, Generic[ModelInput, ModelOutput]):
    """Protocol for ML model implementations."""
    
    @property
    def model_id(self) -> str: ...
    
    @property
    def version(self) -> ModelVersion: ...
    
    @property
    def framework(self) -> MLFramework: ...
    
    @property
    def model_type(self) -> ModelType: ...
    
    @property
    def status(self) -> ModelStatus: ...
    
    def predict(self, input_data: ModelInput) -> ModelOutput: ...
    
    def predict_proba(self, input_data: ModelInput) -> Optional[NDArray[np.floating]]: ...
    
    def get_feature_importance(self) -> Dict[str, float]: ...
    
    def validate_input(self, input_data: ModelInput) -> Tuple[bool, List[str]]: ...

@dataclass
class ModelPrediction(Generic[T]):
    """Type-safe model prediction with metadata."""
    prediction: T
    confidence: float
    probabilities: Optional[Dict[str, float]] = None
    
    # Model metadata
    model_id: str = ""
    model_version: ModelVersion = field(default_factory=lambda: ModelVersion(0, 0, 1))
    timestamp: datetime = field(default_factory=datetime.now)
    
    # Feature attribution
    feature_importance: Dict[str, float] = field(default_factory=dict)
    shap_values: Optional[NDArray[np.floating]] = None
    
    # Processing metadata
    processing_time_ms: float = 0.0
    cache_hit: bool = False
    
    def is_confident(self, threshold: float = 0.8) -> bool:
        """Check if prediction meets confidence threshold."""
        return self.confidence >= threshold

@dataclass
class IrrigationPrediction:
    """Specialized prediction for irrigation decisions."""
    should_irrigate: bool
    shot_size_ml: Optional[int] = None
    confidence: float = 0.0
    urgency_score: float = 0.0  # 0-1 scale
    
    # Time predictions
    optimal_timing_minutes: Optional[int] = None
    next_check_minutes: int = 15
    
    # Context
    reasoning: str = ""
    risk_factors: List[str] = field(default_factory=list)
    expected_vwc_change: Optional[float] = None
    
    # Model metadata
    model_ensemble_size: int = 1
    model_agreement: float = 1.0  # Agreement across ensemble models

@dataclass
class PhaseTransitionPrediction:
    """Prediction for phase transitions."""
    should_transition: bool
    next_phase: Optional[str] = None
    confidence: float = 0.0
    
    # Timing
    optimal_transition_time: Optional[datetime] = None
    phase_duration_remaining: Optional[timedelta] = None
    
    # Reasoning
    transition_triggers: List[str] = field(default_factory=list)
    blocking_factors: List[str] = field(default_factory=list)
    readiness_score: float = 0.0

@dataclass 
class AnomalyDetection:
    """Anomaly detection result."""
    is_anomaly: bool
    anomaly_score: float  # Higher = more anomalous
    anomaly_type: str = "unknown"
    
    # Context
    affected_sensors: List[str] = field(default_factory=list)
    severity: str = "low"  # low, medium, high, critical
    
    # Explanation
    explanation: str = ""
    similar_historical_events: List[str] = field(default_factory=list)
    recommended_actions: List[str] = field(default_factory=list)

class FeatureEngineer(ABC):
    """Abstract base class for feature engineering."""
    
    @abstractmethod
    def extract_features(
        self, 
        raw_data: Dict[str, Any],
        historical_data: Optional[List[Dict[str, Any]]] = None
    ) -> FeatureVector:
        """Extract features from raw sensor data."""
        pass
    
    @abstractmethod
    def get_feature_schema(self) -> List[FeatureDefinition]:
        """Get the feature schema definition."""
        pass

@dataclass
class ModelEvaluationMetrics:
    """Comprehensive model evaluation metrics."""
    # Basic metrics
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0
    
    # Regression metrics (if applicable)
    mae: Optional[float] = None  # Mean Absolute Error
    mse: Optional[float] = None  # Mean Squared Error
    rmse: Optional[float] = None # Root Mean Squared Error
    r2_score: Optional[float] = None
    
    # Business metrics
    irrigation_efficiency: float = 0.0
    resource_optimization: float = 0.0
    plant_health_score: float = 0.0
    
    # Reliability metrics
    prediction_stability: float = 0.0
    confidence_calibration: float = 0.0
    out_of_distribution_handling: float = 0.0
    
    # Evaluation metadata
    evaluation_period: timedelta = timedelta(days=7)
    sample_size: int = 0
    last_evaluated: datetime = field(default_factory=datetime.now)

@dataclass
class ModelTrainingConfig:
    """Configuration for model training."""
    # Data configuration
    training_window: timedelta = timedelta(days=30)
    validation_split: float = 0.2
    test_split: float = 0.1
    
    # Model hyperparameters
    hyperparameters: Dict[str, Any] = field(default_factory=dict)
    
    # Training configuration
    max_iterations: int = 1000
    early_stopping_patience: int = 10
    learning_rate: float = 0.001
    batch_size: Optional[int] = None
    
    # Feature selection
    feature_selection_method: Optional[str] = None
    max_features: Optional[int] = None
    
    # Validation
    cross_validation_folds: int = 5
    performance_threshold: float = 0.8
    
    # Resource limits
    max_training_time: timedelta = timedelta(hours=2)
    memory_limit_gb: float = 4.0
    
    # Versioning
    auto_version_increment: bool = True
    training_tag: Optional[str] = None

class ModelRegistry(Protocol):
    """Protocol for model registry implementations."""
    
    def register_model(
        self, 
        model: MLModel, 
        metadata: Dict[str, Any],
        tags: Optional[List[str]] = None
    ) -> str:
        """Register a new model."""
        ...
    
    def get_model(self, model_id: str, version: Optional[ModelVersion] = None) -> Optional[MLModel]:
        """Retrieve a model by ID and version."""
        ...
    
    def list_models(
        self, 
        model_type: Optional[ModelType] = None,
        status: Optional[ModelStatus] = None
    ) -> List[Dict[str, Any]]:
        """List available models with filters."""
        ...
    
    def promote_model(self, model_id: str, version: ModelVersion, target_status: ModelStatus) -> bool:
        """Promote model to production or other status."""
        ...
    
    def deprecate_model(self, model_id: str, version: ModelVersion) -> bool:
        """Mark model as deprecated."""
        ...

@dataclass
class MLPipelineConfig:
    """Configuration for the entire ML pipeline."""
    # Models
    irrigation_model_id: str = "irrigation_predictor_v1"
    phase_transition_model_id: str = "phase_transition_v1" 
    anomaly_detection_model_id: str = "anomaly_detector_v1"
    
    # Feature engineering
    feature_extraction_version: str = "v2.1"
    feature_selection_enabled: bool = True
    feature_scaling_method: str = "standard"
    
    # Prediction settings
    ensemble_voting: str = "soft"  # soft, hard, weighted
    prediction_cache_ttl: timedelta = timedelta(minutes=5)
    
    # Model updates
    retrain_schedule: str = "daily"  # daily, weekly, monthly
    auto_deployment: bool = False
    performance_monitoring: bool = True
    
    # Safety settings
    fallback_to_rules: bool = True
    confidence_threshold: float = 0.7
    max_prediction_age: timedelta = timedelta(minutes=30)

@dataclass 
class BatchPredictionJob:
    """Configuration for batch prediction jobs."""
    job_id: str
    model_ids: List[str]
    input_data_source: str
    
    # Execution
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    batch_size: int = 1000
    parallel_workers: int = 1
    
    # Output
    output_destination: str = ""
    output_format: str = "json"  # json, csv, parquet
    
    # Monitoring
    progress_callback: Optional[Callable[[float], None]] = None
    error_tolerance: float = 0.1  # Fraction of failures allowed
    
    # Status tracking
    status: str = "pending"
    processed_count: int = 0
    error_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)

@runtime_checkable
class MLPipeline(Protocol):
    """Protocol for ML pipeline implementations."""
    
    def predict_irrigation(
        self, 
        zone_id: int,
        current_features: FeatureVector,
        historical_features: Optional[List[FeatureVector]] = None
    ) -> IrrigationPrediction:
        """Make irrigation decision prediction."""
        ...
    
    def predict_phase_transition(
        self,
        zone_id: int, 
        current_phase: str,
        features: FeatureVector
    ) -> PhaseTransitionPrediction:
        """Predict optimal phase transition timing."""
        ...
    
    def detect_anomalies(
        self,
        zone_id: int,
        features: FeatureVector,
        historical_baseline: Optional[List[FeatureVector]] = None
    ) -> AnomalyDetection:
        """Detect system anomalies."""
        ...
    
    def update_models(self, training_data: List[Dict[str, Any]]) -> Dict[str, ModelEvaluationMetrics]:
        """Update all models with new training data."""
        ...
    
    def get_pipeline_health(self) -> Dict[str, Any]:
        """Get overall pipeline health status."""
        ...

# Type aliases for common use cases
SensorDataPoint = Dict[str, Union[float, int, str, datetime]]
TrainingDataset = List[Tuple[FeatureVector, Union[bool, float, int, str]]]
ModelEnsemble = List[Tuple[MLModel, float]]  # Model and weight pairs
PredictionCallback = Callable[[ModelPrediction], None]

# Validation functions
def validate_feature_vector(
    features: FeatureVector, 
    schema: List[FeatureDefinition]
) -> Tuple[bool, List[str]]:
    """Validate feature vector against schema."""
    errors = []
    schema_dict = {fd.name: fd for fd in schema}
    
    # Check for required features
    for feature_def in schema:
        if not feature_def.nullable and feature_def.name not in features.features:
            errors.append(f"Missing required feature: {feature_def.name}")
            continue
        
        # Validate feature values
        if feature_def.name in features.features:
            value = features.features[feature_def.name]
            if not feature_def.validate_value(value):
                errors.append(f"Invalid value for feature {feature_def.name}: {value}")
    
    # Check for unknown features
    for feature_name in features.features:
        if feature_name not in schema_dict:
            errors.append(f"Unknown feature: {feature_name}")
    
    return len(errors) == 0, errors

def create_model_metadata(
    model_id: str,
    version: ModelVersion,
    framework: MLFramework,
    model_type: ModelType,
    training_config: ModelTrainingConfig,
    evaluation_metrics: ModelEvaluationMetrics
) -> Dict[str, Any]:
    """Create standardized model metadata."""
    return {
        "model_id": model_id,
        "version": str(version),
        "framework": framework.value,
        "model_type": model_type.value,
        "created_at": datetime.now().isoformat(),
        "training_config": {
            "training_window": training_config.training_window.total_seconds(),
            "hyperparameters": training_config.hyperparameters,
            "performance_threshold": training_config.performance_threshold
        },
        "evaluation_metrics": {
            "accuracy": evaluation_metrics.accuracy,
            "f1_score": evaluation_metrics.f1_score,
            "irrigation_efficiency": evaluation_metrics.irrigation_efficiency,
            "confidence_calibration": evaluation_metrics.confidence_calibration,
            "sample_size": evaluation_metrics.sample_size
        },
        "deployment_ready": evaluation_metrics.accuracy >= training_config.performance_threshold
    }
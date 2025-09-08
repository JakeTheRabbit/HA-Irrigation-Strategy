"""
Simplified Irrigation Predictor for Crop Steering
Mathematical prediction model without external ML dependencies
Compatible with Home Assistant OS - no compilation required
"""

from collections import deque
from typing import Dict, List, Optional
from datetime import datetime
import logging
import math

_LOGGER = logging.getLogger(__name__)


class SimplifiedIrrigationPredictor:
    """
    Simplified mathematical irrigation predictor using standard library only.
    
    Features:
    - Mathematical trend analysis using statistics module
    - Real-time VWC trend forecasting 
    - Pattern recognition without external dependencies
    - Irrigation efficiency scoring and optimization
    - Adaptive learning from historical irrigation outcomes
    - Dynamic threshold adjustments based on patterns
    """
    
    def _mean(self, data):
        """Calculate mean of data."""
        if not data:
            return 0
        return sum(data) / len(data)
    
    def _std(self, data):
        """Calculate standard deviation of data."""
        if len(data) < 2:
            return 0
        mean_val = self._mean(data)
        variance = sum((x - mean_val) ** 2 for x in data) / (len(data) - 1)
        return variance ** 0.5
    
    def _correlation(self, x, y):
        """Calculate correlation coefficient between two datasets."""
        if len(x) != len(y) or len(x) < 2:
            return 0
        
        mean_x = self._mean(x)
        mean_y = self._mean(y)
        
        numerator = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(len(x)))
        sum_sq_x = sum((x[i] - mean_x) ** 2 for i in range(len(x)))
        sum_sq_y = sum((y[i] - mean_y) ** 2 for i in range(len(y)))
        
        denominator = (sum_sq_x * sum_sq_y) ** 0.5
        
        if denominator == 0:
            return 0
        
        return numerator / denominator
    
    def __init__(self, history_window: int = 500, prediction_horizon: int = 120,
                 update_frequency: int = 50, min_training_samples: int = 30):
        """
        Initialize simplified irrigation predictor.
        
        Args:
            history_window: Size of historical data window
            prediction_horizon: Prediction horizon in minutes
            update_frequency: Update model every N samples
            min_training_samples: Minimum samples needed for predictions
        """
        self.history_window = history_window
        self.prediction_horizon = prediction_horizon
        self.update_frequency = update_frequency
        self.min_training_samples = min_training_samples
        
        # Data storage
        self.feature_history = deque(maxlen=history_window)
        self.target_history = deque(maxlen=history_window)
        self.timestamp_history = deque(maxlen=history_window)
        
        # Model state
        self.model_trained = False
        self.model_accuracy = 0.0
        self.training_count = 0
        self.last_update_time = datetime.now()
        
        # Prediction parameters
        self.feature_weights = {
            'vwc_trend': 0.4,
            'dryback_rate': 0.3,
            'time_since_last': 0.2,
            'ec_ratio': 0.1
        }
        
        # Trend analysis
        self.trend_coefficients = {}
        self.prediction_confidence = 0.5
        
        # Performance tracking
        self.prediction_errors = deque(maxlen=100)
        self.irrigation_success_rate = 0.0
        
        _LOGGER.info(f"Simplified Irrigation Predictor initialized: history={history_window}, "
                    f"horizon={prediction_horizon}min, update_freq={update_frequency}")

    def add_training_sample(self, features: Dict, irrigation_outcome: Dict, 
                           timestamp: datetime = None) -> Dict:
        """
        Add training sample for model learning.
        
        Args:
            features: Feature dictionary with sensor and environmental data
            irrigation_outcome: Results of irrigation decision
            timestamp: Sample timestamp
            
        Returns:
            Dict with sample addition status
        """
        try:
            if timestamp is None:
                timestamp = datetime.now()
                
            # Extract features
            feature_vector = self._extract_features(features)
            if feature_vector is None:
                return {'success': False, 'reason': 'invalid_features'}
                
            # Calculate target (irrigation need 0-1)
            target = self._calculate_irrigation_target(features, irrigation_outcome)
            
            # Store sample
            self.feature_history.append(feature_vector)
            self.target_history.append(target)
            self.timestamp_history.append(timestamp)
            
            self.training_count += 1
            
            # Update model periodically
            if (self.training_count % self.update_frequency == 0 and 
                len(self.feature_history) >= self.min_training_samples):
                self._update_model()
                
            return {
                'success': True,
                'samples': len(self.feature_history),
                'model_trained': self.model_trained
            }
            
        except Exception as e:
            _LOGGER.error(f"Error adding training sample: {e}")
            return {'success': False, 'reason': str(e)}

    def predict_irrigation_need(self, features: Dict, horizon_minutes: int = None) -> Dict:
        """
        Predict irrigation need using mathematical model.
        
        Args:
            features: Current feature dictionary
            horizon_minutes: Prediction horizon
            
        Returns:
            Dict with prediction results
        """
        try:
            if horizon_minutes is None:
                horizon_minutes = self.prediction_horizon
                
            # Extract features
            feature_vector = self._extract_features(features)
            if feature_vector is None:
                return self._default_prediction(horizon_minutes, 'invalid_features')
                
            # Make prediction
            if self.model_trained and len(self.feature_history) >= self.min_training_samples:
                irrigation_need = self._mathematical_predict(feature_vector)
                confidence = self._calculate_confidence(horizon_minutes)
                status = 'trained'
            else:
                # Fallback to simple heuristic
                irrigation_need = self._heuristic_predict(feature_vector)
                confidence = 0.4
                status = 'learning'
                
            # Ensure bounds
            irrigation_need = max(0.0, min(1.0, irrigation_need))
            confidence = max(0.1, min(0.95, confidence))
            
            return {
                'irrigation_need': irrigation_need,
                'confidence': confidence,
                'horizon_minutes': horizon_minutes,
                'prediction_components': {
                    'vwc_component': feature_vector[0] * self.feature_weights['vwc_trend'],
                    'dryback_component': feature_vector[1] * self.feature_weights['dryback_rate'],
                    'time_component': feature_vector[2] * self.feature_weights['time_since_last'],
                    'ec_component': feature_vector[3] * self.feature_weights['ec_ratio']
                },
                'model_status': status,
                'training_samples': len(self.feature_history)
            }
            
        except Exception as e:
            _LOGGER.error(f"Error predicting irrigation need: {e}")
            return self._default_prediction(horizon_minutes, 'error')

    def _extract_features(self, features: Dict) -> Optional[List[float]]:
        """
        Extract numerical features from feature dictionary.
        
        Args:
            features: Raw feature dictionary
            
        Returns:
            List of numerical features or None if invalid
        """
        try:
            # Core features for simplified model
            vwc_current = features.get('current_vwc', 50.0)
            vwc_trend = features.get('vwc_trend_15min', 0.0)
            
            # VWC trend component (normalized)
            vwc_component = (70.0 - vwc_current) / 70.0  # Higher when VWC is low
            if vwc_trend < 0:  # VWC decreasing
                vwc_component += abs(vwc_trend) / 10.0
                
            # Dryback rate component
            dryback_pct = features.get('dryback_percentage', 0.0)
            dryback_rate = features.get('dryback_rate', 0.0)
            dryback_component = (dryback_pct / 25.0) + abs(dryback_rate) / 5.0
            
            # Time since last irrigation component
            time_since_last = features.get('time_since_last_irrigation', 60)
            time_component = min(time_since_last / 120.0, 1.0)  # Normalize to 2 hours
            
            # EC ratio component
            ec_ratio = features.get('ec_ratio', 1.0)
            ec_component = max(0.0, (ec_ratio - 1.0) / 2.0)  # Higher when EC is high
            
            return [vwc_component, dryback_component, time_component, ec_component]
            
        except Exception as e:
            _LOGGER.error(f"Error extracting features: {e}")
            return None

    def _calculate_irrigation_target(self, features: Dict, outcome: Dict) -> float:
        """
        Calculate target irrigation need from outcome.
        
        Args:
            features: Feature dictionary
            outcome: Irrigation outcome dictionary
            
        Returns:
            Target value (0-1)
        """
        try:
            # Simple target calculation based on outcome success
            irrigation_performed = outcome.get('irrigation_performed', False)
            vwc_improved = outcome.get('vwc_improved', False)
            target_reached = outcome.get('target_reached', False)
            
            if irrigation_performed:
                if vwc_improved and target_reached:
                    return 0.8  # Good irrigation decision
                elif vwc_improved:
                    return 0.6  # Partially successful
                else:
                    return 0.3  # Poor timing
            else:
                # No irrigation performed
                vwc_stable = outcome.get('vwc_stable', True)
                if vwc_stable:
                    return 0.2  # Good decision to wait
                else:
                    return 0.7  # Should have irrigated
                    
        except Exception:
            return 0.5  # Default neutral target

    def _mathematical_predict(self, feature_vector: List[float]) -> float:
        """
        Mathematical prediction using weighted features and trends.
        
        Args:
            feature_vector: List of feature values
            
        Returns:
            Irrigation need prediction (0-1)
        """
        try:
            # Weighted sum of components
            prediction = (
                feature_vector[0] * self.feature_weights['vwc_trend'] +
                feature_vector[1] * self.feature_weights['dryback_rate'] +
                feature_vector[2] * self.feature_weights['time_since_last'] +
                feature_vector[3] * self.feature_weights['ec_ratio']
            )
            
            # Apply sigmoid activation for smooth 0-1 output
            sigmoid_prediction = 1 / (1 + math.exp(-(prediction * 8 - 4)))
            
            return sigmoid_prediction
            
        except Exception as e:
            _LOGGER.error(f"Error in mathematical prediction: {e}")
            return 0.5

    def _heuristic_predict(self, feature_vector: List[float]) -> float:
        """
        Simple heuristic prediction for learning phase.
        
        Args:
            feature_vector: List of feature values
            
        Returns:
            Irrigation need prediction (0-1)
        """
        # Simple linear combination
        prediction = sum(feature_vector) / len(feature_vector)
        return max(0.1, min(0.9, prediction))

    def _update_model(self):
        """
        Update model parameters based on training data.
        """
        try:
            if len(self.feature_history) < self.min_training_samples:
                return
                
            # Convert to lists
            features_list = list(self.feature_history)
            targets_list = list(self.target_history)
            
            # Calculate correlations to update feature weights
            correlations = []
            num_features = len(features_list[0]) if features_list else 4
            for i in range(num_features):
                feature_col = [feat[i] for feat in features_list]
                if self._std(feature_col) > 0:  # Avoid division by zero
                    corr = self._correlation(feature_col, targets_list)
                    correlations.append(abs(corr) if corr == corr else 0.1)  # Check for NaN
                else:
                    correlations.append(0.1)
            
            # Update feature weights
            total_corr = sum(correlations)
            if total_corr > 0:
                weight_names = ['vwc_trend', 'dryback_rate', 'time_since_last', 'ec_ratio']
                for i, name in enumerate(weight_names):
                    self.feature_weights[name] = correlations[i] / total_corr
            
            # Calculate model accuracy
            recent_predictions = []
            recent_targets = []
            
            for i in range(max(0, len(self.feature_history) - 50), len(self.feature_history)):
                pred = self._mathematical_predict(list(self.feature_history)[i])
                recent_predictions.append(pred)
                recent_targets.append(list(self.target_history)[i])
            
            if recent_predictions:
                # Calculate R-squared equivalent
                ss_res = sum((recent_targets[i] - recent_predictions[i]) ** 2 for i in range(len(recent_targets)))
                targets_mean = self._mean(recent_targets)
                ss_tot = sum((target - targets_mean) ** 2 for target in recent_targets)
                
                if ss_tot > 0:
                    r_squared = 1 - (ss_res / ss_tot)
                    self.model_accuracy = max(0.0, r_squared)
                else:
                    self.model_accuracy = 0.5
                    
                self.prediction_confidence = min(0.95, max(0.3, self.model_accuracy))
                
            self.model_trained = True
            self.last_update_time = datetime.now()
            
            _LOGGER.info(f"Model updated: accuracy={self.model_accuracy:.3f}, "
                        f"confidence={self.prediction_confidence:.3f}, "
                        f"samples={len(self.feature_history)}")
            
        except Exception as e:
            _LOGGER.error(f"Error updating model: {e}")

    def _calculate_confidence(self, horizon_minutes: int) -> float:
        """
        Calculate prediction confidence based on horizon and model performance.
        
        Args:
            horizon_minutes: Prediction horizon
            
        Returns:
            Confidence value (0-1)
        """
        # Base confidence from model accuracy
        base_confidence = self.prediction_confidence if self.model_trained else 0.4
        
        # Reduce confidence for longer horizons
        horizon_factor = max(0.2, 1.0 - (horizon_minutes - 60) / 240)
        
        return base_confidence * horizon_factor

    def _default_prediction(self, horizon_minutes: int, reason: str) -> Dict:
        """
        Return default prediction when normal prediction fails.
        
        Args:
            horizon_minutes: Prediction horizon
            reason: Reason for default prediction
            
        Returns:
            Default prediction dictionary
        """
        return {
            'irrigation_need': 0.5,
            'confidence': 0.3,
            'horizon_minutes': horizon_minutes,
            'prediction_components': {},
            'model_status': f'default_{reason}',
            'training_samples': len(self.feature_history)
        }

    def get_model_status(self) -> Dict:
        """
        Get comprehensive model status information.
        
        Returns:
            Dict with model status and performance metrics
        """
        return {
            'model_type': 'simplified_mathematical',
            'trained': self.model_trained,
            'training_samples': len(self.feature_history),
            'model_accuracy': self.model_accuracy,
            'prediction_confidence': self.prediction_confidence,
            'feature_weights': self.feature_weights.copy(),
            'last_update': self.last_update_time.isoformat() if self.last_update_time else None,
            'prediction_horizon': self.prediction_horizon,
            'dependencies': ['statistics'],
            'compilation_required': False
        }

    def reset_model(self):
        """
        Reset model and clear all training data.
        """
        self.feature_history.clear()
        self.target_history.clear()
        self.timestamp_history.clear()
        
        self.model_trained = False
        self.model_accuracy = 0.0
        self.training_count = 0
        self.prediction_confidence = 0.5
        
        # Reset feature weights to defaults
        self.feature_weights = {
            'vwc_trend': 0.4,
            'dryback_rate': 0.3,
            'time_since_last': 0.2,
            'ec_ratio': 0.1
        }
        
        _LOGGER.info("Simplified model reset successfully")

    def export_model_data(self) -> Dict:
        """
        Export model data for backup or analysis.
        
        Returns:
            Dict with exportable model data
        """
        return {
            'model_type': 'simplified_mathematical',
            'feature_weights': self.feature_weights,
            'model_accuracy': self.model_accuracy,
            'prediction_confidence': self.prediction_confidence,
            'training_samples': len(self.feature_history),
            'last_update': self.last_update_time.isoformat() if self.last_update_time else None
        }


# Alias for backward compatibility
MLIrrigationPredictor = SimplifiedIrrigationPredictor
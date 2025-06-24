"""
Intelligent Sensor Fusion for Crop Steering
Implements IQR-based outlier detection and multi-sensor validation
Based on research: Generalized ESD + weighted outlier-robust Kalman filter
"""

import statistics
import math
from collections import deque, defaultdict
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime, timedelta
import logging

_LOGGER = logging.getLogger(__name__)


class IntelligentSensorFusion:
    
    def _percentile(self, data, p):
        """Calculate percentile of data."""
        if not data:
            return 0
        data_sorted = sorted(data)
        n = len(data_sorted)
        k = (n - 1) * p / 100
        f = int(k)
        c = k - f
        if f + 1 < n:
            return data_sorted[f] * (1 - c) + data_sorted[f + 1] * c
        else:
            return data_sorted[f]
    
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
    
    """
    Advanced sensor fusion system with intelligent outlier detection and validation.
    
    Features:
    - IQR-based outlier detection with adaptive thresholds
    - Multi-sensor reliability scoring and confidence weighting
    - Temporal and spatial correlation analysis
    - Automated sensor health monitoring
    - Robust Kalman filtering for noise reduction
    """
    
    def __init__(self, outlier_multiplier: float = 1.5, min_sensors_required: int = 2,
                 history_window: int = 200, confidence_threshold: float = 0.6):
        """
        Initialize intelligent sensor fusion system.
        
        Args:
            outlier_multiplier: IQR multiplier for outlier detection (1.5 standard)
            min_sensors_required: Minimum sensors needed for fusion
            history_window: Size of historical data window
            confidence_threshold: Minimum confidence for sensor readings
        """
        self.outlier_multiplier = outlier_multiplier
        self.min_sensors_required = min_sensors_required
        self.history_window = history_window
        self.confidence_threshold = confidence_threshold
        
        # Sensor data storage - keyed by sensor ID
        self.sensor_data = defaultdict(lambda: deque(maxlen=history_window))
        self.sensor_timestamps = defaultdict(lambda: deque(maxlen=history_window))
        self.sensor_reliability_scores = defaultdict(float)
        self.sensor_health_status = defaultdict(str)
        
        # Fusion results
        self.fused_values = deque(maxlen=history_window)
        self.fusion_timestamps = deque(maxlen=history_window)
        self.fusion_confidence = deque(maxlen=history_window)
        
        # Outlier tracking
        self.outlier_counts = defaultdict(int)
        self.total_readings = defaultdict(int)
        
        # Kalman filter parameters
        self.kalman_state = None
        self.kalman_covariance = 1.0
        self.process_noise = 0.1
        self.measurement_noise = 0.5
        
        _LOGGER.info(f"Intelligent Sensor Fusion initialized: outlier_mult={outlier_multiplier}, "
                    f"min_sensors={min_sensors_required}, history={history_window}")

    def add_sensor_reading(self, sensor_id: str, value: float, timestamp: datetime = None,
                          sensor_type: str = 'vwc') -> Dict:
        """
        Add new sensor reading and perform fusion analysis.
        
        Args:
            sensor_id: Unique identifier for sensor
            value: Sensor reading value
            timestamp: Reading timestamp (default: now)
            sensor_type: Type of sensor ('vwc', 'ec', 'temp', etc.)
            
        Returns:
            Dict with fusion results and sensor health info
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        # Add raw reading
        self.sensor_data[sensor_id].append(value)
        self.sensor_timestamps[sensor_id].append(timestamp)
        self.total_readings[sensor_id] += 1
        
        # Update sensor reliability
        self._update_sensor_reliability(sensor_id)
        
        # Perform outlier detection
        is_outlier = self._detect_outlier(sensor_id, value)
        if is_outlier:
            self.outlier_counts[sensor_id] += 1
            _LOGGER.warning(f"Outlier detected: {sensor_id} = {value}")
        
        # Update sensor health status
        self._update_sensor_health(sensor_id)
        
        # Perform sensor fusion
        fused_result = self._perform_sensor_fusion(sensor_type, timestamp)
        
        return {
            'sensor_id': sensor_id,
            'value': value,
            'is_outlier': is_outlier,
            'sensor_reliability': self.sensor_reliability_scores[sensor_id],
            'sensor_health': self.sensor_health_status[sensor_id],
            'fused_value': fused_result['value'],
            'fusion_confidence': fused_result['confidence'],
            'active_sensors': fused_result['active_sensors'],
            'outlier_rate': self.outlier_counts[sensor_id] / max(self.total_readings[sensor_id], 1)
        }

    def _detect_outlier(self, sensor_id: str, value: float) -> bool:
        """
        Detect outliers using IQR method with adaptive thresholds.
        
        Args:
            sensor_id: Sensor identifier
            value: Current sensor value
            
        Returns:
            True if value is considered an outlier
        """
        sensor_history = list(self.sensor_data[sensor_id])
        
        # Need minimum data for outlier detection
        if len(sensor_history) < 10:
            return False
        
        # Calculate IQR bounds
        q1 = self._percentile(sensor_history, 25)
        q3 = self._percentile(sensor_history, 75)
        iqr_value = q3 - q1
        
        # Adaptive multiplier based on data variability
        data_std = self._std(sensor_history)
        data_mean = self._mean(sensor_history)
        cv = data_std / data_mean if data_mean > 0 else 1.0  # Coefficient of variation
        
        # Adjust multiplier based on data stability
        adaptive_multiplier = self.outlier_multiplier
        if cv < 0.1:  # Very stable data
            adaptive_multiplier *= 0.8  # More sensitive to outliers
        elif cv > 0.3:  # Highly variable data
            adaptive_multiplier *= 1.5  # Less sensitive to outliers
        
        # IQR bounds
        lower_bound = q1 - (adaptive_multiplier * iqr_value)
        upper_bound = q3 + (adaptive_multiplier * iqr_value)
        
        # Additional checks for extreme values
        z_score = abs((value - data_mean) / data_std) if data_std > 0 and len(sensor_history) > 2 else 0
        extreme_outlier = z_score > 3.5  # Very extreme values
        
        # Check temporal consistency (rapid changes)
        temporal_outlier = False
        if len(sensor_history) >= 3:
            recent_values = sensor_history[-3:]
            recent_mean = self._mean(recent_values)
            if abs(value - recent_mean) > (2 * data_std):
                temporal_outlier = True
        
        is_outlier = (value < lower_bound or value > upper_bound) or extreme_outlier or temporal_outlier
        
        # Log detailed outlier analysis
        if is_outlier:
            _LOGGER.debug(f"Outlier Analysis - {sensor_id}: value={value:.2f}, "
                         f"bounds=[{lower_bound:.2f}, {upper_bound:.2f}], "
                         f"z_score={z_score:.2f}, CV={cv:.3f}")
        
        return is_outlier

    def _update_sensor_reliability(self, sensor_id: str):
        """
        Update sensor reliability score based on historical performance.
        
        Args:
            sensor_id: Sensor identifier
        """
        if self.total_readings[sensor_id] < 10:
            self.sensor_reliability_scores[sensor_id] = 0.8  # Default for new sensors
            return
        
        # Calculate reliability factors
        factors = []
        
        # 1. Outlier rate factor (lower outlier rate = higher reliability)
        outlier_rate = self.outlier_counts[sensor_id] / self.total_readings[sensor_id]
        outlier_factor = max(0, 1 - (outlier_rate * 5))  # Penalize high outlier rates
        factors.append(outlier_factor * 0.4)
        
        # 2. Data consistency factor
        sensor_history = list(self.sensor_data[sensor_id])
        if len(sensor_history) >= 20:
            # Calculate rolling standard deviation
            rolling_std = []
            window_size = min(10, len(sensor_history) // 4)
            for i in range(window_size, len(sensor_history)):
                window_data = sensor_history[i-window_size:i]
                rolling_std.append(self._std(window_data))
            
            if rolling_std:
                consistency_factor = max(0, 1 - (self._mean(rolling_std) / self._mean(sensor_history)))
                factors.append(consistency_factor * 0.3)
        
        # 3. Temporal stability factor
        if len(self.sensor_timestamps[sensor_id]) >= 5:
            timestamps = list(self.sensor_timestamps[sensor_id])[-10:]
            time_diffs = [(timestamps[i] - timestamps[i-1]).total_seconds() 
                         for i in range(1, len(timestamps))]
            avg_interval = self._mean(time_diffs)
            interval_std = self._std(time_diffs)
            
            # Stable reading intervals indicate good sensor health
            stability_factor = max(0, 1 - (interval_std / max(avg_interval, 1)))
            factors.append(stability_factor * 0.2)
        
        # 4. Recent performance factor
        recent_readings = min(20, len(sensor_history))
        if recent_readings >= 10:
            recent_data = sensor_history[-recent_readings:]
            recent_outliers = sum(1 for val in recent_data 
                                if self._is_single_value_outlier(val, sensor_history[:-recent_readings]))
            recent_factor = max(0, 1 - (recent_outliers / recent_readings * 3))
            factors.append(recent_factor * 0.1)
        
        # Calculate weighted reliability score
        self.sensor_reliability_scores[sensor_id] = min(sum(factors), 1.0)

    def _is_single_value_outlier(self, value: float, reference_data: List[float]) -> bool:
        """Check if single value is outlier against reference data."""
        if len(reference_data) < 5:
            return False
        
        q1 = self._percentile(reference_data, 25)
        q3 = self._percentile(reference_data, 75)
        iqr_val = q3 - q1
        lower_bound = q1 - (1.5 * iqr_val)
        upper_bound = q3 + (1.5 * iqr_val)
        
        return value < lower_bound or value > upper_bound

    def _update_sensor_health(self, sensor_id: str):
        """Update sensor health status based on multiple factors."""
        reliability = self.sensor_reliability_scores[sensor_id]
        outlier_rate = self.outlier_counts[sensor_id] / max(self.total_readings[sensor_id], 1)
        
        # Check for recent data availability
        if len(self.sensor_timestamps[sensor_id]) > 0:
            last_reading_age = (datetime.now() - self.sensor_timestamps[sensor_id][-1]).total_seconds() / 60
        else:
            last_reading_age = float('inf')
        
        # Determine health status
        if last_reading_age > 30:  # No data for 30+ minutes
            self.sensor_health_status[sensor_id] = 'offline'
        elif reliability < 0.3 or outlier_rate > 0.5:
            self.sensor_health_status[sensor_id] = 'faulty'
        elif reliability < 0.6 or outlier_rate > 0.2:
            self.sensor_health_status[sensor_id] = 'degraded'
        elif reliability > 0.8 and outlier_rate < 0.1:
            self.sensor_health_status[sensor_id] = 'excellent'
        else:
            self.sensor_health_status[sensor_id] = 'good'

    def _perform_sensor_fusion(self, sensor_type: str, timestamp: datetime) -> Dict:
        """
        Perform intelligent sensor fusion with confidence weighting.
        
        Args:
            sensor_type: Type of sensors to fuse
            timestamp: Current timestamp
            
        Returns:
            Dict with fused value and confidence
        """
        # Get all sensors of this type with recent data
        active_sensors = []
        current_time = datetime.now()
        
        for sensor_id in self.sensor_data:
            if (len(self.sensor_data[sensor_id]) > 0 and 
                len(self.sensor_timestamps[sensor_id]) > 0):
                
                last_reading_age = (current_time - self.sensor_timestamps[sensor_id][-1]).total_seconds() / 60
                
                if (last_reading_age <= 10 and  # Recent data (within 10 minutes)
                    self.sensor_health_status[sensor_id] not in ['offline', 'faulty'] and
                    self.sensor_reliability_scores[sensor_id] >= self.confidence_threshold):
                    
                    active_sensors.append({
                        'id': sensor_id,
                        'value': self.sensor_data[sensor_id][-1],
                        'reliability': self.sensor_reliability_scores[sensor_id],
                        'health': self.sensor_health_status[sensor_id]
                    })
        
        if len(active_sensors) < self.min_sensors_required:
            # Fallback to single best sensor if available
            if active_sensors:
                best_sensor = max(active_sensors, key=lambda x: x['reliability'])
                fused_value = best_sensor['value']
                confidence = best_sensor['reliability'] * 0.7  # Reduced confidence for single sensor
            else:
                return {'value': None, 'confidence': 0.0, 'active_sensors': 0}
        else:
            # Weighted fusion based on reliability scores
            fused_value = self._weighted_fusion(active_sensors)
            confidence = self._calculate_fusion_confidence(active_sensors)
        
        # Apply Kalman filtering for smoothing
        if self.kalman_state is not None:
            fused_value = self._apply_kalman_filter(fused_value)
        else:
            self.kalman_state = fused_value
        
        # Store fusion results
        self.fused_values.append(fused_value)
        self.fusion_timestamps.append(timestamp)
        self.fusion_confidence.append(confidence)
        
        return {
            'value': round(fused_value, 2),
            'confidence': round(confidence, 3),
            'active_sensors': len(active_sensors)
        }

    def _weighted_fusion(self, sensors: List[Dict]) -> float:
        """
        Perform weighted fusion of sensor values.
        
        Args:
            sensors: List of sensor data with reliability scores
            
        Returns:
            Weighted average value
        """
        # Calculate weights based on reliability and health
        total_weight = 0
        weighted_sum = 0
        
        for sensor in sensors:
            # Base weight from reliability
            weight = sensor['reliability']
            
            # Boost weight for excellent sensors
            if sensor['health'] == 'excellent':
                weight *= 1.2
            elif sensor['health'] == 'degraded':
                weight *= 0.8
            
            # Apply outlier detection to current values
            if not self._is_current_value_outlier(sensor['id'], sensor['value']):
                weighted_sum += sensor['value'] * weight
                total_weight += weight
        
        if total_weight > 0:
            return weighted_sum / total_weight
        else:
            # Fallback to simple average
            return self._mean([s['value'] for s in sensors])

    def _is_current_value_outlier(self, sensor_id: str, value: float) -> bool:
        """Check if current value is outlier for specific sensor."""
        sensor_history = list(self.sensor_data[sensor_id])[:-1]  # Exclude current value
        return self._is_single_value_outlier(value, sensor_history)

    def _calculate_fusion_confidence(self, sensors: List[Dict]) -> float:
        """
        Calculate confidence in fusion result.
        
        Args:
            sensors: List of active sensors
            
        Returns:
            Confidence score (0-1)
        """
        if not sensors:
            return 0.0
        
        factors = []
        
        # 1. Number of sensors factor
        sensor_count_factor = min(len(sensors) / 4, 1.0)  # Optimal around 4 sensors
        factors.append(sensor_count_factor * 0.3)
        
        # 2. Average reliability factor
        avg_reliability = self._mean([s['reliability'] for s in sensors])
        factors.append(avg_reliability * 0.4)
        
        # 3. Value agreement factor
        values = [s['value'] for s in sensors]
        if len(values) > 1:
            value_std = self._std(values)
            value_mean = self._mean(values)
            cv = value_std / value_mean if value_mean > 0 else 1.0
            agreement_factor = max(0, 1 - (cv * 2))  # Good agreement if CV < 0.5
            factors.append(agreement_factor * 0.2)
        
        # 4. Health status factor
        excellent_count = sum(1 for s in sensors if s['health'] == 'excellent')
        good_count = sum(1 for s in sensors if s['health'] == 'good')
        health_factor = (excellent_count * 1.0 + good_count * 0.8) / len(sensors)
        factors.append(health_factor * 0.1)
        
        return min(sum(factors), 1.0)

    def _apply_kalman_filter(self, measurement: float) -> float:
        """
        Apply Kalman filter for noise reduction.
        
        Args:
            measurement: Current measurement value
            
        Returns:
            Filtered value
        """
        # Prediction step
        predicted_state = self.kalman_state
        predicted_covariance = self.kalman_covariance + self.process_noise
        
        # Update step
        kalman_gain = predicted_covariance / (predicted_covariance + self.measurement_noise)
        self.kalman_state = predicted_state + kalman_gain * (measurement - predicted_state)
        self.kalman_covariance = (1 - kalman_gain) * predicted_covariance
        
        return self.kalman_state

    def get_sensor_health_report(self) -> Dict:
        """Get comprehensive sensor health report."""
        report = {
            'total_sensors': len(self.sensor_data),
            'active_sensors': 0,
            'healthy_sensors': 0,
            'degraded_sensors': 0,
            'faulty_sensors': 0,
            'offline_sensors': 0,
            'sensors': {}
        }
        
        for sensor_id in self.sensor_data:
            health = self.sensor_health_status[sensor_id]
            reliability = self.sensor_reliability_scores[sensor_id]
            outlier_rate = self.outlier_counts[sensor_id] / max(self.total_readings[sensor_id], 1)
            
            # Count by status
            if health == 'offline':
                report['offline_sensors'] += 1
            elif health == 'faulty':
                report['faulty_sensors'] += 1
            elif health == 'degraded':
                report['degraded_sensors'] += 1
            else:
                report['healthy_sensors'] += 1
                if health in ['good', 'excellent']:
                    report['active_sensors'] += 1
            
            # Individual sensor report
            report['sensors'][sensor_id] = {
                'health_status': health,
                'reliability_score': round(reliability, 3),
                'outlier_rate': round(outlier_rate, 3),
                'total_readings': self.total_readings[sensor_id],
                'outlier_count': self.outlier_counts[sensor_id],
                'last_reading': self.sensor_data[sensor_id][-1] if self.sensor_data[sensor_id] else None,
                'last_timestamp': self.sensor_timestamps[sensor_id][-1].isoformat() if self.sensor_timestamps[sensor_id] else None
            }
        
        return report

    def get_fusion_history(self, hours: int = 24) -> Dict:
        """Get fusion history for specified time period."""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        history = {
            'timestamps': [],
            'fused_values': [],
            'confidence_scores': []
        }
        
        for i, timestamp in enumerate(self.fusion_timestamps):
            if timestamp >= cutoff_time:
                history['timestamps'].append(timestamp.isoformat())
                history['fused_values'].append(self.fused_values[i])
                history['confidence_scores'].append(self.fusion_confidence[i])
        
        return history

    def reset_fusion_data(self):
        """Reset all fusion data and statistics."""
        self.sensor_data.clear()
        self.sensor_timestamps.clear()
        self.sensor_reliability_scores.clear()
        self.sensor_health_status.clear()
        self.fused_values.clear()
        self.fusion_timestamps.clear()
        self.fusion_confidence.clear()
        self.outlier_counts.clear()
        self.total_readings.clear()
        self.kalman_state = None
        self.kalman_covariance = 1.0
        
        _LOGGER.info("Sensor Fusion system reset")
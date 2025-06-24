"""
Intelligent Crop Profiles for Advanced Crop Steering
Implements strain-specific growing parameters with adaptive learning
Based on research: Indica/Sativa/Hybrid specific VWC and EC targeting
"""

import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import defaultdict, deque
import statistics

_LOGGER = logging.getLogger(__name__)


class IntelligentCropProfiles:
    """
    Advanced crop profile management with strain-specific optimization.
    
    Features:
    - Pre-configured profiles for major cannabis strains and other crops
    - Adaptive parameter learning based on plant response
    - Growth stage-specific adjustments (seedling, veg, early flower, late flower)
    - Environmental adaptation (temperature, humidity, light intensity)
    - Performance tracking and profile optimization
    - Custom profile creation and modification
    """
    
    def _mean(self, data):
        """Calculate mean of data."""
        if not data:
            return 0
        return sum(data) / len(data)
    
    def __init__(self, profiles_file: str = None):
        """
        Initialize intelligent crop profiles system.
        
        Args:
            profiles_file: Optional path to custom profiles JSON file
        """
        self.current_profile = None
        self.current_growth_stage = 'vegetative'
        self.profile_performance_history = defaultdict(list)
        self.adaptation_learning = defaultdict(lambda: defaultdict(float))
        
        # Load base profiles
        self.base_profiles = self._create_base_profiles()
        
        # Custom profiles from file
        self.custom_profiles = {}
        if profiles_file:
            self._load_custom_profiles(profiles_file)
        
        # Profile adaptation settings
        self.adaptation_rate = 0.1  # How quickly to adapt parameters
        self.min_samples_for_adaptation = 10
        self.performance_window = 50  # Track last 50 irrigation events
        
        _LOGGER.info(f"Intelligent Crop Profiles initialized with {len(self.base_profiles)} base profiles")

    def _create_base_profiles(self) -> Dict[str, Dict]:
        """Create comprehensive base crop profiles based on research."""
        return {
            'Cannabis_Athena': {
                'description': 'Athena Nutrients methodology - high EC, controlled VWC',
                'genetics_type': 'hybrid',
                'flowering_weeks': 9,
                'parameters': {
                    'vegetative': {
                        'vwc_target_min': 50,
                        'vwc_target_max': 70,
                        'dryback_target': 15,  # 10-15% for vegetative growth
                        'ec_baseline': 3.0,
                        'ec_max': 6.0,
                        'shot_frequency': 'high',  # Every 15-30 minutes during photoperiod
                        'substrate_field_capacity': 70,
                        'p1_target_vwc': 65,
                        'p2_vwc_threshold': 60,
                        'p3_emergency_threshold': 45
                    },
                    'early_flower': {
                        'vwc_target_min': 45,
                        'vwc_target_max': 65,
                        'dryback_target': 20,  # Increased stress for generative response
                        'ec_baseline': 4.0,
                        'ec_max': 8.0,
                        'shot_frequency': 'medium',
                        'substrate_field_capacity': 65,
                        'p1_target_vwc': 60,
                        'p2_vwc_threshold': 55,
                        'p3_emergency_threshold': 40
                    },
                    'late_flower': {
                        'vwc_target_min': 40,
                        'vwc_target_max': 60,
                        'dryback_target': 25,  # Maximum generative stress
                        'ec_baseline': 5.0,
                        'ec_max': 9.0,
                        'shot_frequency': 'low',
                        'substrate_field_capacity': 60,
                        'p1_target_vwc': 55,
                        'p2_vwc_threshold': 50,
                        'p3_emergency_threshold': 35
                    }
                },
                'environmental_factors': {
                    'temperature_optimal': [24, 28],  # °C range
                    'humidity_veg': [60, 70],  # % RH
                    'humidity_flower': [45, 55],  # % RH for flower
                    'vpd_target': [0.8, 1.2],  # kPa
                    'light_sensitivity': 'medium'
                },
                'adaptation_sensitivity': {
                    'vwc_adjustment_rate': 0.05,
                    'ec_adjustment_rate': 0.1,
                    'dryback_adjustment_rate': 0.02
                }
            },
            
            'Cannabis_Indica_Dominant': {
                'description': 'Indica-dominant strains - shorter, bushier, higher yields',
                'genetics_type': 'indica',
                'flowering_weeks': 8,
                'parameters': {
                    'vegetative': {
                        'vwc_target_min': 55,  # Slightly higher moisture for indica
                        'vwc_target_max': 75,
                        'dryback_target': 12,  # Less aggressive dryback
                        'ec_baseline': 2.8,
                        'ec_max': 5.5,
                        'shot_frequency': 'high',
                        'substrate_field_capacity': 75,
                        'p1_target_vwc': 70,
                        'p2_vwc_threshold': 65,
                        'p3_emergency_threshold': 50
                    },
                    'early_flower': {
                        'vwc_target_min': 50,
                        'vwc_target_max': 70,
                        'dryback_target': 18,
                        'ec_baseline': 3.5,
                        'ec_max': 7.0,
                        'shot_frequency': 'medium',
                        'substrate_field_capacity': 70,
                        'p1_target_vwc': 65,
                        'p2_vwc_threshold': 60,
                        'p3_emergency_threshold': 45
                    },
                    'late_flower': {
                        'vwc_target_min': 45,
                        'vwc_target_max': 65,
                        'dryback_target': 22,
                        'ec_baseline': 4.0,
                        'ec_max': 8.0,
                        'shot_frequency': 'medium',
                        'substrate_field_capacity': 65,
                        'p1_target_vwc': 60,
                        'p2_vwc_threshold': 55,
                        'p3_emergency_threshold': 40
                    }
                },
                'environmental_factors': {
                    'temperature_optimal': [22, 26],  # Cooler for indica
                    'humidity_veg': [55, 65],
                    'humidity_flower': [40, 50],
                    'vpd_target': [0.7, 1.1],
                    'light_sensitivity': 'low'  # Can handle higher light
                },
                'adaptation_sensitivity': {
                    'vwc_adjustment_rate': 0.03,  # More conservative
                    'ec_adjustment_rate': 0.08,
                    'dryback_adjustment_rate': 0.015
                }
            },
            
            'Cannabis_Sativa_Dominant': {
                'description': 'Sativa-dominant strains - taller, longer flowering, heat tolerant',
                'genetics_type': 'sativa',
                'flowering_weeks': 12,
                'parameters': {
                    'vegetative': {
                        'vwc_target_min': 45,  # Lower moisture for sativa
                        'vwc_target_max': 65,
                        'dryback_target': 18,  # More aggressive dryback
                        'ec_baseline': 3.2,
                        'ec_max': 6.5,
                        'shot_frequency': 'medium',
                        'substrate_field_capacity': 65,
                        'p1_target_vwc': 60,
                        'p2_vwc_threshold': 55,
                        'p3_emergency_threshold': 40
                    },
                    'early_flower': {
                        'vwc_target_min': 40,
                        'vwc_target_max': 60,
                        'dryback_target': 25,
                        'ec_baseline': 4.5,
                        'ec_max': 8.5,
                        'shot_frequency': 'low',
                        'substrate_field_capacity': 60,
                        'p1_target_vwc': 55,
                        'p2_vwc_threshold': 50,
                        'p3_emergency_threshold': 35
                    },
                    'late_flower': {
                        'vwc_target_min': 35,
                        'vwc_target_max': 55,
                        'dryback_target': 30,  # Extreme generative stress
                        'ec_baseline': 5.5,
                        'ec_max': 9.5,
                        'shot_frequency': 'very_low',
                        'substrate_field_capacity': 55,
                        'p1_target_vwc': 50,
                        'p2_vwc_threshold': 45,
                        'p3_emergency_threshold': 30
                    }
                },
                'environmental_factors': {
                    'temperature_optimal': [26, 30],  # Higher temp tolerance
                    'humidity_veg': [50, 60],
                    'humidity_flower': [35, 45],
                    'vpd_target': [1.0, 1.5],
                    'light_sensitivity': 'high'  # Needs more light
                },
                'adaptation_sensitivity': {
                    'vwc_adjustment_rate': 0.08,  # More aggressive
                    'ec_adjustment_rate': 0.12,
                    'dryback_adjustment_rate': 0.03
                }
            },
            
            'Cannabis_Balanced_Hybrid': {
                'description': 'Balanced hybrid strains - 50/50 indica/sativa traits',
                'genetics_type': 'hybrid',
                'flowering_weeks': 9,
                'parameters': {
                    'vegetative': {
                        'vwc_target_min': 50,
                        'vwc_target_max': 70,
                        'dryback_target': 15,
                        'ec_baseline': 3.0,
                        'ec_max': 6.0,
                        'shot_frequency': 'high',
                        'substrate_field_capacity': 70,
                        'p1_target_vwc': 65,
                        'p2_vwc_threshold': 60,
                        'p3_emergency_threshold': 45
                    },
                    'early_flower': {
                        'vwc_target_min': 45,
                        'vwc_target_max': 65,
                        'dryback_target': 20,
                        'ec_baseline': 4.0,
                        'ec_max': 7.5,
                        'shot_frequency': 'medium',
                        'substrate_field_capacity': 65,
                        'p1_target_vwc': 60,
                        'p2_vwc_threshold': 55,
                        'p3_emergency_threshold': 40
                    },
                    'late_flower': {
                        'vwc_target_min': 40,
                        'vwc_target_max': 60,
                        'dryback_target': 25,
                        'ec_baseline': 4.5,
                        'ec_max': 8.5,
                        'shot_frequency': 'medium',
                        'substrate_field_capacity': 60,
                        'p1_target_vwc': 55,
                        'p2_vwc_threshold': 50,
                        'p3_emergency_threshold': 35
                    }
                },
                'environmental_factors': {
                    'temperature_optimal': [24, 28],
                    'humidity_veg': [55, 65],
                    'humidity_flower': [40, 50],
                    'vpd_target': [0.8, 1.3],
                    'light_sensitivity': 'medium'
                },
                'adaptation_sensitivity': {
                    'vwc_adjustment_rate': 0.05,
                    'ec_adjustment_rate': 0.1,
                    'dryback_adjustment_rate': 0.025
                }
            },
            
            'Tomato_Hydroponic': {
                'description': 'Hydroponic tomato cultivation',
                'genetics_type': 'vegetable',
                'flowering_weeks': 16,  # Continuous production
                'parameters': {
                    'vegetative': {
                        'vwc_target_min': 65,
                        'vwc_target_max': 85,
                        'dryback_target': 8,  # Minimal dryback
                        'ec_baseline': 2.0,
                        'ec_max': 3.5,
                        'shot_frequency': 'very_high',
                        'substrate_field_capacity': 85,
                        'p1_target_vwc': 80,
                        'p2_vwc_threshold': 75,
                        'p3_emergency_threshold': 65
                    },
                    'early_flower': {  # Early fruit set
                        'vwc_target_min': 60,
                        'vwc_target_max': 80,
                        'dryback_target': 12,
                        'ec_baseline': 2.5,
                        'ec_max': 4.0,
                        'shot_frequency': 'high',
                        'substrate_field_capacity': 80,
                        'p1_target_vwc': 75,
                        'p2_vwc_threshold': 70,
                        'p3_emergency_threshold': 60
                    },
                    'late_flower': {  # Fruit production
                        'vwc_target_min': 55,
                        'vwc_target_max': 75,
                        'dryback_target': 15,
                        'ec_baseline': 3.0,
                        'ec_max': 4.5,
                        'shot_frequency': 'high',
                        'substrate_field_capacity': 75,
                        'p1_target_vwc': 70,
                        'p2_vwc_threshold': 65,
                        'p3_emergency_threshold': 55
                    }
                },
                'environmental_factors': {
                    'temperature_optimal': [20, 25],
                    'humidity_veg': [70, 80],
                    'humidity_flower': [60, 70],
                    'vpd_target': [0.5, 0.9],
                    'light_sensitivity': 'medium'
                },
                'adaptation_sensitivity': {
                    'vwc_adjustment_rate': 0.02,
                    'ec_adjustment_rate': 0.05,
                    'dryback_adjustment_rate': 0.01
                }
            },
            
            'Lettuce_Leafy_Greens': {
                'description': 'Lettuce and leafy green cultivation',
                'genetics_type': 'leafy_green',
                'flowering_weeks': 6,  # Harvest cycle
                'parameters': {
                    'vegetative': {
                        'vwc_target_min': 70,
                        'vwc_target_max': 90,
                        'dryback_target': 5,  # Minimal stress
                        'ec_baseline': 1.2,
                        'ec_max': 2.0,
                        'shot_frequency': 'very_high',
                        'substrate_field_capacity': 90,
                        'p1_target_vwc': 85,
                        'p2_vwc_threshold': 80,
                        'p3_emergency_threshold': 70
                    },
                    'early_flower': {  # Heading stage
                        'vwc_target_min': 65,
                        'vwc_target_max': 85,
                        'dryback_target': 8,
                        'ec_baseline': 1.5,
                        'ec_max': 2.2,
                        'shot_frequency': 'high',
                        'substrate_field_capacity': 85,
                        'p1_target_vwc': 80,
                        'p2_vwc_threshold': 75,
                        'p3_emergency_threshold': 65
                    },
                    'late_flower': {  # Maturation
                        'vwc_target_min': 60,
                        'vwc_target_max': 80,
                        'dryback_target': 10,
                        'ec_baseline': 1.8,
                        'ec_max': 2.5,
                        'shot_frequency': 'high',
                        'substrate_field_capacity': 80,
                        'p1_target_vwc': 75,
                        'p2_vwc_threshold': 70,
                        'p3_emergency_threshold': 60
                    }
                },
                'environmental_factors': {
                    'temperature_optimal': [18, 22],
                    'humidity_veg': [60, 75],
                    'humidity_flower': [55, 70],
                    'vpd_target': [0.4, 0.8],
                    'light_sensitivity': 'low'
                },
                'adaptation_sensitivity': {
                    'vwc_adjustment_rate': 0.01,
                    'ec_adjustment_rate': 0.03,
                    'dryback_adjustment_rate': 0.005
                }
            }
        }

    def select_profile(self, profile_name: str, growth_stage: str = 'vegetative') -> Dict:
        """
        Select and activate a crop profile.
        
        Args:
            profile_name: Name of profile to activate
            growth_stage: Current growth stage
            
        Returns:
            Dict with profile selection results
        """
        # Check base profiles first
        if profile_name in self.base_profiles:
            self.current_profile = profile_name
            self.current_growth_stage = growth_stage
            
            profile_data = self.base_profiles[profile_name]
            _LOGGER.info(f"Selected profile: {profile_name} ({growth_stage} stage)")
            
            return {
                'status': 'success',
                'profile_name': profile_name,
                'growth_stage': growth_stage,
                'profile_data': profile_data,
                'active_parameters': self.get_current_parameters()
            }
        
        # Check custom profiles
        elif profile_name in self.custom_profiles:
            self.current_profile = profile_name
            self.current_growth_stage = growth_stage
            
            profile_data = self.custom_profiles[profile_name]
            _LOGGER.info(f"Selected custom profile: {profile_name}")
            
            return {
                'status': 'success',
                'profile_name': profile_name,
                'growth_stage': growth_stage,
                'profile_data': profile_data,
                'active_parameters': self.get_current_parameters()
            }
        
        else:
            return {
                'status': 'error',
                'message': f"Profile '{profile_name}' not found",
                'available_profiles': list(self.base_profiles.keys()) + list(self.custom_profiles.keys())
            }

    def get_current_parameters(self) -> Optional[Dict]:
        """Get current active parameters for selected profile and growth stage."""
        if not self.current_profile:
            return None
        
        # Get base parameters
        profile_source = (self.base_profiles if self.current_profile in self.base_profiles 
                         else self.custom_profiles)
        
        if self.current_profile not in profile_source:
            return None
        
        profile = profile_source[self.current_profile]
        stage_params = profile['parameters'].get(self.current_growth_stage, {})
        
        # Apply adaptations if available
        adapted_params = self._apply_adaptations(stage_params.copy())
        
        # Add environmental adjustments
        environmental_params = self._apply_environmental_adjustments(adapted_params, profile)
        
        return environmental_params

    def _apply_adaptations(self, base_params: Dict) -> Dict:
        """Apply learned adaptations to base parameters."""
        if not self.current_profile or self.current_profile not in self.adaptation_learning:
            return base_params
        
        adaptations = self.adaptation_learning[self.current_profile]
        adapted_params = base_params.copy()
        
        # Apply adaptations with safety limits
        for param, adjustment in adaptations.items():
            if param in adapted_params:
                base_value = adapted_params[param]
                
                # Apply bounded adjustment
                if param.endswith('_min'):
                    adapted_params[param] = max(0, base_value + adjustment)
                elif param.endswith('_max'):
                    adapted_params[param] = min(100, base_value + adjustment)
                elif param == 'ec_baseline':
                    adapted_params[param] = max(0.5, min(10.0, base_value + adjustment))
                elif param == 'dryback_target':
                    adapted_params[param] = max(5, min(40, base_value + adjustment))
                else:
                    adapted_params[param] = base_value + adjustment
        
        return adapted_params

    def _apply_environmental_adjustments(self, params: Dict, profile: Dict) -> Dict:
        """Apply environmental adjustments based on current conditions."""
        # This would integrate with environmental sensors
        # For now, return params as-is
        # Future: Adjust based on temperature, humidity, VPD, light intensity
        return params

    def update_performance(self, irrigation_result: Dict, environmental_data: Dict = None) -> Dict:
        """
        Update profile performance based on irrigation results.
        
        Args:
            irrigation_result: Results from irrigation event
            environmental_data: Current environmental conditions
            
        Returns:
            Dict with adaptation updates
        """
        if not self.current_profile:
            return {'status': 'no_active_profile'}
        
        # Store performance data
        performance_entry = {
            'timestamp': datetime.now().isoformat(),
            'growth_stage': self.current_growth_stage,
            'irrigation_efficiency': irrigation_result.get('efficiency', 0.5),
            'vwc_response': irrigation_result.get('vwc_improvement', 0.0),
            'target_achievement': irrigation_result.get('target_achieved', False),
            'water_usage': irrigation_result.get('water_used', 0.0),
            'plant_response_score': irrigation_result.get('plant_response_score', 0.5)
        }
        
        if environmental_data:
            performance_entry['environmental'] = environmental_data
        
        self.profile_performance_history[self.current_profile].append(performance_entry)
        
        # Trigger adaptation learning
        adaptation_result = self._learn_adaptations(performance_entry)
        
        return {
            'status': 'performance_updated',
            'profile': self.current_profile,
            'performance_samples': len(self.profile_performance_history[self.current_profile]),
            'adaptations_applied': adaptation_result
        }

    def _learn_adaptations(self, performance_entry: Dict) -> Dict:
        """Learn parameter adaptations based on performance data."""
        profile_history = self.profile_performance_history[self.current_profile]
        
        if len(profile_history) < self.min_samples_for_adaptation:
            return {'status': 'insufficient_data'}
        
        # Analyze recent performance (last 20 samples)
        recent_performance = profile_history[-20:]
        avg_efficiency = self._mean([p['irrigation_efficiency'] for p in recent_performance])
        avg_response = self._mean([p['vwc_response'] for p in recent_performance])
        target_hit_rate = self._mean([p['target_achievement'] for p in recent_performance])
        
        adaptations = {}
        
        # Adapt VWC targets based on efficiency
        if avg_efficiency < 0.6:  # Poor efficiency
            if avg_response < 5.0:  # Low VWC response
                # Increase VWC targets
                adaptations['vwc_target_min'] = self.adaptation_rate * 2
                adaptations['vwc_target_max'] = self.adaptation_rate * 2
                adaptations['p1_target_vwc'] = self.adaptation_rate * 2
            else:
                # Decrease irrigation frequency
                adaptations['dryback_target'] = self.adaptation_rate * 1
        
        elif avg_efficiency > 0.8:  # Good efficiency
            if target_hit_rate > 0.8:  # Consistently hitting targets
                # Can be more aggressive
                adaptations['dryback_target'] = -self.adaptation_rate * 0.5
        
        # Adapt EC based on plant response
        plant_response_scores = [p['plant_response_score'] for p in recent_performance]
        avg_plant_response = self._mean(plant_response_scores)
        
        if avg_plant_response < 0.4:  # Poor plant response
            # Reduce EC stress
            adaptations['ec_baseline'] = -self.adaptation_rate * 0.2
        elif avg_plant_response > 0.8:  # Excellent response
            # Can increase EC for better yields
            adaptations['ec_baseline'] = self.adaptation_rate * 0.1
        
        # Apply adaptations with momentum
        for param, adjustment in adaptations.items():
            current_adaptation = self.adaptation_learning[self.current_profile].get(param, 0)
            # Use momentum to smooth adaptations
            new_adaptation = current_adaptation * 0.8 + adjustment * 0.2
            self.adaptation_learning[self.current_profile][param] = new_adaptation
        
        _LOGGER.info(f"Profile adaptations updated for {self.current_profile}: {adaptations}")
        
        return {
            'status': 'adaptations_applied',
            'adaptations': adaptations,
            'performance_metrics': {
                'efficiency': avg_efficiency,
                'vwc_response': avg_response,
                'target_hit_rate': target_hit_rate,
                'plant_response': avg_plant_response
            }
        }

    def create_custom_profile(self, profile_name: str, base_profile: str, 
                            modifications: Dict) -> Dict:
        """
        Create a custom profile based on existing profile with modifications.
        
        Args:
            profile_name: Name for new custom profile
            base_profile: Base profile to copy from
            modifications: Parameter modifications to apply
            
        Returns:
            Dict with creation results
        """
        if base_profile not in self.base_profiles:
            return {'status': 'error', 'message': f"Base profile '{base_profile}' not found"}
        
        # Deep copy base profile
        import copy
        new_profile = copy.deepcopy(self.base_profiles[base_profile])
        
        # Apply modifications
        for stage, stage_mods in modifications.get('parameters', {}).items():
            if stage in new_profile['parameters']:
                new_profile['parameters'][stage].update(stage_mods)
        
        # Update environmental factors if provided
        if 'environmental_factors' in modifications:
            new_profile['environmental_factors'].update(modifications['environmental_factors'])
        
        # Update description
        new_profile['description'] = f"Custom profile based on {base_profile}"
        
        # Store custom profile
        self.custom_profiles[profile_name] = new_profile
        
        _LOGGER.info(f"Created custom profile: {profile_name}")
        
        return {
            'status': 'success',
            'profile_name': profile_name,
            'base_profile': base_profile,
            'profile_data': new_profile
        }

    def get_profile_recommendations(self, plant_characteristics: Dict, 
                                  environmental_conditions: Dict) -> List[Dict]:
        """
        Get profile recommendations based on plant and environmental characteristics.
        
        Args:
            plant_characteristics: Plant genetics, growth stage, etc.
            environmental_conditions: Current growing environment
            
        Returns:
            List of recommended profiles with suitability scores
        """
        recommendations = []
        
        genetics = plant_characteristics.get('genetics_type', 'hybrid')
        growth_stage = plant_characteristics.get('growth_stage', 'vegetative')
        environment_temp = environmental_conditions.get('temperature', 25)
        environment_humidity = environmental_conditions.get('humidity', 60)
        
        for profile_name, profile_data in self.base_profiles.items():
            suitability_score = 0.0
            factors = []
            
            # Genetics matching
            profile_genetics = profile_data.get('genetics_type', 'hybrid')
            if genetics == profile_genetics:
                suitability_score += 0.4
                factors.append(f"Perfect genetics match ({genetics})")
            elif genetics in profile_genetics or profile_genetics in genetics:
                suitability_score += 0.2
                factors.append(f"Partial genetics match")
            
            # Environmental suitability
            env_factors = profile_data.get('environmental_factors', {})
            temp_range = env_factors.get('temperature_optimal', [20, 30])
            if temp_range[0] <= environment_temp <= temp_range[1]:
                suitability_score += 0.3
                factors.append("Temperature compatible")
            
            humidity_key = 'humidity_veg' if growth_stage == 'vegetative' else 'humidity_flower'
            humidity_range = env_factors.get(humidity_key, [40, 70])
            if humidity_range[0] <= environment_humidity <= humidity_range[1]:
                suitability_score += 0.2
                factors.append("Humidity compatible")
            
            # Performance history bonus
            if profile_name in self.profile_performance_history:
                history = self.profile_performance_history[profile_name]
                if len(history) >= 10:
                    avg_performance = self._mean([h['irrigation_efficiency'] for h in history[-10:]])
                    suitability_score += avg_performance * 0.1
                    factors.append(f"Proven performance ({avg_performance:.2f})")
            
            recommendations.append({
                'profile_name': profile_name,
                'suitability_score': round(suitability_score, 3),
                'match_factors': factors,
                'description': profile_data['description']
            })
        
        # Sort by suitability score
        recommendations.sort(key=lambda x: x['suitability_score'], reverse=True)
        
        return recommendations[:5]  # Top 5 recommendations

    def export_profile_data(self) -> Dict:
        """Export all profile data for backup/analysis."""
        return {
            'base_profiles': self.base_profiles,
            'custom_profiles': self.custom_profiles,
            'current_profile': self.current_profile,
            'current_growth_stage': self.current_growth_stage,
            'performance_history': dict(self.profile_performance_history),
            'adaptations': dict(self.adaptation_learning),
            'export_timestamp': datetime.now().isoformat()
        }

    def import_profile_data(self, data: Dict) -> Dict:
        """Import profile data from backup."""
        try:
            if 'custom_profiles' in data:
                self.custom_profiles.update(data['custom_profiles'])
            
            if 'performance_history' in data:
                for profile, history in data['performance_history'].items():
                    self.profile_performance_history[profile].extend(history)
            
            if 'adaptations' in data:
                for profile, adaptations in data['adaptations'].items():
                    self.adaptation_learning[profile].update(adaptations)
            
            return {'status': 'success', 'imported_profiles': len(data.get('custom_profiles', {}))}
            
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def get_available_profiles(self) -> Dict:
        """Get list of all available profiles with descriptions."""
        profiles = {}
        
        # Base profiles
        for name, data in self.base_profiles.items():
            profiles[name] = {
                'type': 'base',
                'description': data['description'],
                'genetics_type': data['genetics_type'],
                'flowering_weeks': data['flowering_weeks']
            }
        
        # Custom profiles
        for name, data in self.custom_profiles.items():
            profiles[name] = {
                'type': 'custom',
                'description': data['description'],
                'genetics_type': data.get('genetics_type', 'unknown'),
                'flowering_weeks': data.get('flowering_weeks', 0)
            }
        
        return profiles

    def _load_custom_profiles(self, profiles_file: str):
        """Load custom profiles from JSON file."""
        try:
            with open(profiles_file, 'r') as f:
                custom_data = json.load(f)
            self.custom_profiles = custom_data.get('custom_profiles', {})
            _LOGGER.info(f"Loaded {len(self.custom_profiles)} custom profiles")
        except Exception as e:
            _LOGGER.warning(f"Could not load custom profiles: {e}")

    def save_custom_profiles(self, profiles_file: str) -> Dict:
        """Save custom profiles to JSON file."""
        try:
            data = {
                'custom_profiles': self.custom_profiles,
                'saved_timestamp': datetime.now().isoformat()
            }
            with open(profiles_file, 'w') as f:
                json.dump(data, f, indent=2)
            return {'status': 'success', 'profiles_saved': len(self.custom_profiles)}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
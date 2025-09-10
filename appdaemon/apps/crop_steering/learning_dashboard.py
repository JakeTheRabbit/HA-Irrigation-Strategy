"""
Learning Dashboard Helper
========================
Home Assistant service and entity helpers for the Smart Irrigation Learning System.
Provides dashboard entities and services for monitoring and controlling the learning system.

Author: Smart Irrigation Learning Dashboard v1.0
"""

import appdaemon.plugins.hass.hassapi as hass
import json
from datetime import datetime, timedelta
from smart_irrigation_learning import SmartIrrigationLearning


class LearningDashboard(hass.Hass):
    """Dashboard helper for smart irrigation learning system."""
    
    def initialize(self):
        """Initialize dashboard helper."""
        self.learning_system = None
        
        # Register services
        self.register_service("crop_steering/detect_field_capacity", self.service_detect_field_capacity)
        self.register_service("crop_steering/characterize_zone_efficiency", self.service_characterize_efficiency)
        self.register_service("crop_steering/get_zone_intelligence", self.service_get_zone_intelligence)
        self.register_service("crop_steering/calculate_optimal_shot", self.service_calculate_optimal_shot)
        
        # Create dashboard entities
        self.create_dashboard_entities()
        
        # Update dashboard every minute
        self.run_every(self.update_dashboard, 60)
        
        self.log("Learning Dashboard initialized")
    
    def get_learning_system(self):
        """Get reference to learning system."""
        if self.learning_system is None:
            # Find the learning system app
            for app_name in self.list_apps():
                app = self.get_app(app_name)
                if isinstance(app, SmartIrrigationLearning):
                    self.learning_system = app
                    break
        return self.learning_system
    
    def create_dashboard_entities(self):
        """Create Home Assistant entities for the learning dashboard."""
        # Zone learning status sensors
        for zone_id in range(1, 7):
            self.set_state(
                f"sensor.crop_steering_zone_{zone_id}_learning_status",
                "unknown",
                attributes={
                    "friendly_name": f"Zone {zone_id} Learning Status",
                    "icon": "mdi:brain",
                    "device_class": None
                }
            )
            
            self.set_state(
                f"sensor.crop_steering_zone_{zone_id}_field_capacity",
                "unknown",
                attributes={
                    "friendly_name": f"Zone {zone_id} Field Capacity",
                    "unit_of_measurement": "%",
                    "icon": "mdi:water-percent",
                    "device_class": "humidity"
                }
            )
            
            self.set_state(
                f"sensor.crop_steering_zone_{zone_id}_avg_efficiency",
                "unknown",
                attributes={
                    "friendly_name": f"Zone {zone_id} Avg Efficiency",
                    "unit_of_measurement": "%",
                    "icon": "mdi:gauge",
                    "device_class": None
                }
            )
            
            self.set_state(
                f"sensor.crop_steering_zone_{zone_id}_recommendation",
                "unknown",
                attributes={
                    "friendly_name": f"Zone {zone_id} Recommendation",
                    "icon": "mdi:lightbulb",
                    "device_class": None
                }
            )
        
        # System-wide learning entities
        self.set_state(
            "sensor.crop_steering_learning_progress",
            "0",
            attributes={
                "friendly_name": "Learning System Progress",
                "unit_of_measurement": "%",
                "icon": "mdi:progress-check",
                "zones_learned": 0,
                "total_zones": 6
            }
        )
        
        self.set_state(
            "sensor.crop_steering_total_irrigations_logged",
            "0",
            attributes={
                "friendly_name": "Total Irrigations Logged",
                "icon": "mdi:water-pump",
                "device_class": None
            }
        )
    
    def update_dashboard(self, kwargs):
        """Update dashboard entities with current learning data."""
        learning_system = self.get_learning_system()
        if not learning_system:
            return
        
        zones_learned = 0
        total_irrigations = 0
        
        # Update zone-specific entities
        for zone_id in range(1, 7):
            try:
                # Get zone intelligence summary
                summary = learning_system.get_zone_intelligence_summary(zone_id)
                
                # Update learning status
                status = summary.get('learning_status', 'unknown')
                self.set_state(
                    f"sensor.crop_steering_zone_{zone_id}_learning_status",
                    status,
                    attributes={
                        "friendly_name": f"Zone {zone_id} Learning Status",
                        "icon": "mdi:brain" if status == "learned" else "mdi:brain-outline",
                        "last_updated": summary.get('last_updated', 'never')
                    }
                )
                
                # Update field capacity
                fc = summary.get('field_capacity')
                if fc:
                    zones_learned += 1
                    self.set_state(
                        f"sensor.crop_steering_zone_{zone_id}_field_capacity",
                        round(fc, 1),
                        attributes={
                            "friendly_name": f"Zone {zone_id} Field Capacity",
                            "unit_of_measurement": "%",
                            "icon": "mdi:water-percent",
                            "device_class": "humidity"
                        }
                    )
                
                # Update efficiency
                recent_perf = summary.get('recent_performance', {})
                avg_eff = recent_perf.get('average_efficiency')
                if avg_eff is not None:
                    self.set_state(
                        f"sensor.crop_steering_zone_{zone_id}_avg_efficiency",
                        round(avg_eff * 100, 1),
                        attributes={
                            "friendly_name": f"Zone {zone_id} Avg Efficiency",
                            "unit_of_measurement": "%",
                            "icon": "mdi:gauge",
                            "irrigation_count": recent_perf.get('irrigation_count', 0),
                            "efficiency_stdev": round(recent_perf.get('efficiency_stdev', 0) * 100, 1)
                        }
                    )
                    
                    total_irrigations += recent_perf.get('irrigation_count', 0)
                
                # Update recommendation
                recommendation = summary.get('recommended_action', 'No recommendation')
                self.set_state(
                    f"sensor.crop_steering_zone_{zone_id}_recommendation",
                    recommendation,
                    attributes={
                        "friendly_name": f"Zone {zone_id} Recommendation",
                        "icon": "mdi:lightbulb",
                        "channeling_analysis": recent_perf.get('channeling_analysis', 'No analysis')
                    }
                )
                
            except Exception as e:
                self.log(f"Error updating zone {zone_id} dashboard: {e}")
        
        # Update system progress
        progress = round((zones_learned / 6) * 100)
        self.set_state(
            "sensor.crop_steering_learning_progress",
            progress,
            attributes={
                "friendly_name": "Learning System Progress",
                "unit_of_measurement": "%",
                "icon": "mdi:progress-check",
                "zones_learned": zones_learned,
                "total_zones": 6
            }
        )
        
        self.set_state(
            "sensor.crop_steering_total_irrigations_logged",
            total_irrigations,
            attributes={
                "friendly_name": "Total Irrigations Logged",
                "icon": "mdi:water-pump"
            }
        )
    
    # Service handlers
    def service_detect_field_capacity(self, entity, attribute, old, new, kwargs):
        """Service to detect field capacity for a zone."""
        zone_id = kwargs.get('zone_id')
        if not zone_id:
            self.log("Error: zone_id required for field capacity detection")
            return
        
        learning_system = self.get_learning_system()
        if not learning_system:
            self.log("Error: Learning system not available")
            return
        
        self.log(f"Starting field capacity detection for zone {zone_id}")
        
        # Run in background to avoid blocking
        self.run_in(lambda kwargs: learning_system.detect_field_capacity(zone_id), 1)
        
        # Fire event to notify user
        self.fire_event("crop_steering_learning_started", {
            "type": "field_capacity_detection",
            "zone_id": zone_id,
            "estimated_duration": "10-30 minutes"
        })
    
    def service_characterize_efficiency(self, entity, attribute, old, new, kwargs):
        """Service to characterize zone efficiency curve."""
        zone_id = kwargs.get('zone_id')
        if not zone_id:
            self.log("Error: zone_id required for efficiency characterization")
            return
        
        learning_system = self.get_learning_system()
        if not learning_system:
            self.log("Error: Learning system not available")
            return
        
        self.log(f"Starting efficiency characterization for zone {zone_id}")
        
        # Run in background
        self.run_in(lambda kwargs: learning_system.characterize_zone_efficiency(zone_id), 1)
        
        self.fire_event("crop_steering_learning_started", {
            "type": "efficiency_characterization",
            "zone_id": zone_id,
            "estimated_duration": "2-4 hours"
        })
    
    def service_get_zone_intelligence(self, entity, attribute, old, new, kwargs):
        """Service to get zone intelligence summary."""
        zone_id = kwargs.get('zone_id')
        if not zone_id:
            self.log("Error: zone_id required")
            return {}
        
        learning_system = self.get_learning_system()
        if not learning_system:
            self.log("Error: Learning system not available")
            return {}
        
        try:
            summary = learning_system.get_zone_intelligence_summary(zone_id)
            
            # Fire event with results
            self.fire_event("crop_steering_zone_intelligence", {
                "zone_id": zone_id,
                "summary": summary
            })
            
            return summary
            
        except Exception as e:
            self.log(f"Error getting zone intelligence: {e}")
            return {}
    
    def service_calculate_optimal_shot(self, entity, attribute, old, new, kwargs):
        """Service to calculate optimal shot size for current conditions."""
        zone_id = kwargs.get('zone_id')
        target_increase = kwargs.get('target_vwc_increase', 5.0)
        
        if not zone_id:
            self.log("Error: zone_id required")
            return
        
        learning_system = self.get_learning_system()
        if not learning_system:
            self.log("Error: Learning system not available")
            return
        
        try:
            current_vwc = learning_system.get_zone_vwc(zone_id)
            if current_vwc is None:
                self.log(f"Error: Cannot get VWC reading for zone {zone_id}")
                return
            
            optimal_duration = learning_system.calculate_optimal_shot_size(
                zone_id, current_vwc, target_increase
            )
            
            result = {
                "zone_id": zone_id,
                "current_vwc": current_vwc,
                "target_increase": target_increase,
                "optimal_duration_seconds": optimal_duration,
                "estimated_water_delivery": learning_system.calculate_water_delivered(zone_id, optimal_duration)
            }
            
            # Fire event with results
            self.fire_event("crop_steering_optimal_shot_calculated", result)
            
            self.log(f"Zone {zone_id}: Optimal shot = {optimal_duration}s for +{target_increase}% VWC")
            
        except Exception as e:
            self.log(f"Error calculating optimal shot: {e}")
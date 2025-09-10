"""LLM-Enhanced Crop Steering AppDaemon App.

Integrates LLM decision making with the existing AppDaemon automation system
for enhanced irrigation intelligence while maintaining safety-first approach.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import appdaemon.plugins.hass.hassapi as hass

# Import Home Assistant integration components
# Note: This assumes the HA integration is installed and available
try:
    from custom_components.crop_steering.llm.decision_engine import LLMDecisionEngine
    from custom_components.crop_steering.llm.client import LLMConfig, LLMProvider
    from custom_components.crop_steering.llm.cost_optimizer import BudgetConfig, CostTier
    LLM_AVAILABLE = True
except ImportError as e:
    # LLM components not available - will use rule-based fallback only
    logging.warning("LLM components not available: %s", e)
    LLM_AVAILABLE = False

_LOGGER = logging.getLogger(__name__)


class LLMEnhancedCropSteering(hass.Hass):
    """LLM-enhanced crop steering automation for AppDaemon."""
    
    def initialize(self):
        """Initialize the LLM-enhanced automation."""
        try:
            self.log("Initializing LLM-Enhanced Crop Steering App")
            
            # Load configuration
            self._load_configuration()
            
            # Initialize LLM components if available
            if LLM_AVAILABLE and self.args.get("enable_llm", False):
                self._initialize_llm_components()
            else:
                self.log("LLM components disabled or unavailable - using rule-based only")
                self._llm_enabled = False
            
            # Set up event listeners
            self._setup_event_listeners()
            
            # Schedule periodic LLM health checks
            if self._llm_enabled:
                self.run_every(
                    self._llm_health_check,
                    "now+300",  # Start in 5 minutes
                    600  # Every 10 minutes
                )
            
            self.log("LLM-Enhanced Crop Steering App initialized successfully")
            
        except Exception as e:
            self.log(f"Failed to initialize LLM-Enhanced Crop Steering: {e}", level="ERROR")
            self._llm_enabled = False
    
    def _load_configuration(self):
        """Load configuration from AppDaemon args."""
        # Basic configuration
        self._zones = self.args.get("zones", [])
        self._enable_llm = self.args.get("enable_llm", False)
        
        # LLM Configuration
        llm_config = self.args.get("llm_config", {})
        self._llm_provider = LLMProvider(llm_config.get("provider", "openai"))
        self._llm_model = llm_config.get("model", "gpt-5-nano")
        self._llm_api_key = llm_config.get("api_key", "")
        
        # Budget Configuration
        budget_config = self.args.get("budget_config", {})
        self._daily_budget = budget_config.get("daily_limit", 5.0)
        self._cost_tier = CostTier(budget_config.get("cost_tier", "standard"))
        
        # Decision thresholds
        self._llm_confidence_threshold = self.args.get("llm_confidence_threshold", 70.0)
        self._enable_llm_phase_transitions = self.args.get("enable_llm_phase_transitions", True)
        
        # Performance tracking
        self._decision_history = []
        self._performance_stats = {
            "total_decisions": 0,
            "llm_decisions": 0,
            "rule_decisions": 0,
            "total_cost": 0.0
        }
    
    def _initialize_llm_components(self):
        """Initialize LLM decision engine and related components."""
        try:
            if not self._llm_api_key:
                self.log("LLM API key not configured - disabling LLM features", level="WARNING")
                self._llm_enabled = False
                return
            
            # Create LLM configuration
            llm_config = LLMConfig(
                provider=self._llm_provider,
                api_key=self._llm_api_key,
                model=self._llm_model,
                timeout=30,
                max_retries=3
            )
            
            # Create budget configuration
            budget_config = BudgetConfig(
                daily_limit=self._daily_budget,
                cost_tier=self._cost_tier,
                enable_alerts=True
            )
            
            # Initialize decision engine
            self._llm_engine = LLMDecisionEngine(
                self.get_plugin_api("hass"),  # Get Home Assistant API
                llm_config,
                budget_config
            )
            
            # Initialize engine asynchronously
            asyncio.create_task(self._llm_engine.initialize())
            
            self._llm_enabled = True
            self.log(f"LLM Decision Engine initialized with {self._llm_provider.value} ({self._llm_model})")
            
        except Exception as e:
            self.log(f"Failed to initialize LLM components: {e}", level="ERROR")
            self._llm_enabled = False
    
    def _setup_event_listeners(self):
        """Set up event listeners for crop steering events."""
        # Listen for irrigation decision requests
        self.listen_event(
            self._handle_irrigation_decision_request,
            "crop_steering_irrigation_decision_request"
        )
        
        # Listen for phase transition requests
        self.listen_event(
            self._handle_phase_transition_request,
            "crop_steering_phase_transition_request"
        )
        
        # Listen for LLM configuration updates
        self.listen_event(
            self._handle_llm_config_update,
            "crop_steering_llm_config_update"
        )
    
    def _handle_irrigation_decision_request(self, event_name, data, kwargs):
        """Handle irrigation decision request event."""
        asyncio.create_task(self._process_irrigation_decision(data))
    
    async def _process_irrigation_decision(self, event_data: Dict[str, Any]):
        """Process irrigation decision with LLM enhancement."""
        try:
            zone_id = event_data.get("zone_id")
            if not zone_id:
                self.log("No zone_id in irrigation decision request", level="ERROR")
                return
            
            self.log(f"Processing irrigation decision for zone {zone_id}")
            
            # Gather sensor data
            sensor_data = await self._gather_sensor_data(zone_id)
            system_config = await self._gather_system_config(zone_id)
            current_phase = await self._get_current_phase(zone_id)
            
            # Get decision
            if self._llm_enabled:
                decision = await self._get_llm_enhanced_decision(
                    zone_id, current_phase, sensor_data, system_config
                )
            else:
                decision = self._get_rule_based_decision(
                    zone_id, current_phase, sensor_data, system_config
                )
            
            # Execute decision
            await self._execute_irrigation_decision(zone_id, decision)
            
            # Update statistics
            self._update_decision_stats(decision)
            
            # Fire response event
            self.fire_event("crop_steering_irrigation_decision_response", {
                "zone_id": zone_id,
                "decision": decision.decision,
                "confidence": decision.confidence,
                "reasoning": decision.reasoning,
                "llm_enhanced": self._llm_enabled,
                "timestamp": datetime.now().isoformat()
            })
            
        except Exception as e:
            self.log(f"Error processing irrigation decision: {e}", level="ERROR")
    
    async def _get_llm_enhanced_decision(
        self,
        zone_id: int,
        current_phase: str,
        sensor_data: Dict[str, Any],
        system_config: Dict[str, Any]
    ):
        """Get LLM-enhanced irrigation decision."""
        try:
            # Gather historical data for context
            historical_data = await self._gather_historical_data(zone_id)
            
            # Check for emergency conditions
            emergency = self._check_emergency_conditions(sensor_data)
            
            # Get LLM decision
            decision = await self._llm_engine.make_irrigation_decision(
                zone_id=zone_id,
                current_phase=current_phase,
                sensor_data=sensor_data,
                system_config=system_config,
                historical_data=historical_data,
                emergency=emergency
            )
            
            self.log(f"LLM decision for zone {zone_id}: {decision.decision} (confidence: {decision.confidence}%)")
            
            return decision
            
        except Exception as e:
            self.log(f"LLM decision failed for zone {zone_id}, falling back to rules: {e}", level="WARNING")
            return self._get_rule_based_decision(zone_id, current_phase, sensor_data, system_config)
    
    def _get_rule_based_decision(
        self,
        zone_id: int,
        current_phase: str,
        sensor_data: Dict[str, Any],
        system_config: Dict[str, Any]
    ):
        """Get rule-based irrigation decision (fallback)."""
        # Import decision class for rule-based fallback
        if LLM_AVAILABLE:
            from custom_components.crop_steering.llm.decision_engine import LLMDecision
        else:
            # Create minimal decision structure if LLM not available
            class LLMDecision:
                def __init__(self, decision, confidence, reasoning, **kwargs):
                    self.decision = decision
                    self.confidence = confidence
                    self.reasoning = reasoning
                    for k, v in kwargs.items():
                        setattr(self, k, v)
        
        # Simple rule-based logic
        vwc_avg = (sensor_data.get("vwc_front", 0) + sensor_data.get("vwc_back", 0)) / 2
        vwc_threshold = system_config.get("vwc_threshold", 60)
        
        if vwc_avg < vwc_threshold:
            return LLMDecision(
                decision="irrigate",
                confidence=80,
                reasoning=f"Rule-based: VWC {vwc_avg:.1f}% below threshold {vwc_threshold}%",
                shot_size_ml=system_config.get("default_shot_size_ml", 100),
                urgency="medium",
                next_check_minutes=15
            )
        else:
            return LLMDecision(
                decision="wait",
                confidence=75,
                reasoning=f"Rule-based: VWC {vwc_avg:.1f}% above threshold {vwc_threshold}%",
                urgency="low",
                next_check_minutes=30
            )
    
    async def _gather_sensor_data(self, zone_id: int) -> Dict[str, Any]:
        """Gather current sensor data for the zone."""
        try:
            # Get sensor entity IDs
            vwc_front_entity = f"sensor.crop_steering_zone_{zone_id}_vwc_front"
            vwc_back_entity = f"sensor.crop_steering_zone_{zone_id}_vwc_back"
            ec_front_entity = f"sensor.crop_steering_zone_{zone_id}_ec_front"
            ec_back_entity = f"sensor.crop_steering_zone_{zone_id}_ec_back"
            temp_entity = f"sensor.crop_steering_zone_{zone_id}_temperature"
            humidity_entity = f"sensor.crop_steering_zone_{zone_id}_humidity"
            
            # Gather sensor values
            sensor_data = {
                "vwc_front": float(self.get_state(vwc_front_entity) or 0),
                "vwc_back": float(self.get_state(vwc_back_entity) or 0),
                "ec_front": float(self.get_state(ec_front_entity) or 0),
                "ec_back": float(self.get_state(ec_back_entity) or 0),
                "temperature": float(self.get_state(temp_entity) or 20),
                "humidity": float(self.get_state(humidity_entity) or 60),
                "timestamp": datetime.now().isoformat()
            }
            
            # Calculate derived values
            sensor_data["vwc_avg"] = (sensor_data["vwc_front"] + sensor_data["vwc_back"]) / 2
            sensor_data["ec_avg"] = (sensor_data["ec_front"] + sensor_data["ec_back"]) / 2
            
            return sensor_data
            
        except Exception as e:
            self.log(f"Error gathering sensor data for zone {zone_id}: {e}", level="ERROR")
            return {}
    
    async def _gather_system_config(self, zone_id: int) -> Dict[str, Any]:
        """Gather system configuration for the zone."""
        try:
            # Get configuration entity IDs
            target_vwc_entity = f"number.crop_steering_zone_{zone_id}_target_vwc"
            target_ec_entity = f"number.crop_steering_zone_{zone_id}_target_ec"
            vwc_threshold_entity = f"number.crop_steering_zone_{zone_id}_vwc_threshold"
            shot_size_entity = f"number.crop_steering_zone_{zone_id}_shot_size"
            
            config = {
                "target_vwc": float(self.get_state(target_vwc_entity) or 65),
                "target_ec": float(self.get_state(target_ec_entity) or 2.5),
                "vwc_threshold": float(self.get_state(vwc_threshold_entity) or 60),
                "default_shot_size_ml": int(float(self.get_state(shot_size_entity) or 100)),
                "max_shot_size_ml": 200,
                "min_shot_size_ml": 10
            }
            
            return config
            
        except Exception as e:
            self.log(f"Error gathering system config for zone {zone_id}: {e}", level="ERROR")
            return {}
    
    async def _get_current_phase(self, zone_id: int) -> str:
        """Get current irrigation phase for the zone."""
        try:
            phase_entity = f"select.crop_steering_zone_{zone_id}_current_phase"
            return self.get_state(phase_entity) or "P2"
        except:
            return "P2"  # Default to maintenance phase
    
    async def _gather_historical_data(self, zone_id: int) -> Dict[str, Any]:
        """Gather historical data for LLM context."""
        try:
            # This would typically query a database or historical storage
            # For now, return basic historical context
            return {
                "summary": "Historical data collection in development",
                "recent_irrigation_count": 3,
                "avg_daily_water_usage": 1200,
                "performance_trend": "stable"
            }
        except:
            return {}
    
    def _check_emergency_conditions(self, sensor_data: Dict[str, Any]) -> bool:
        """Check if current conditions constitute an emergency."""
        vwc_avg = sensor_data.get("vwc_avg", 0)
        ec_avg = sensor_data.get("ec_avg", 0)
        
        # Emergency conditions
        if vwc_avg < 40 or vwc_avg > 80 or ec_avg > 5.0:
            return True
        
        return False
    
    async def _execute_irrigation_decision(self, zone_id: int, decision):
        """Execute the irrigation decision."""
        try:
            if decision.decision == "irrigate":
                # Call irrigation service
                await self.call_service(
                    "crop_steering/execute_irrigation_shot",
                    zone_id=zone_id,
                    shot_size_ml=decision.shot_size_ml or 100,
                    reasoning=decision.reasoning
                )
                self.log(f"Executed irrigation for zone {zone_id}: {decision.shot_size_ml}mL")
                
            elif decision.decision == "phase_change":
                # Call phase transition service
                next_phase = decision.parameters.get("next_phase", "P2")
                await self.call_service(
                    "crop_steering/transition_phase",
                    zone_id=zone_id,
                    target_phase=next_phase,
                    reasoning=decision.reasoning
                )
                self.log(f"Executed phase transition for zone {zone_id} to {next_phase}")
            
            # Log warnings if any
            if hasattr(decision, 'warnings') and decision.warnings:
                for warning in decision.warnings:
                    self.log(f"Zone {zone_id} warning: {warning}", level="WARNING")
                    
        except Exception as e:
            self.log(f"Error executing decision for zone {zone_id}: {e}", level="ERROR")
    
    def _update_decision_stats(self, decision):
        """Update decision statistics."""
        self._performance_stats["total_decisions"] += 1
        
        if hasattr(decision, "llm_metadata") and decision.llm_metadata:
            self._performance_stats["llm_decisions"] += 1
            if "cost" in decision.llm_metadata:
                self._performance_stats["total_cost"] += decision.llm_metadata["cost"]
        else:
            self._performance_stats["rule_decisions"] += 1
    
    def _handle_phase_transition_request(self, event_name, data, kwargs):
        """Handle phase transition request event."""
        if self._enable_llm_phase_transitions and self._llm_enabled:
            asyncio.create_task(self._process_llm_phase_transition(data))
        else:
            self.log("LLM phase transitions disabled - using rule-based logic")
    
    async def _process_llm_phase_transition(self, event_data: Dict[str, Any]):
        """Process phase transition with LLM analysis."""
        try:
            zone_id = event_data.get("zone_id")
            if not zone_id:
                return
            
            sensor_data = await self._gather_sensor_data(zone_id)
            system_config = await self._gather_system_config(zone_id)
            current_phase = await self._get_current_phase(zone_id)
            
            decision = await self._llm_engine.analyze_phase_transition(
                zone_id=zone_id,
                current_phase=current_phase,
                sensor_data=sensor_data,
                system_config=system_config
            )
            
            if decision.decision == "phase_change":
                await self._execute_irrigation_decision(zone_id, decision)
            
            # Fire response event
            self.fire_event("crop_steering_phase_transition_response", {
                "zone_id": zone_id,
                "decision": decision.decision,
                "current_phase": current_phase,
                "reasoning": decision.reasoning,
                "timestamp": datetime.now().isoformat()
            })
            
        except Exception as e:
            self.log(f"Error processing LLM phase transition: {e}", level="ERROR")
    
    def _handle_llm_config_update(self, event_name, data, kwargs):
        """Handle LLM configuration update event."""
        try:
            # Update configuration
            if "daily_budget" in data:
                self._daily_budget = data["daily_budget"]
            if "cost_tier" in data:
                self._cost_tier = CostTier(data["cost_tier"])
            if "confidence_threshold" in data:
                self._llm_confidence_threshold = data["confidence_threshold"]
            
            self.log(f"Updated LLM configuration: {data}")
            
        except Exception as e:
            self.log(f"Error updating LLM configuration: {e}", level="ERROR")
    
    def _llm_health_check(self, kwargs):
        """Periodic health check for LLM components."""
        try:
            if not self._llm_enabled:
                return
            
            # Check LLM engine status
            if hasattr(self, "_llm_engine"):
                status = self._llm_engine.get_system_status()
                self.log(f"LLM system status: {status['llm_client_status']}")
                
                # Check if error rate is too high
                error_rate = status.get("performance_metrics", {}).get("error_rate", 0)
                if error_rate > 0.1:  # More than 10% error rate
                    self.log(f"High LLM error rate detected: {error_rate:.2%}", level="WARNING")
            
            # Log performance statistics
            if self._performance_stats["total_decisions"] > 0:
                llm_usage_rate = (
                    self._performance_stats["llm_decisions"] / 
                    self._performance_stats["total_decisions"]
                )
                self.log(f"LLM usage rate: {llm_usage_rate:.1%}, Total cost: ${self._performance_stats['total_cost']:.4f}")
            
        except Exception as e:
            self.log(f"LLM health check failed: {e}", level="ERROR")
    
    # Service handlers for manual control
    def handle_get_llm_status(self, **kwargs):
        """Service handler to get LLM system status."""
        if self._llm_enabled and hasattr(self, "_llm_engine"):
            status = self._llm_engine.get_system_status()
            status["performance_stats"] = self._performance_stats
            return status
        else:
            return {"status": "disabled", "reason": "LLM components not available"}
    
    def handle_generate_usage_report(self, **kwargs):
        """Service handler to generate usage report."""
        days = kwargs.get("days", 7)
        if self._llm_enabled and hasattr(self, "_llm_engine"):
            return asyncio.create_task(self._llm_engine.get_usage_report(days))
        else:
            return {"error": "LLM components not available"}
    
    def handle_update_safety_thresholds(self, **kwargs):
        """Service handler to update safety thresholds."""
        if self._llm_enabled and hasattr(self, "_llm_engine"):
            thresholds = kwargs.get("thresholds", {})
            self._llm_engine.update_safety_thresholds(thresholds)
            return {"status": "updated", "thresholds": thresholds}
        else:
            return {"error": "LLM components not available"}
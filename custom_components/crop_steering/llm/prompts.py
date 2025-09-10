"""Prompt engineering and template management for LLM irrigation decisions.

Provides specialized prompts for irrigation decision making, troubleshooting,
optimization, and system analysis with templating and context injection.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Union

_LOGGER = logging.getLogger(__name__)


class PromptType(Enum):
    """Types of prompts for different operations."""
    IRRIGATION_DECISION = "irrigation_decision"
    PHASE_TRANSITION = "phase_transition"
    TROUBLESHOOTING = "troubleshooting"
    OPTIMIZATION = "optimization"
    EMERGENCY_ANALYSIS = "emergency_analysis"
    SENSOR_VALIDATION = "sensor_validation"
    GROWTH_ANALYSIS = "growth_analysis"


class PromptComplexity(Enum):
    """Complexity levels for cost optimization."""
    SIMPLE = "simple"       # Basic decisions, low token usage
    STANDARD = "standard"   # Normal complexity
    DETAILED = "detailed"   # Comprehensive analysis
    EXPERT = "expert"       # Full expert-level analysis


@dataclass
class PromptContext:
    """Context data for prompt generation."""
    zone_id: int
    current_phase: str
    sensor_data: Dict[str, Any]
    historical_data: Optional[Dict[str, Any]] = None
    system_config: Optional[Dict[str, Any]] = None
    recent_events: Optional[List[Dict]] = None
    weather_data: Optional[Dict[str, Any]] = None
    growth_stage: Optional[str] = None
    timestamp: Optional[datetime] = None


class PromptManager:
    """Manages prompt templates and context injection for LLM operations."""
    
    def __init__(self):
        """Initialize prompt manager with templates."""
        self._templates = self._load_prompt_templates()
        self._context_processors = self._setup_context_processors()
    
    def _load_prompt_templates(self) -> Dict[str, Dict]:
        """Load all prompt templates."""
        return {
            PromptType.IRRIGATION_DECISION.value: {
                PromptComplexity.SIMPLE.value: {
                    "system": self._get_irrigation_system_prompt(),
                    "user": self._get_simple_irrigation_prompt()
                },
                PromptComplexity.STANDARD.value: {
                    "system": self._get_irrigation_system_prompt(),
                    "user": self._get_standard_irrigation_prompt()
                },
                PromptComplexity.DETAILED.value: {
                    "system": self._get_irrigation_system_prompt(),
                    "user": self._get_detailed_irrigation_prompt()
                },
                PromptComplexity.EXPERT.value: {
                    "system": self._get_irrigation_system_prompt(),
                    "user": self._get_expert_irrigation_prompt()
                }
            },
            PromptType.PHASE_TRANSITION.value: {
                PromptComplexity.STANDARD.value: {
                    "system": self._get_phase_system_prompt(),
                    "user": self._get_phase_transition_prompt()
                }
            },
            PromptType.TROUBLESHOOTING.value: {
                PromptComplexity.STANDARD.value: {
                    "system": self._get_troubleshooting_system_prompt(),
                    "user": self._get_troubleshooting_prompt()
                },
                PromptComplexity.DETAILED.value: {
                    "system": self._get_troubleshooting_system_prompt(),
                    "user": self._get_detailed_troubleshooting_prompt()
                }
            },
            PromptType.OPTIMIZATION.value: {
                PromptComplexity.STANDARD.value: {
                    "system": self._get_optimization_system_prompt(),
                    "user": self._get_optimization_prompt()
                }
            },
            PromptType.EMERGENCY_ANALYSIS.value: {
                PromptComplexity.SIMPLE.value: {
                    "system": self._get_emergency_system_prompt(),
                    "user": self._get_emergency_analysis_prompt()
                }
            },
            PromptType.SENSOR_VALIDATION.value: {
                PromptComplexity.SIMPLE.value: {
                    "system": self._get_sensor_system_prompt(),
                    "user": self._get_sensor_validation_prompt()
                }
            }
        }
    
    def _get_irrigation_system_prompt(self) -> str:
        """Core system prompt for irrigation decisions."""
        return """You are an expert precision agriculture AI assistant specializing in crop steering irrigation systems. Your role is to analyze sensor data and make informed irrigation decisions for controlled environment agriculture.

CRITICAL SAFETY REQUIREMENTS:
- Always prioritize plant health and safety over efficiency
- Never recommend actions that could cause crop stress or death
- If uncertain, err on the side of caution and recommend conservative actions
- Provide clear reasoning for all recommendations
- Consider both immediate and long-term plant health impacts

EXPERTISE AREAS:
- Volumetric Water Content (VWC) analysis and interpretation
- Electrical Conductivity (EC) monitoring and nutrient management
- 4-phase irrigation cycle optimization (P0-P3)
- Dryback analysis and timing
- Environmental factor integration
- Growth stage considerations

RESPONSE FORMAT:
Provide responses in JSON format with these fields:
- "decision": "irrigate" | "wait" | "emergency" | "phase_change"
- "confidence": 0-100 (percentage confidence in recommendation)
- "reasoning": "Clear explanation of the decision rationale"
- "shot_size_ml": number (if irrigating, recommended volume in mL)
- "urgency": "low" | "medium" | "high" | "emergency"
- "next_check_minutes": number (when to reassess)
- "warnings": [] (array of any concerns or warnings)
- "parameters": {} (any specific parameter adjustments)

Always provide quantitative reasoning based on the sensor data and thresholds."""
    
    def _get_simple_irrigation_prompt(self) -> str:
        """Simple irrigation decision prompt for basic operations."""
        return """Based on the current sensor data for Zone {zone_id}, should irrigation be triggered?

CURRENT STATUS:
- Zone: {zone_id}
- Phase: {current_phase}
- VWC Front: {vwc_front}%
- VWC Back: {vwc_back}%
- VWC Average: {vwc_avg}%
- EC Front: {ec_front} mS/cm
- EC Back: {ec_back} mS/cm
- EC Average: {ec_avg} mS/cm
- Target VWC: {target_vwc}%
- Target EC: {target_ec} mS/cm

THRESHOLDS:
- VWC Trigger: {vwc_threshold}%
- EC Ratio: {ec_ratio}
- Shot Size: {shot_size_ml}mL

DECISION CRITERIA:
- Phase {current_phase} requirements
- Current sensor readings vs targets
- Time since last irrigation: {time_since_last}

Provide a clear irrigation recommendation with reasoning."""
    
    def _get_standard_irrigation_prompt(self) -> str:
        """Standard irrigation decision prompt with moderate detail."""
        return """Analyze the irrigation needs for Zone {zone_id} considering current conditions and historical patterns.

CURRENT CONDITIONS:
Zone: {zone_id} | Phase: {current_phase} | Time: {timestamp}

SENSOR READINGS:
VWC: Front={vwc_front}%, Back={vwc_back}%, Average={vwc_avg}%
EC: Front={ec_front} mS/cm, Back={ec_back} mS/cm, Average={ec_avg} mS/cm
Temperature: {temperature}°C
Humidity: {humidity}%

TARGETS & THRESHOLDS:
Target VWC: {target_vwc}% | VWC Threshold: {vwc_threshold}%
Target EC: {target_ec} mS/cm | EC Ratio: {ec_ratio}
Configured Shot Size: {shot_size_ml}mL

HISTORICAL CONTEXT:
{historical_summary}

RECENT EVENTS:
{recent_events}

PHASE REQUIREMENTS:
{phase_requirements}

ANALYSIS REQUIRED:
1. Current moisture status vs targets
2. EC levels and nutrient availability
3. Phase-appropriate action
4. Timing considerations
5. Risk assessment

Provide irrigation recommendation with detailed reasoning and any parameter adjustments needed."""
    
    def _get_detailed_irrigation_prompt(self) -> str:
        """Detailed irrigation prompt for comprehensive analysis."""
        return """Perform comprehensive irrigation analysis for Zone {zone_id} including predictive modeling and optimization recommendations.

SYSTEM STATUS:
Zone: {zone_id} | Phase: {current_phase} | Growth Stage: {growth_stage}
Timestamp: {timestamp} | Days in Phase: {days_in_phase}

CURRENT SENSOR ARRAY:
VWC Sensors: Front={vwc_front}%, Back={vwc_back}%, Average={vwc_avg}%
EC Sensors: Front={ec_front} mS/cm, Back={ec_back} mS/cm, Average={ec_avg} mS/cm
Environmental: Temp={temperature}°C, RH={humidity}%, VPD={vpd} kPa

SYSTEM CONFIGURATION:
Target VWC: {target_vwc}% (Range: {vwc_min}-{vwc_max}%)
Target EC: {target_ec} mS/cm (Range: {ec_min}-{ec_max} mS/cm)
Current Thresholds: VWC={vwc_threshold}%, EC Ratio={ec_ratio}
Shot Configuration: {shot_size_ml}mL, Max Daily: {max_daily_ml}mL

HISTORICAL ANALYSIS:
{detailed_historical_data}

TREND ANALYSIS:
VWC Trend (24h): {vwc_trend_24h}
EC Trend (24h): {ec_trend_24h}
Irrigation Frequency: {irrigation_frequency}
Dryback Patterns: {dryback_analysis}

ENVIRONMENTAL CONTEXT:
Weather Forecast: {weather_forecast}
Light Schedule: {light_schedule}
Climate Conditions: {climate_conditions}

PERFORMANCE METRICS:
Water Use Efficiency: {wue}
EC Management Score: {ec_score}
Growth Rate: {growth_rate}

COMPREHENSIVE ANALYSIS REQUIRED:
1. Multi-sensor data validation and outlier detection
2. VWC/EC correlation analysis and optimal ranges
3. Phase-specific requirements vs current status
4. Predictive modeling for next 2-4 hours
5. Environmental factor integration
6. Historical pattern matching and learning
7. Risk assessment for under/over irrigation
8. Optimization opportunities for efficiency
9. Long-term trend implications
10. System performance evaluation

Provide detailed irrigation strategy with predictive insights and optimization recommendations."""
    
    def _get_expert_irrigation_prompt(self) -> str:
        """Expert-level prompt for advanced analysis and research scenarios."""
        return """Conduct expert-level precision agriculture analysis for Zone {zone_id} with research-grade insights and advanced optimization strategies.

EXECUTIVE SUMMARY REQUEST:
Provide comprehensive crop steering analysis incorporating advanced plant physiology, environmental science, and precision agriculture best practices.

COMPLETE SYSTEM STATE:
Zone ID: {zone_id} | Growth Phase: {current_phase} | Phenological Stage: {growth_stage}
Operational Day: {day_number} | Time: {timestamp} | Photoperiod: {photoperiod}

MULTI-SENSOR TELEMETRY:
Primary VWC Array: F={vwc_front}%, B={vwc_back}%, μ={vwc_avg}%, σ={vwc_std}%
Primary EC Array: F={ec_front}, B={ec_back}, μ={ec_avg}, σ={ec_std} mS/cm
Backup Sensors: {backup_sensors}
Environmental Matrix: T={temperature}°C, RH={humidity}%, VPD={vpd}kPa, PPFD={ppfd}μmol/m²/s

PHYSIOLOGICAL TARGETS:
VWC Operating Range: {target_vwc}% ±{vwc_tolerance}% (Critical: {vwc_critical_min}-{vwc_critical_max}%)
EC Management Zone: {target_ec} ±{ec_tolerance} mS/cm (Stress Threshold: >{ec_stress_threshold})
Water Potential: {water_potential} MPa | Osmotic Potential: {osmotic_potential} MPa

ADVANCED METRICS:
Water Use Efficiency: {wue_current} vs {wue_target} g DW/L
Specific Leaf Area: {sla} cm²/g | Leaf Water Content: {lwc}%
Stomatal Conductance Proxy: {gs_proxy} | Photosynthetic Rate Proxy: {pn_proxy}
Root Zone Activity Index: {root_activity_index}

HISTORICAL PERFORMANCE DATABASE:
{comprehensive_historical_analysis}

MACHINE LEARNING INSIGHTS:
Predictive Model Confidence: {ml_confidence}%
Anomaly Detection Score: {anomaly_score}
Pattern Recognition Results: {pattern_recognition}
Optimization Suggestions: {ml_optimization}

ENVIRONMENTAL INTEGRATION:
Microclimate Analysis: {microclimate_data}
Weather Integration: {weather_integration}
Climate Control Feedback: {climate_feedback}

RESEARCH-GRADE ANALYSIS REQUIREMENTS:
1. Advanced plant water relations analysis using water potential theory
2. Root zone hydraulic conductivity assessment and modeling
3. Transpiration rate estimation and VPD response curves
4. Nutrient uptake kinetics and EC optimization modeling
5. Stomatal behavior prediction under current environmental matrix
6. Photosynthetic efficiency analysis and light use efficiency
7. Advanced dryback characterization using multi-exponential decay models
8. Machine learning-based anomaly detection and early warning systems
9. Multi-objective optimization (yield, quality, resource efficiency)
10. Phenological stage-specific physiological response modeling
11. Long-term sustainability and resource conservation analysis
12. Comparative analysis with research literature and best practices

EXPERT DELIVERABLES:
Provide university research-level analysis with:
- Quantitative physiological assessment
- Predictive modeling with confidence intervals
- Multi-scenario decision matrix
- Risk-benefit analysis with statistical significance
- Literature-based validation of recommendations
- Long-term optimization strategy
- Research gaps identification
- Experimental design suggestions for continuous improvement

This analysis should demonstrate mastery of plant physiology, precision agriculture engineering, and data science methodologies."""
    
    def _get_phase_system_prompt(self) -> str:
        """System prompt for phase transition decisions."""
        return """You are a crop steering phase management specialist. Your role is to determine optimal timing for phase transitions in the 4-phase irrigation cycle (P0-P3) based on plant physiological indicators and environmental conditions.

PHASE OVERVIEW:
- P0 (Morning Dryback): Monitor VWC decline from overnight peak
- P1 (Ramp-Up): Progressive irrigation to reach target VWC  
- P2 (Maintenance): Threshold-based irrigation maintenance
- P3 (Pre-Lights-Off): Prepare plants for night cycle

CRITICAL CONSIDERATIONS:
- Plant stress indicators and recovery patterns
- VWC trajectory and dryback completion
- EC trends and nutrient uptake patterns
- Environmental factors and timing
- Growth stage requirements

Provide phase transition recommendations in JSON format with clear reasoning and timing guidance."""
    
    def _get_phase_transition_prompt(self) -> str:
        """Prompt for phase transition analysis."""
        return """Analyze phase transition requirements for Zone {zone_id}.

CURRENT PHASE STATUS:
Zone: {zone_id} | Current Phase: {current_phase} | Time in Phase: {time_in_phase}
Phase Start Time: {phase_start_time} | Target Transition: {target_transition_time}

PHYSIOLOGICAL INDICATORS:
VWC Trend: {vwc_trend} | Peak VWC: {peak_vwc}% | Current VWC: {current_vwc}%
Dryback Progress: {dryback_progress}% | Target Dryback: {target_dryback}%
EC Status: Current={current_ec}, Target={target_ec}, Trend={ec_trend}

ENVIRONMENTAL CONTEXT:
Light Status: {light_status} | Time to Lights Off: {time_to_lights_off}
Environmental Conditions: {environmental_conditions}

HISTORICAL PATTERNS:
Previous Phase Duration: {previous_phase_duration}
Typical Transition Triggers: {transition_triggers}
Success Metrics: {success_metrics}

ANALYSIS REQUIRED:
1. Phase completion criteria assessment
2. Plant readiness for next phase
3. Environmental timing considerations
4. Risk assessment for early/late transition
5. Optimization opportunities

Determine if phase transition should occur and provide detailed transition strategy."""
    
    def _get_troubleshooting_system_prompt(self) -> str:
        """System prompt for troubleshooting analysis."""
        return """You are a precision agriculture troubleshooting specialist. Analyze system anomalies, sensor irregularities, and performance issues to provide diagnostic insights and corrective actions.

DIAGNOSTIC CAPABILITIES:
- Sensor validation and calibration assessment
- Irrigation system performance analysis
- Environmental factor correlation
- Plant stress detection and mitigation
- System optimization recommendations

Focus on identifying root causes and providing actionable solutions while maintaining plant health and system reliability."""
    
    def _get_troubleshooting_prompt(self) -> str:
        """Standard troubleshooting prompt."""
        return """Diagnose potential issues with Zone {zone_id} irrigation system.

REPORTED SYMPTOMS:
{symptoms_description}

CURRENT SYSTEM STATE:
Zone: {zone_id} | Phase: {current_phase} | Alert Level: {alert_level}
Sensor Status: {sensor_status}
Recent Performance: {performance_metrics}

ANOMALY INDICATORS:
{anomaly_indicators}

HISTORICAL COMPARISON:
{historical_comparison}

ENVIRONMENTAL FACTORS:
{environmental_factors}

DIAGNOSTIC ANALYSIS REQUIRED:
1. Sensor accuracy and calibration status
2. Irrigation delivery system performance
3. Environmental factor impacts
4. Plant stress indicators
5. System configuration issues
6. Data quality assessment

Provide comprehensive diagnostic report with prioritized corrective actions."""
    
    def _get_detailed_troubleshooting_prompt(self) -> str:
        """Detailed troubleshooting with comprehensive analysis."""
        return """Perform comprehensive system diagnostic for Zone {zone_id} with advanced troubleshooting protocols.

INCIDENT REPORT:
Issue ID: {issue_id} | Severity: {severity} | Detection Time: {detection_time}
Symptoms: {detailed_symptoms}
Impact Assessment: {impact_assessment}

COMPREHENSIVE SYSTEM ANALYSIS:
{comprehensive_system_data}

MULTI-SENSOR VALIDATION:
{sensor_validation_data}

PERFORMANCE TRENDING:
{performance_trends}

ENVIRONMENTAL CORRELATION:
{environmental_correlation}

ROOT CAUSE ANALYSIS:
{root_cause_data}

ADVANCED DIAGNOSTIC REQUIREMENTS:
1. Multi-sensor cross-validation and calibration drift analysis
2. Statistical process control and anomaly quantification
3. Environmental factor correlation and impact modeling
4. Plant physiological stress assessment and recovery projections
5. System component reliability analysis
6. Data integrity and communication pathway validation
7. Predictive failure analysis and preventive recommendations
8. Cost-benefit analysis of corrective actions
9. Long-term system optimization opportunities
10. Quality assurance and validation protocols

Provide expert-level diagnostic report with quantitative analysis and prioritized action plan."""
    
    def _get_optimization_system_prompt(self) -> str:
        """System prompt for optimization analysis."""
        return """You are a precision agriculture optimization specialist focused on improving irrigation efficiency, resource utilization, and crop outcomes through data-driven insights and advanced analytics.

OPTIMIZATION DOMAINS:
- Water use efficiency maximization
- Energy consumption reduction
- Nutrient delivery optimization
- Growth rate enhancement
- Quality parameter improvement
- Operational cost reduction

Provide actionable optimization strategies with quantitative benefits and implementation guidance."""
    
    def _get_optimization_prompt(self) -> str:
        """Optimization analysis prompt."""
        return """Analyze optimization opportunities for Zone {zone_id} irrigation system.

CURRENT PERFORMANCE METRICS:
{current_performance}

EFFICIENCY INDICATORS:
Water Use Efficiency: {wue_current} vs Benchmark: {wue_benchmark}
Energy Consumption: {energy_current} vs Target: {energy_target}
Nutrient Efficiency: {nutrient_efficiency}

HISTORICAL PERFORMANCE:
{historical_performance}

COMPARATIVE ANALYSIS:
{comparative_analysis}

OPTIMIZATION TARGETS:
{optimization_targets}

ANALYSIS REQUIREMENTS:
1. Resource efficiency optimization
2. Performance improvement opportunities
3. Cost reduction strategies
4. Quality enhancement potential
5. Sustainability improvements
6. Automation opportunities

Provide comprehensive optimization strategy with quantified benefits and implementation roadmap."""
    
    def _get_emergency_system_prompt(self) -> str:
        """System prompt for emergency analysis."""
        return """You are an emergency response specialist for precision agriculture systems. Rapidly assess critical situations and provide immediate protective actions to prevent crop loss or system damage.

EMERGENCY PROTOCOLS:
- Immediate threat assessment
- Plant protection priorities
- System safeguarding procedures
- Rapid response recommendations
- Escalation criteria

Focus on immediate actions to protect crops and systems while providing clear escalation guidance."""
    
    def _get_emergency_analysis_prompt(self) -> str:
        """Emergency analysis prompt."""
        return """EMERGENCY ANALYSIS REQUIRED for Zone {zone_id}

ALERT DETAILS:
Alert Type: {alert_type} | Severity: {severity} | Time: {timestamp}
Critical Values: {critical_values}
Threshold Violations: {threshold_violations}

IMMEDIATE SYSTEM STATE:
{emergency_system_state}

RISK ASSESSMENT:
Plant Health Risk: {plant_risk}
System Damage Risk: {system_risk}
Time Sensitivity: {time_sensitivity}

EMERGENCY RESPONSE REQUIRED:
1. Immediate threat mitigation
2. Plant protection actions
3. System safeguarding
4. Monitoring intensification
5. Escalation recommendations

Provide emergency response plan with immediate actions and monitoring requirements."""
    
    def _get_sensor_system_prompt(self) -> str:
        """System prompt for sensor validation."""
        return """You are a sensor validation specialist focused on ensuring data quality and measurement accuracy in precision agriculture systems.

VALIDATION CAPABILITIES:
- Sensor accuracy assessment
- Calibration drift detection
- Data quality analysis
- Measurement correlation
- Outlier identification

Provide actionable sensor maintenance and calibration recommendations."""
    
    def _get_sensor_validation_prompt(self) -> str:
        """Sensor validation prompt."""
        return """Validate sensor performance for Zone {zone_id}.

SENSOR ARRAY STATUS:
{sensor_status}

MEASUREMENT ANALYSIS:
{measurement_analysis}

CALIBRATION STATUS:
{calibration_status}

DATA QUALITY METRICS:
{data_quality}

VALIDATION REQUIREMENTS:
1. Measurement accuracy assessment
2. Sensor correlation analysis
3. Drift detection and trending
4. Outlier identification
5. Calibration recommendations

Provide sensor validation report with maintenance recommendations."""
    
    def _setup_context_processors(self) -> Dict:
        """Set up context processors for different data types."""
        return {
            "sensor_data": self._process_sensor_context,
            "historical_data": self._process_historical_context,
            "environmental_data": self._process_environmental_context,
            "system_config": self._process_config_context,
            "events": self._process_events_context
        }
    
    def generate_prompt(
        self,
        prompt_type: PromptType,
        context: PromptContext,
        complexity: PromptComplexity = PromptComplexity.STANDARD,
        custom_params: Optional[Dict] = None
    ) -> Dict[str, str]:
        """Generate a complete prompt with system and user messages."""
        try:
            # Get template for prompt type and complexity
            if prompt_type.value not in self._templates:
                raise ValueError(f"Unknown prompt type: {prompt_type}")
            
            prompt_templates = self._templates[prompt_type.value]
            
            if complexity.value not in prompt_templates:
                # Fall back to standard complexity if requested complexity not available
                complexity = PromptComplexity.STANDARD
                if complexity.value not in prompt_templates:
                    raise ValueError(f"No templates available for {prompt_type}")
            
            template = prompt_templates[complexity.value]
            
            # Process context data
            context_vars = self._process_context(context, custom_params or {})
            
            # Format templates with context
            system_prompt = template["system"].format(**context_vars)
            user_prompt = template["user"].format(**context_vars)
            
            return {
                "system": system_prompt,
                "user": user_prompt,
                "metadata": {
                    "prompt_type": prompt_type.value,
                    "complexity": complexity.value,
                    "zone_id": context.zone_id,
                    "timestamp": context.timestamp.isoformat() if context.timestamp else datetime.now().isoformat()
                }
            }
            
        except Exception as e:
            _LOGGER.error("Error generating prompt: %s", e)
            # Return fallback prompt
            return {
                "system": "You are a precision agriculture assistant. Analyze the provided data and give recommendations.",
                "user": f"Analyze irrigation needs for Zone {context.zone_id} with current phase {context.current_phase}.",
                "metadata": {"error": str(e)}
            }
    
    def _process_context(self, context: PromptContext, custom_params: Dict) -> Dict[str, Any]:
        """Process context data into template variables."""
        # Start with custom parameters
        vars_dict = custom_params.copy()
        
        # Add basic context
        vars_dict.update({
            "zone_id": context.zone_id,
            "current_phase": context.current_phase,
            "timestamp": context.timestamp.isoformat() if context.timestamp else datetime.now().isoformat(),
            "growth_stage": context.growth_stage or "unknown"
        })
        
        # Process sensor data
        if context.sensor_data:
            vars_dict.update(self._process_sensor_context(context.sensor_data))
        
        # Process historical data
        if context.historical_data:
            vars_dict.update(self._process_historical_context(context.historical_data))
        
        # Process system configuration
        if context.system_config:
            vars_dict.update(self._process_config_context(context.system_config))
        
        # Process recent events
        if context.recent_events:
            vars_dict.update(self._process_events_context(context.recent_events))
        
        # Process weather data
        if context.weather_data:
            vars_dict.update(self._process_environmental_context(context.weather_data))
        
        # Ensure all template variables have default values
        self._apply_defaults(vars_dict)
        
        return vars_dict
    
    def _process_sensor_context(self, sensor_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process sensor data into template variables."""
        processed = {}
        
        # VWC processing
        vwc_front = sensor_data.get("vwc_front", 0)
        vwc_back = sensor_data.get("vwc_back", 0)
        processed.update({
            "vwc_front": round(vwc_front, 1),
            "vwc_back": round(vwc_back, 1),
            "vwc_avg": round((vwc_front + vwc_back) / 2, 1),
            "vwc_std": round(abs(vwc_front - vwc_back) / 2, 1)
        })
        
        # EC processing
        ec_front = sensor_data.get("ec_front", 0)
        ec_back = sensor_data.get("ec_back", 0)
        processed.update({
            "ec_front": round(ec_front, 2),
            "ec_back": round(ec_back, 2),
            "ec_avg": round((ec_front + ec_back) / 2, 2),
            "ec_std": round(abs(ec_front - ec_back) / 2, 2)
        })
        
        # Environmental sensors
        processed.update({
            "temperature": round(sensor_data.get("temperature", 0), 1),
            "humidity": round(sensor_data.get("humidity", 0), 1),
            "vpd": round(sensor_data.get("vpd", 0), 2)
        })
        
        return processed
    
    def _process_historical_context(self, historical_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process historical data into template variables."""
        return {
            "historical_summary": historical_data.get("summary", "No historical data available"),
            "detailed_historical_data": json.dumps(historical_data, indent=2),
            "vwc_trend_24h": historical_data.get("vwc_trend_24h", "stable"),
            "ec_trend_24h": historical_data.get("ec_trend_24h", "stable"),
            "irrigation_frequency": historical_data.get("irrigation_frequency", "normal"),
            "dryback_analysis": historical_data.get("dryback_analysis", "normal pattern")
        }
    
    def _process_environmental_context(self, weather_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process environmental/weather data."""
        return {
            "weather_forecast": weather_data.get("forecast", "No forecast available"),
            "light_schedule": weather_data.get("light_schedule", "Standard photoperiod"),
            "climate_conditions": weather_data.get("climate", "Controlled environment"),
            "environmental_conditions": json.dumps(weather_data, indent=2)
        }
    
    def _process_config_context(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process system configuration data."""
        return {
            "target_vwc": config_data.get("target_vwc", 65),
            "target_ec": config_data.get("target_ec", 2.5),
            "vwc_threshold": config_data.get("vwc_threshold", 60),
            "ec_ratio": config_data.get("ec_ratio", 1.0),
            "shot_size_ml": config_data.get("shot_size_ml", 100),
            "max_daily_ml": config_data.get("max_daily_ml", 2000),
            "vwc_min": config_data.get("vwc_min", 50),
            "vwc_max": config_data.get("vwc_max", 80),
            "ec_min": config_data.get("ec_min", 1.5),
            "ec_max": config_data.get("ec_max", 4.0)
        }
    
    def _process_events_context(self, events_data: List[Dict]) -> Dict[str, Any]:
        """Process recent events data."""
        if not events_data:
            return {
                "recent_events": "No recent events",
                "time_since_last": "unknown"
            }
        
        # Format recent events
        event_summary = []
        for event in events_data[-5:]:  # Last 5 events
            event_summary.append(
                f"{event.get('timestamp', 'unknown')}: {event.get('type', 'event')} - {event.get('description', 'no description')}"
            )
        
        return {
            "recent_events": "\\n".join(event_summary),
            "time_since_last": events_data[-1].get("time_since", "unknown") if events_data else "unknown"
        }
    
    def _apply_defaults(self, vars_dict: Dict[str, Any]) -> None:
        """Apply default values for any missing template variables."""
        defaults = {
            # Sensor defaults
            "vwc_front": 0, "vwc_back": 0, "vwc_avg": 0, "vwc_std": 0,
            "ec_front": 0, "ec_back": 0, "ec_avg": 0, "ec_std": 0,
            "temperature": 0, "humidity": 0, "vpd": 0,
            
            # Configuration defaults
            "target_vwc": 65, "target_ec": 2.5, "vwc_threshold": 60,
            "ec_ratio": 1.0, "shot_size_ml": 100, "max_daily_ml": 2000,
            
            # Historical defaults
            "historical_summary": "No historical data available",
            "vwc_trend_24h": "stable", "ec_trend_24h": "stable",
            "irrigation_frequency": "normal", "dryback_analysis": "normal",
            
            # Event defaults
            "recent_events": "No recent events",
            "time_since_last": "unknown",
            
            # Environmental defaults
            "weather_forecast": "No forecast available",
            "light_schedule": "Standard photoperiod",
            "climate_conditions": "Controlled environment",
            
            # Phase defaults
            "phase_requirements": "Standard phase requirements",
            "time_in_phase": "unknown",
            "days_in_phase": 0,
            
            # Emergency defaults
            "alert_type": "unknown", "severity": "medium",
            "critical_values": "none", "threshold_violations": "none",
            "plant_risk": "low", "system_risk": "low", "time_sensitivity": "medium"
        }
        
        for key, default_value in defaults.items():
            if key not in vars_dict:
                vars_dict[key] = default_value
    
    def estimate_token_usage(
        self,
        prompt_type: PromptType,
        complexity: PromptComplexity,
        context_size: str = "medium"
    ) -> int:
        """Estimate token usage for a prompt type and complexity."""
        # Base token estimates by complexity
        base_tokens = {
            PromptComplexity.SIMPLE: 500,
            PromptComplexity.STANDARD: 1200,
            PromptComplexity.DETAILED: 2500,
            PromptComplexity.EXPERT: 4500
        }
        
        # Context size multipliers
        context_multipliers = {
            "small": 0.8,
            "medium": 1.0,
            "large": 1.5,
            "xlarge": 2.0
        }
        
        # Prompt type adjustments
        type_adjustments = {
            PromptType.IRRIGATION_DECISION: 1.0,
            PromptType.PHASE_TRANSITION: 0.8,
            PromptType.TROUBLESHOOTING: 1.3,
            PromptType.OPTIMIZATION: 1.5,
            PromptType.EMERGENCY_ANALYSIS: 0.6,
            PromptType.SENSOR_VALIDATION: 0.7
        }
        
        base = base_tokens.get(complexity, 1200)
        context_mult = context_multipliers.get(context_size, 1.0)
        type_mult = type_adjustments.get(prompt_type, 1.0)
        
        return int(base * context_mult * type_mult)
    
    def get_recommended_complexity(
        self,
        operation_type: str,
        budget_tier: str,
        urgency: str = "medium"
    ) -> PromptComplexity:
        """Recommend prompt complexity based on operation parameters."""
        # Emergency situations use simple prompts
        if urgency == "emergency":
            return PromptComplexity.SIMPLE
        
        # Budget-based recommendations
        if budget_tier == "economy":
            return PromptComplexity.SIMPLE
        elif budget_tier == "standard":
            if operation_type in ["irrigation_decision", "phase_transition"]:
                return PromptComplexity.STANDARD
            else:
                return PromptComplexity.SIMPLE
        elif budget_tier == "premium":
            if operation_type in ["optimization", "troubleshooting"]:
                return PromptComplexity.DETAILED
            else:
                return PromptComplexity.STANDARD
        
        # Default to standard
        return PromptComplexity.STANDARD
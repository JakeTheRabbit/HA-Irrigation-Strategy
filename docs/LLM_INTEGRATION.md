# LLM Integration for Crop Steering System

## Overview

The LLM Integration enhances the Crop Steering System with AI-powered decision making while maintaining the existing safety-first approach with rule-based fallbacks. This integration provides intelligent irrigation recommendations, phase transition analysis, and system optimization suggestions.

## Architecture

### Safety-First Design
- **Rule-based fallbacks**: All LLM decisions are validated against safety rules
- **Budget controls**: Comprehensive cost management and usage limits
- **Emergency overrides**: Critical conditions bypass LLM and use immediate rule-based responses
- **Confidence thresholds**: Low-confidence LLM decisions default to rule-based logic

### Components

1. **LLM Client Layer** (`llm/client.py`)
   - Unified API interface for Claude and OpenAI
   - Async HTTP clients with retry logic and error handling
   - Automatic failover between providers
   - Token counting and cost estimation

2. **Cost Optimizer** (`llm/cost_optimizer.py`)
   - Budget tracking (daily/weekly/monthly limits)
   - Usage analytics and reporting
   - Cost tier management (Economy/Standard/Premium/Emergency)
   - Alert system for budget thresholds

3. **Prompt Manager** (`llm/prompts.py`)
   - Specialized prompts for irrigation decisions, troubleshooting, optimization
   - Multiple complexity levels (Simple/Standard/Detailed/Expert)
   - Context injection and template management
   - Token usage estimation

4. **Decision Engine** (`llm/decision_engine.py`)
   - Core decision making logic combining LLM and rules
   - Safety validation and constraint enforcement
   - Performance tracking and metrics
   - Decision history and learning

5. **AppDaemon Integration** (`appdaemon/apps/crop_steering/llm/`)
   - Seamless integration with existing automation
   - Event-driven LLM enhancements
   - Real-time decision processing

## Installation

### Prerequisites
- Home Assistant with Crop Steering integration installed
- AppDaemon add-on (optional, for autonomous operation)
- API key for Claude (Anthropic) or OpenAI

### Setup Steps

1. **Enable LLM Integration in Home Assistant**
   The LLM components are automatically available once the Crop Steering integration is installed.

2. **Configure AppDaemon (Optional)**
   Add the LLM-enhanced app to your `appdaemon/apps/apps.yaml`:

   ```yaml
   llm_enhanced_crop_steering:
     module: crop_steering.llm.llm_enhanced_app
     class: LLMEnhancedCropSteering
     
     zones: [1, 2, 3]
     enable_llm: true
     
     llm_config:
       provider: "claude"
       model: "claude-3-5-sonnet-20241022"
       api_key: !secret claude_api_key
     
     budget_config:
       daily_limit: 5.0
       cost_tier: "standard"
   ```

3. **Add API Key to Secrets**
   In your `secrets.yaml`:
   ```yaml
   claude_api_key: "sk-ant-api03-your-key-here"
   ```

4. **Restart AppDaemon**
   The LLM-enhanced automation will initialize alongside existing crop steering apps.

## Configuration

### Cost Tiers

**Economy** ($1-2/day typical)
- Uses cheapest models (Claude Haiku, GPT-3.5)
- Strict budget controls
- Frequent rule-based fallbacks
- Best for: Testing, low-budget operations

**Standard** ($3-8/day typical)
- Balanced model usage (Claude Sonnet, GPT-4)
- Reasonable token limits
- Good LLM/rule balance
- Best for: Most production environments

**Premium** ($10-25/day typical)
- Best models with higher token limits
- Detailed analysis and recommendations
- Best for: Research, high-value crops

**Emergency** (Minimal usage)
- LLM only for true emergencies
- Rule-based for normal operations
- Best for: Very tight budgets

### Budget Controls

- **Daily/Weekly/Monthly Limits**: Automatic budget enforcement
- **Alert Thresholds**: Notifications at 70% and 90% of limits
- **Emergency Reserve**: Additional budget for critical situations
- **Usage Tracking**: Detailed analytics and reporting

### Safety Thresholds

Critical conditions that trigger immediate rule-based responses:
- VWC below 40% or above 80%
- EC above 5.0 mS/cm
- Sensor communication failures
- LLM confidence below threshold (default 70%)

## Usage

### Automatic Operation

Once configured, the LLM integration works automatically:

1. **Irrigation Decisions**: Enhanced analysis considering environmental factors, growth stage, and historical patterns
2. **Phase Transitions**: Intelligent timing based on plant physiology and sensor trends
3. **Troubleshooting**: Automated diagnosis of sensor issues and system anomalies
4. **Optimization**: Continuous improvement suggestions for efficiency and performance

### Manual Control

Control LLM features through Home Assistant:

```yaml
# Enable/disable LLM features
service: input_boolean.turn_on
target:
  entity_id: input_boolean.crop_steering_llm_enabled

# Change cost tier
service: input_select.select_option
target:
  entity_id: input_select.crop_steering_llm_cost_tier
data:
  option: "premium"

# Adjust daily budget
service: input_number.set_value
target:
  entity_id: input_number.crop_steering_llm_daily_budget
data:
  value: 10.0
```

### Service Calls

Get usage reports:
```yaml
service: crop_steering.get_llm_usage_report
data:
  days: 7
```

Update safety thresholds:
```yaml
service: crop_steering.update_llm_safety_thresholds
data:
  thresholds:
    min_confidence: 75.0
    max_vwc_critical: 75.0
```

## Monitoring

### Performance Metrics

The system tracks:
- Decision accuracy and confidence levels
- Cost per decision and total usage
- LLM vs rule-based decision ratios
- Error rates and response times
- Budget utilization and trends

### Alerts and Notifications

Automatic notifications for:
- Budget threshold warnings (70%, 90%)
- High error rates or system issues
- Critical safety condition overrides
- Weekly usage summaries

### Logs and Debugging

Detailed logging for:
- Decision reasoning and confidence
- Budget tracking and cost breakdowns
- Safety override triggers
- Performance optimization opportunities

## Advanced Features

### Prompt Complexity Levels

**Simple**: Fast, low-cost decisions for routine operations
**Standard**: Balanced analysis for normal conditions  
**Detailed**: Comprehensive analysis for complex situations
**Expert**: Research-grade analysis with full context

### Historical Learning

The system learns from:
- Decision outcomes and plant responses
- Seasonal patterns and trends
- User corrections and overrides
- Environmental correlations

### Predictive Analytics

Advanced models consider:
- Weather forecasts and climate data
- Growth stage requirements
- Nutrient uptake patterns
- Long-term yield optimization

## Troubleshooting

### Common Issues

**High Costs**
- Check cost tier settings
- Review token usage patterns
- Adjust prompt complexity
- Increase rule-based fallback thresholds

**Low LLM Usage**
- Verify API keys and connectivity
- Check budget availability
- Review confidence thresholds
- Monitor error rates

**Decision Quality**
- Validate sensor data accuracy
- Review historical context quality
- Adjust safety thresholds
- Provide user feedback for learning

### Support

For issues and improvements:
1. Check AppDaemon logs for detailed error information
2. Review Home Assistant notifications for alerts
3. Generate usage reports to identify patterns
4. Consult the main project documentation

## API Reference

### LLM Decision Structure
```python
@dataclass
class LLMDecision:
    decision: str  # "irrigate", "wait", "emergency", "phase_change"
    confidence: float  # 0-100
    reasoning: str
    shot_size_ml: Optional[int] = None
    urgency: str = "medium"  # "low", "medium", "high", "emergency"
    next_check_minutes: int = 15
    warnings: List[str] = None
    parameters: Dict[str, Any] = None
```

### Configuration Options
See `llm_integration_config.yaml` for complete configuration reference.

---

This LLM integration maintains the reliability and safety of the existing rule-based system while adding intelligent decision-making capabilities that adapt to your specific growing conditions and requirements.
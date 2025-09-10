# GPT-5 Setup Guide for Crop Steering System

## Quick Start (5 Minutes)

### Step 1: Secure Your API Key

**IMPORTANT**: Never commit API keys to git!

1. Create a `secrets.yaml` file in your config directory:
```bash
cd C:\Github\HA-Irrigation-Strategy
cp secrets.yaml.example secrets.yaml
```

2. Add your OpenAI API key:
```yaml
# secrets.yaml
openai_api_key: "sk-proj-YOUR_ACTUAL_KEY_HERE"
```

3. Verify `.gitignore` includes `secrets.yaml`:
```bash
echo "secrets.yaml" >> .gitignore
```

### Step 2: Configure GPT-5 Models

Edit `config/gpt5_config.yaml` to set your preferences:

```yaml
# Recommended Budget-Conscious Configuration
models:
  default:
    name: "gpt-5-nano"  # $0.05/1M tokens - perfect for routine decisions
    
budget:
  daily_limit: 3.00  # Start conservative, increase as needed
```

### Step 3: Test API Connection

Run this test script to verify your setup:

```python
# test_gpt5.py
import os
import yaml
from openai import OpenAI

# Load secrets
with open('secrets.yaml', 'r') as f:
    secrets = yaml.safe_load(f)

# Initialize client
client = OpenAI(api_key=secrets['openai_api_key'])

# Test with GPT-5-nano
response = client.chat.completions.create(
    model="gpt-5-nano",
    messages=[{"role": "user", "content": "Test irrigation decision: VWC 45%, EC 2.5"}],
    max_tokens=100,
    temperature=0.1
)

print(f"Response: {response.choices[0].message.content}")
print(f"Tokens used: {response.usage.total_tokens}")
print(f"Estimated cost: ${response.usage.total_tokens * 0.05 / 1_000_000:.6f}")
```

## Cost Optimization Strategy

### Recommended Model Usage by Phase

| Phase | Model | Cost/Decision | Frequency | Daily Cost |
|-------|-------|---------------|-----------|------------|
| **P0 (Dryback)** | gpt-5-nano | $0.0001 | Every 15 min | $0.01 |
| **P1 (Ramp-up)** | gpt-5-nano | $0.0001 | Every 5 min | $0.03 |
| **P2 (Maintenance)** | gpt-5-nano | $0.0001 | Every 3 min | $0.05 |
| **P3 (Pre-lights-off)** | gpt-5-nano | $0.0001 | Every 10 min | $0.01 |
| **Weekly Analysis** | gpt-5-mini | $0.002 | Once/week | $0.01 |
| **Emergency** | gpt-5 | $0.01 | As needed | Reserve |

**Total estimated daily cost: $0.10-0.50** (well under budget!)

### GPT-5 Nano Performance

Despite being the cheapest option, GPT-5-nano is perfect for crop steering because:

- **Fast response**: <1 second latency
- **Consistent decisions**: Low temperature (0.1) ensures repeatability
- **Sufficient intelligence**: Handles VWC/EC thresholds perfectly
- **Cost effective**: 1000x cheaper than GPT-4

### Caching Strategy (90% Savings!)

GPT-5 offers 90% discount on cached tokens. Enable aggressive caching:

```yaml
caching:
  enabled: true
  ttl_minutes: 1440  # 24 hours
  similarity_threshold: 0.95
  
  # Cache these aggressively
  cache_priorities:
    - normal_irrigation_check
    - threshold_evaluation
    - sensor_validation
```

## Integration with Home Assistant

### Step 1: Update configuration.yaml

```yaml
# configuration.yaml
crop_steering:
  llm:
    enabled: true
    provider: "openai"
    model: "gpt-5-nano"
    api_key: !secret openai_api_key
    daily_budget: 3.00
    
  # Your existing crop steering config...
```

### Step 2: Add LLM entities

The integration automatically creates these entities:

```yaml
sensor.crop_steering_llm_daily_cost     # Track spending
sensor.crop_steering_llm_decisions_today # Decision count
sensor.crop_steering_llm_confidence_avg  # Average confidence
sensor.crop_steering_llm_cache_hit_rate  # Cache efficiency

switch.crop_steering_llm_enabled        # Enable/disable AI
select.crop_steering_llm_model          # Switch models
number.crop_steering_llm_daily_budget   # Adjust budget
```

### Step 3: Dashboard Card

Add this card to monitor LLM performance:

```yaml
type: vertical-stack
cards:
  - type: entities
    title: GPT-5 Irrigation AI
    entities:
      - switch.crop_steering_llm_enabled
      - select.crop_steering_llm_model
      - sensor.crop_steering_llm_daily_cost
      - sensor.crop_steering_llm_confidence_avg
  
  - type: statistics-graph
    title: AI Decision History
    entities:
      - sensor.crop_steering_llm_decisions_today
    days_to_show: 7
```

## AppDaemon Configuration

### Step 1: Update apps.yaml

```yaml
# appdaemon/apps/apps.yaml
llm_crop_steering:
  module: llm_enhanced_app
  class: LLMEnhancedCropSteering
  
  # API Configuration
  llm_provider: "openai"
  api_key: !secret openai_api_key
  model: "gpt-5-nano"
  
  # Cost Management
  daily_budget: 3.00
  enable_caching: true
  
  # Decision Settings
  decision_interval: 180  # 3 minutes
  min_confidence: 0.7
  
  # Safety
  enable_fallback: true
  emergency_override: true
  
  # Reasoning Control (GPT-5 specific)
  reasoning_effort: "minimal"  # minimal/low/medium/high
  verbosity: "low"  # low/medium/high
```

### Step 2: Restart AppDaemon

```bash
# If using Home Assistant Add-on
ha addon restart a0d7b954_appdaemon

# Or via docker
docker restart appdaemon
```

## Testing Your Setup

### Basic Connectivity Test

```python
# Run in AppDaemon or as standalone
async def test_gpt5_irrigation():
    """Test GPT-5 irrigation decision."""
    
    from custom_components.crop_steering.llm.gpt5_config import (
        GPT5Model, 
        GPT5DecisionRouter,
        create_gpt5_prompt
    )
    
    # Create test context
    context = {
        'vwc': 55,
        'ec': 2.8,
        'phase': 'P2',
        'growth_stage': 'Flowering',
        'vwc_target': 60,
        'ec_target': 2.5
    }
    
    # Select model
    router = GPT5DecisionRouter(DEFAULT_GPT5_CONFIG)
    model, reasoning, verbosity = router.select_model(
        urgency="normal",
        vwc=context['vwc'],
        ec=context['ec']
    )
    
    print(f"Selected: {model.value}")
    print(f"Reasoning: {reasoning.value}")
    
    # Create prompt
    prompt = create_gpt5_prompt(context, model, reasoning, verbosity)
    print(f"Prompt: {prompt}")
    
    # Calculate estimated cost
    from custom_components.crop_steering.llm.gpt5_config import GPT5CostCalculator
    
    daily_cost = GPT5CostCalculator.estimate_daily_cost(
        model=GPT5Model.NANO,
        calls_per_day=480,  # Every 3 minutes
        avg_input_tokens=200,
        avg_output_tokens=50,
        cache_hit_rate=0.7
    )
    
    print(f"Estimated daily cost: ${daily_cost:.2f}")
```

### Monitor First 24 Hours

Watch these metrics:

1. **Cost tracking**: Should stay well under $1/day with nano
2. **Cache hit rate**: Should reach 60-80% after first few hours
3. **Decision confidence**: Should average >0.8
4. **Response time**: Should be <2 seconds

## Troubleshooting

### "Model not found" Error

GPT-5 models require API access. Verify your account has access:
```bash
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### High Costs

If costs exceed expectations:
1. Check cache hit rate (should be >60%)
2. Reduce decision frequency
3. Ensure using gpt-5-nano for routine decisions
4. Check for error retry loops

### Low Confidence Decisions

If AI confidence is consistently <0.7:
1. Increase context provided in prompts
2. Switch to gpt-5-mini for complex decisions
3. Ensure sensor data is valid

### API Rate Limits

GPT-5 has generous rate limits, but if hit:
1. Enable request queuing
2. Increase decision interval
3. Use caching more aggressively

## Best Practices

### 1. Start Conservative
- Begin with $1/day budget
- Use gpt-5-nano exclusively
- Monitor for a week before increasing

### 2. Optimize Caching
- Cache similar contexts (same phase, similar VWC/EC)
- Use 24-hour TTL for stable conditions
- Clear cache when switching growth stages

### 3. Safety First
- Always maintain rule-based fallback
- Set confidence thresholds appropriately
- Never disable emergency overrides

### 4. Progressive Enhancement
- Week 1: Basic irrigation decisions with nano
- Week 2: Add weekly analysis with mini
- Week 3: Enable emergency responses with standard
- Week 4: Fine-tune based on results

## Cost Examples

### Hobbyist (1-2 zones)
- **Model**: gpt-5-nano only
- **Frequency**: Every 5 minutes
- **Daily calls**: ~300
- **Daily cost**: $0.05-0.10

### Prosumer (3-4 zones)
- **Models**: nano + weekly mini
- **Frequency**: Every 3 minutes
- **Daily calls**: ~500
- **Daily cost**: $0.10-0.30

### Commercial (5-6 zones)
- **Models**: All three tiers
- **Frequency**: Every 2 minutes
- **Daily calls**: ~750
- **Daily cost**: $0.50-1.00

## Support

For issues or questions:
1. Check AppDaemon logs: `/addon_configs/a0d7b954_appdaemon/logs/`
2. Review Home Assistant logs: Settings → System → Logs
3. Open GitHub issue with logs and configuration

Remember: GPT-5-nano at $0.05/1M tokens makes AI-powered irrigation incredibly affordable!
"""Cost optimization and budget tracking for LLM usage.

Implements budget controls, usage analytics, daily limits, and fallback decision logic
to ensure cost-effective LLM usage while maintaining system functionality.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, date, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .client import LLMProvider, LLMResponse

_LOGGER = logging.getLogger(__name__)


class BudgetPeriod(Enum):
    """Budget tracking periods."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class CostTier(Enum):
    """Cost optimization tiers."""
    PREMIUM = "premium"      # Use best models, unlimited budget
    STANDARD = "standard"    # Balanced approach with reasonable limits
    ECONOMY = "economy"      # Cost-conscious with strict limits
    EMERGENCY = "emergency"  # Minimal usage, rule-based fallbacks


@dataclass
class BudgetConfig:
    """Budget configuration settings."""
    daily_limit: float = 5.0        # $5 daily limit
    weekly_limit: float = 25.0      # $25 weekly limit  
    monthly_limit: float = 100.0    # $100 monthly limit
    emergency_reserve: float = 10.0 # $10 emergency reserve
    cost_tier: CostTier = CostTier.STANDARD
    enable_alerts: bool = True
    alert_thresholds: Dict[str, float] = None
    
    def __post_init__(self):
        """Set default alert thresholds."""
        if self.alert_thresholds is None:
            self.alert_thresholds = {
                "daily_warning": 0.7,   # 70% of daily budget
                "daily_critical": 0.9,  # 90% of daily budget
                "weekly_warning": 0.8,  # 80% of weekly budget
                "monthly_warning": 0.8  # 80% of monthly budget
            }


@dataclass
class UsageRecord:
    """Individual usage record."""
    timestamp: datetime
    provider: LLMProvider
    model: str
    tokens_used: int
    cost: float
    operation_type: str
    zone_id: Optional[int] = None
    metadata: Dict = None


@dataclass
class UsageStats:
    """Usage statistics for a time period."""
    period_start: datetime
    period_end: datetime
    total_cost: float
    total_tokens: int
    request_count: int
    avg_cost_per_request: float
    avg_tokens_per_request: float
    provider_breakdown: Dict[str, float]
    operation_breakdown: Dict[str, float]


class CostOptimizer:
    """Cost optimization and budget tracking system."""
    
    STORAGE_VERSION = 1
    STORAGE_KEY = "crop_steering_llm_usage"
    
    def __init__(self, hass: HomeAssistant, config: BudgetConfig):
        """Initialize cost optimizer."""
        self._hass = hass
        self._config = config
        self._store = Store(hass, self.STORAGE_VERSION, self.STORAGE_KEY)
        self._usage_records: List[UsageRecord] = []
        self._last_cleanup = datetime.now()
    
    async def initialize(self) -> None:
        """Initialize storage and load existing data."""
        try:
            data = await self._store.async_load()
            if data:
                self._load_usage_records(data.get("usage_records", []))
                _LOGGER.info("Loaded %d usage records", len(self._usage_records))
        except Exception as e:
            _LOGGER.warning("Could not load usage data: %s", e)
            self._usage_records = []
    
    def _load_usage_records(self, records_data: List[Dict]) -> None:
        """Load usage records from storage data."""
        self._usage_records = []
        for record_data in records_data:
            try:
                # Convert string timestamps back to datetime
                record_data["timestamp"] = datetime.fromisoformat(
                    record_data["timestamp"]
                )
                # Convert provider string back to enum
                record_data["provider"] = LLMProvider(record_data["provider"])
                
                self._usage_records.append(UsageRecord(**record_data))
            except Exception as e:
                _LOGGER.warning("Could not load usage record: %s", e)
                continue
    
    async def _save_usage_data(self) -> None:
        """Save usage data to storage."""
        try:
            # Convert records to serializable format
            records_data = []
            for record in self._usage_records:
                record_dict = asdict(record)
                record_dict["timestamp"] = record.timestamp.isoformat()
                record_dict["provider"] = record.provider.value
                records_data.append(record_dict)
            
            await self._store.async_save({
                "usage_records": records_data,
                "last_updated": datetime.now().isoformat()
            })
        except Exception as e:
            _LOGGER.error("Could not save usage data: %s", e)
    
    async def record_usage(
        self, 
        response: LLMResponse, 
        operation_type: str,
        zone_id: Optional[int] = None
    ) -> None:
        """Record LLM usage for cost tracking."""
        record = UsageRecord(
            timestamp=response.timestamp,
            provider=response.provider,
            model=response.model,
            tokens_used=response.tokens_used,
            cost=response.cost_estimate,
            operation_type=operation_type,
            zone_id=zone_id,
            metadata=response.metadata
        )
        
        self._usage_records.append(record)
        
        # Periodic cleanup and save
        if (datetime.now() - self._last_cleanup).total_seconds() > 3600:  # 1 hour
            await self._cleanup_old_records()
            await self._save_usage_data()
            self._last_cleanup = datetime.now()
        
        # Check budget limits
        await self._check_budget_limits()
    
    async def _cleanup_old_records(self) -> None:
        """Remove usage records older than 90 days."""
        cutoff_date = datetime.now() - timedelta(days=90)
        old_count = len(self._usage_records)
        
        self._usage_records = [
            record for record in self._usage_records 
            if record.timestamp > cutoff_date
        ]
        
        removed_count = old_count - len(self._usage_records)
        if removed_count > 0:
            _LOGGER.info("Cleaned up %d old usage records", removed_count)
    
    def get_usage_for_period(
        self, 
        period: BudgetPeriod,
        reference_date: Optional[datetime] = None
    ) -> UsageStats:
        """Get usage statistics for a specific period."""
        if reference_date is None:
            reference_date = datetime.now()
        
        # Calculate period boundaries
        if period == BudgetPeriod.DAILY:
            period_start = reference_date.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            period_end = period_start + timedelta(days=1)
        elif period == BudgetPeriod.WEEKLY:
            days_since_monday = reference_date.weekday()
            period_start = (reference_date - timedelta(days=days_since_monday)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            period_end = period_start + timedelta(weeks=1)
        elif period == BudgetPeriod.MONTHLY:
            period_start = reference_date.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            if period_start.month == 12:
                period_end = period_start.replace(year=period_start.year + 1, month=1)
            else:
                period_end = period_start.replace(month=period_start.month + 1)
        
        # Filter records for period
        period_records = [
            record for record in self._usage_records
            if period_start <= record.timestamp < period_end
        ]
        
        if not period_records:
            return UsageStats(
                period_start=period_start,
                period_end=period_end,
                total_cost=0.0,
                total_tokens=0,
                request_count=0,
                avg_cost_per_request=0.0,
                avg_tokens_per_request=0.0,
                provider_breakdown={},
                operation_breakdown={}
            )
        
        # Calculate statistics
        total_cost = sum(record.cost for record in period_records)
        total_tokens = sum(record.tokens_used for record in period_records)
        request_count = len(period_records)
        
        # Provider breakdown
        provider_breakdown = {}
        for record in period_records:
            provider = record.provider.value
            provider_breakdown[provider] = provider_breakdown.get(provider, 0) + record.cost
        
        # Operation breakdown  
        operation_breakdown = {}
        for record in period_records:
            op_type = record.operation_type
            operation_breakdown[op_type] = operation_breakdown.get(op_type, 0) + record.cost
        
        return UsageStats(
            period_start=period_start,
            period_end=period_end,
            total_cost=total_cost,
            total_tokens=total_tokens,
            request_count=request_count,
            avg_cost_per_request=total_cost / request_count,
            avg_tokens_per_request=total_tokens / request_count,
            provider_breakdown=provider_breakdown,
            operation_breakdown=operation_breakdown
        )
    
    async def check_budget_availability(
        self, 
        estimated_cost: float,
        operation_type: str = "general"
    ) -> Tuple[bool, str]:
        """Check if operation is within budget limits."""
        daily_stats = self.get_usage_for_period(BudgetPeriod.DAILY)
        weekly_stats = self.get_usage_for_period(BudgetPeriod.WEEKLY)
        monthly_stats = self.get_usage_for_period(BudgetPeriod.MONTHLY)
        
        # Check daily limit
        if daily_stats.total_cost + estimated_cost > self._config.daily_limit:
            return False, f"Would exceed daily budget limit (${self._config.daily_limit})"
        
        # Check weekly limit
        if weekly_stats.total_cost + estimated_cost > self._config.weekly_limit:
            return False, f"Would exceed weekly budget limit (${self._config.weekly_limit})"
        
        # Check monthly limit
        if monthly_stats.total_cost + estimated_cost > self._config.monthly_limit:
            return False, f"Would exceed monthly budget limit (${self._config.monthly_limit})"
        
        # Check emergency operations
        if operation_type == "emergency":
            # Emergency operations get access to reserve budget
            total_available = (
                self._config.daily_limit + 
                self._config.weekly_limit + 
                self._config.monthly_limit + 
                self._config.emergency_reserve
            )
            total_used = (
                daily_stats.total_cost + 
                weekly_stats.total_cost + 
                monthly_stats.total_cost
            )
            if total_used + estimated_cost > total_available:
                return False, "Would exceed emergency reserve budget"
        
        return True, "Within budget limits"
    
    async def _check_budget_limits(self) -> None:
        """Check current usage against budget limits and send alerts."""
        if not self._config.enable_alerts:
            return
        
        daily_stats = self.get_usage_for_period(BudgetPeriod.DAILY)
        weekly_stats = self.get_usage_for_period(BudgetPeriod.WEEKLY)
        monthly_stats = self.get_usage_for_period(BudgetPeriod.MONTHLY)
        
        # Check daily thresholds
        daily_pct = daily_stats.total_cost / self._config.daily_limit
        if daily_pct >= self._config.alert_thresholds["daily_critical"]:
            await self._send_budget_alert(
                "critical", 
                f"Daily LLM budget at {daily_pct:.1%} (${daily_stats.total_cost:.2f}/${self._config.daily_limit})"
            )
        elif daily_pct >= self._config.alert_thresholds["daily_warning"]:
            await self._send_budget_alert(
                "warning",
                f"Daily LLM budget at {daily_pct:.1%} (${daily_stats.total_cost:.2f}/${self._config.daily_limit})"
            )
        
        # Check weekly thresholds
        weekly_pct = weekly_stats.total_cost / self._config.weekly_limit
        if weekly_pct >= self._config.alert_thresholds["weekly_warning"]:
            await self._send_budget_alert(
                "warning",
                f"Weekly LLM budget at {weekly_pct:.1%} (${weekly_stats.total_cost:.2f}/${self._config.weekly_limit})"
            )
        
        # Check monthly thresholds
        monthly_pct = monthly_stats.total_cost / self._config.monthly_limit
        if monthly_pct >= self._config.alert_thresholds["monthly_warning"]:
            await self._send_budget_alert(
                "warning",
                f"Monthly LLM budget at {monthly_pct:.1%} (${monthly_stats.total_cost:.2f}/${self._config.monthly_limit})"
            )
    
    async def _send_budget_alert(self, severity: str, message: str) -> None:
        """Send budget alert through Home Assistant notification system."""
        try:
            await self._hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": f"Crop Steering LLM Budget Alert ({severity.upper()})",
                    "message": message,
                    "notification_id": f"crop_steering_llm_budget_{severity}"
                }
            )
            _LOGGER.warning("LLM budget alert (%s): %s", severity, message)
        except Exception as e:
            _LOGGER.error("Could not send budget alert: %s", e)
    
    def get_cost_optimization_recommendation(
        self, 
        operation_type: str,
        current_cost_estimate: float
    ) -> Tuple[bool, str, Dict]:
        """Get recommendation for cost optimization."""
        daily_stats = self.get_usage_for_period(BudgetPeriod.DAILY)
        weekly_stats = self.get_usage_for_period(BudgetPeriod.WEEKLY)
        
        # Calculate current usage percentages
        daily_pct = daily_stats.total_cost / self._config.daily_limit
        weekly_pct = weekly_stats.total_cost / self._config.weekly_limit
        
        recommendations = {
            "use_llm": True,
            "suggested_model": None,
            "max_tokens": None,
            "temperature": None,
            "fallback_to_rules": False,
            "reason": ""
        }
        
        # Economy tier - strict cost controls
        if self._config.cost_tier == CostTier.ECONOMY:
            if daily_pct > 0.8 or current_cost_estimate > 0.50:
                recommendations.update({
                    "use_llm": False,
                    "fallback_to_rules": True,
                    "reason": "Economy tier budget limits - using rule-based fallback"
                })
                return False, "Use rule-based fallback", recommendations
            
            # Use cheaper models and lower token limits
            recommendations.update({
                "suggested_model": "gpt-5-nano",  # Ultra-cheap GPT-5 model
                "max_tokens": 1000,  # Reduced token limit
                "temperature": 0.3,  # Lower temperature for more deterministic output
                "reason": "Economy tier - using cost-optimized settings"
            })
        
        # Emergency tier - minimal LLM usage
        elif self._config.cost_tier == CostTier.EMERGENCY:
            if operation_type != "emergency":
                recommendations.update({
                    "use_llm": False,
                    "fallback_to_rules": True,
                    "reason": "Emergency tier - LLM usage reserved for emergencies only"
                })
                return False, "Emergency tier - use rules only", recommendations
        
        # Standard tier - balanced approach
        elif self._config.cost_tier == CostTier.STANDARD:
            if daily_pct > 0.9:
                recommendations.update({
                    "suggested_model": "gpt-5-nano",
                    "max_tokens": 2000,
                    "reason": "Approaching daily budget - using cheaper model"
                })
            elif current_cost_estimate > 1.0:
                recommendations.update({
                    "max_tokens": 3000,
                    "temperature": 0.5,
                    "reason": "High cost operation - reducing token limit"
                })
        
        # Premium tier - minimal restrictions
        # (Premium tier allows full usage with just monitoring)
        
        return True, "Approved with optimizations", recommendations
    
    async def generate_usage_report(self, days: int = 7) -> Dict:
        """Generate comprehensive usage report."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # Filter records for report period
        report_records = [
            record for record in self._usage_records
            if start_date <= record.timestamp <= end_date
        ]
        
        if not report_records:
            return {
                "period": f"Last {days} days",
                "total_cost": 0,
                "total_requests": 0,
                "message": "No LLM usage in this period"
            }
        
        # Calculate daily breakdown
        daily_breakdown = {}
        for record in report_records:
            day_key = record.timestamp.date().isoformat()
            if day_key not in daily_breakdown:
                daily_breakdown[day_key] = {"cost": 0, "requests": 0, "tokens": 0}
            
            daily_breakdown[day_key]["cost"] += record.cost
            daily_breakdown[day_key]["requests"] += 1
            daily_breakdown[day_key]["tokens"] += record.tokens_used
        
        # Provider and operation analysis
        provider_stats = {}
        operation_stats = {}
        zone_stats = {}
        
        for record in report_records:
            # Provider breakdown
            provider = record.provider.value
            if provider not in provider_stats:
                provider_stats[provider] = {"cost": 0, "requests": 0}
            provider_stats[provider]["cost"] += record.cost
            provider_stats[provider]["requests"] += 1
            
            # Operation breakdown
            op_type = record.operation_type
            if op_type not in operation_stats:
                operation_stats[op_type] = {"cost": 0, "requests": 0}
            operation_stats[op_type]["cost"] += record.cost
            operation_stats[op_type]["requests"] += 1
            
            # Zone breakdown
            if record.zone_id:
                zone_key = f"zone_{record.zone_id}"
                if zone_key not in zone_stats:
                    zone_stats[zone_key] = {"cost": 0, "requests": 0}
                zone_stats[zone_key]["cost"] += record.cost
                zone_stats[zone_key]["requests"] += 1
        
        total_cost = sum(record.cost for record in report_records)
        total_requests = len(report_records)
        
        return {
            "period": f"Last {days} days",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "total_cost": round(total_cost, 4),
            "total_requests": total_requests,
            "avg_cost_per_request": round(total_cost / total_requests, 4) if total_requests > 0 else 0,
            "daily_breakdown": daily_breakdown,
            "provider_breakdown": provider_stats,
            "operation_breakdown": operation_stats,
            "zone_breakdown": zone_stats,
            "current_budget_status": {
                "daily_used": round(self.get_usage_for_period(BudgetPeriod.DAILY).total_cost, 4),
                "daily_limit": self._config.daily_limit,
                "weekly_used": round(self.get_usage_for_period(BudgetPeriod.WEEKLY).total_cost, 4),
                "weekly_limit": self._config.weekly_limit,
                "monthly_used": round(self.get_usage_for_period(BudgetPeriod.MONTHLY).total_cost, 4),
                "monthly_limit": self._config.monthly_limit
            }
        }
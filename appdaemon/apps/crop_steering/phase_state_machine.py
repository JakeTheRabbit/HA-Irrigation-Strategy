"""
Phase State Machine for Crop Steering
Provides clean, centralized phase management for irrigation zones
"""

from enum import Enum, auto
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Callable, Any
import logging
import threading

_LOGGER = logging.getLogger(__name__)


class IrrigationPhase(Enum):
    """Irrigation phases with clear semantic meaning"""
    P0_MORNING_DRYBACK = "P0"     # Morning dryback period
    P1_RAMP_UP = "P1"              # Progressive rehydration
    P2_MAINTENANCE = "P2"          # EC-based maintenance
    P3_PRE_LIGHTS_OFF = "P3"      # Pre-lights-off dryback


class PhaseTransition(Enum):
    """Valid transitions between phases"""
    LIGHTS_ON = auto()                # Lights turned on - start P0
    DRYBACK_COMPLETE = auto()         # P0 target reached - start P1
    DRYBACK_TIMEOUT = auto()          # P0 max duration - start P1
    RAMP_UP_COMPLETE = auto()         # P1 target reached - start P2
    LIGHTS_OFF_APPROACHING = auto()   # ML prediction - start P3
    MANUAL_OVERRIDE = auto()          # Manual phase change
    EMERGENCY = auto()                # Emergency condition


@dataclass
class PhaseData:
    """Base class for phase-specific data"""
    entry_time: datetime = field(default_factory=datetime.now)
    exit_time: Optional[datetime] = None
    
    def get_duration(self) -> timedelta:
        """Get phase duration"""
        end = self.exit_time or datetime.now()
        return end - self.entry_time


@dataclass
class P0Data(PhaseData):
    """Data specific to P0 Morning Dryback phase"""
    peak_vwc: Optional[float] = None
    target_dryback_percentage: float = 50.0
    max_duration_minutes: int = 45
    current_dryback_percentage: float = 0.0
    dryback_rate: Optional[float] = None  # %/minute


@dataclass
class P1Data(PhaseData):
    """Data specific to P1 Ramp-Up phase"""
    vwc_at_start: Optional[float] = None
    target_vwc: float = 65.0
    shot_count: int = 0
    current_shot_size: Optional[float] = None
    initial_shot_size: float = 2.0  # % of substrate volume
    shot_history: List[Dict] = field(default_factory=list)  # List of shot details
    
    def add_shot(self, timestamp: datetime, size: float, vwc_before: float, vwc_after: float):
        """Record irrigation shot"""
        self.shot_history.append({
            'timestamp': timestamp,
            'size': size,
            'vwc_before': vwc_before,
            'vwc_after': vwc_after,
            'shot_number': self.shot_count + 1
        })
        self.shot_count += 1
        self.current_shot_size = size


@dataclass
class P2Data(PhaseData):
    """Data specific to P2 Maintenance phase"""
    irrigation_count: int = 0
    last_irrigation_time: Optional[datetime] = None
    field_capacity: Optional[float] = None
    ec_trend: List[Tuple[datetime, float]] = field(default_factory=list)
    vwc_trend: List[Tuple[datetime, float]] = field(default_factory=list)
    
    def add_irrigation(self, timestamp: datetime):
        """Record irrigation event"""
        self.irrigation_count += 1
        self.last_irrigation_time = timestamp


@dataclass
class P3Data(PhaseData):
    """Data specific to P3 Pre-Lights-Off phase"""
    emergency_shot_count: int = 0
    target_overnight_dryback: float = 50.0  # % dryback expected overnight
    predicted_dryback_duration: Optional[timedelta] = None
    last_emergency_shot: Optional[datetime] = None


@dataclass
class ZoneState:
    """Complete state data for a single irrigation zone"""
    zone_id: int
    current_phase: IrrigationPhase
    phase_history: List[Tuple[IrrigationPhase, datetime]] = field(default_factory=list)
    
    # Phase-specific data
    p0_data: Optional[P0Data] = None
    p1_data: Optional[P1Data] = None
    p2_data: Optional[P2Data] = None
    p3_data: Optional[P3Data] = None
    
    # Water usage tracking
    daily_water_ml: float = 0.0
    weekly_water_ml: float = 0.0
    daily_irrigation_count: int = 0
    last_daily_reset: datetime = field(default_factory=datetime.now)
    last_weekly_reset: datetime = field(default_factory=datetime.now)
    
    def get_current_phase_data(self) -> Optional[PhaseData]:
        """Get data for current phase"""
        phase_map = {
            IrrigationPhase.P0_MORNING_DRYBACK: self.p0_data,
            IrrigationPhase.P1_RAMP_UP: self.p1_data,
            IrrigationPhase.P2_MAINTENANCE: self.p2_data,
            IrrigationPhase.P3_PRE_LIGHTS_OFF: self.p3_data
        }
        return phase_map.get(self.current_phase)
    
    def record_water_usage(self, amount_ml: float):
        """Record water usage"""
        self.daily_water_ml += amount_ml
        self.weekly_water_ml += amount_ml
        self.daily_irrigation_count += 1


class ZoneStateMachine:
    """State machine for a single irrigation zone"""
    
    # Define valid transitions
    VALID_TRANSITIONS = {
        IrrigationPhase.P0_MORNING_DRYBACK: [
            (PhaseTransition.DRYBACK_COMPLETE, IrrigationPhase.P1_RAMP_UP),
            (PhaseTransition.DRYBACK_TIMEOUT, IrrigationPhase.P1_RAMP_UP),
            (PhaseTransition.MANUAL_OVERRIDE, IrrigationPhase.P1_RAMP_UP),
            (PhaseTransition.MANUAL_OVERRIDE, IrrigationPhase.P2_MAINTENANCE),
        ],
        IrrigationPhase.P1_RAMP_UP: [
            (PhaseTransition.RAMP_UP_COMPLETE, IrrigationPhase.P2_MAINTENANCE),
            (PhaseTransition.LIGHTS_OFF_APPROACHING, IrrigationPhase.P3_PRE_LIGHTS_OFF),
            (PhaseTransition.MANUAL_OVERRIDE, IrrigationPhase.P2_MAINTENANCE),
        ],
        IrrigationPhase.P2_MAINTENANCE: [
            (PhaseTransition.LIGHTS_OFF_APPROACHING, IrrigationPhase.P3_PRE_LIGHTS_OFF),
            (PhaseTransition.LIGHTS_ON, IrrigationPhase.P0_MORNING_DRYBACK),
            (PhaseTransition.MANUAL_OVERRIDE, IrrigationPhase.P3_PRE_LIGHTS_OFF),
        ],
        IrrigationPhase.P3_PRE_LIGHTS_OFF: [
            (PhaseTransition.LIGHTS_ON, IrrigationPhase.P0_MORNING_DRYBACK),
            (PhaseTransition.MANUAL_OVERRIDE, IrrigationPhase.P2_MAINTENANCE),
            (PhaseTransition.MANUAL_OVERRIDE, IrrigationPhase.P1_RAMP_UP),
        ]
    }
    
    def __init__(self, zone_id: int, initial_phase: IrrigationPhase = IrrigationPhase.P2_MAINTENANCE,
                 logger: Optional[logging.Logger] = None):
        """Initialize state machine for a zone"""
        self.zone_id = zone_id
        self.logger = logger or _LOGGER
        self.lock = threading.RLock()
        
        # Initialize state
        self.state = ZoneState(
            zone_id=zone_id,
            current_phase=initial_phase,
            phase_history=[(initial_phase, datetime.now())]
        )
        
        # Initialize phase data
        self._initialize_phase_data(initial_phase)
        
        # Callbacks
        self._on_enter_callbacks: Dict[IrrigationPhase, List[Callable]] = {}
        self._on_exit_callbacks: Dict[IrrigationPhase, List[Callable]] = {}
        self._transition_callbacks: Dict[Tuple[IrrigationPhase, IrrigationPhase], List[Callable]] = {}
    
    def _initialize_phase_data(self, phase: IrrigationPhase):
        """Initialize data for a phase"""
        if phase == IrrigationPhase.P0_MORNING_DRYBACK:
            self.state.p0_data = P0Data()
        elif phase == IrrigationPhase.P1_RAMP_UP:
            self.state.p1_data = P1Data()
        elif phase == IrrigationPhase.P2_MAINTENANCE:
            self.state.p2_data = P2Data()
        elif phase == IrrigationPhase.P3_PRE_LIGHTS_OFF:
            self.state.p3_data = P3Data()
    
    def can_transition(self, transition: PhaseTransition, to_phase: Optional[IrrigationPhase] = None) -> bool:
        """Check if transition is valid from current state"""
        with self.lock:
            valid_transitions = self.VALID_TRANSITIONS.get(self.state.current_phase, [])
            
            # Check if transition type is valid
            valid_transition_types = [t[0] for t in valid_transitions]
            if transition not in valid_transition_types:
                return False
            
            # If specific target phase requested, verify it's valid
            if to_phase:
                return any(t[0] == transition and t[1] == to_phase for t in valid_transitions)
            
            return True
    
    def transition(self, transition: PhaseTransition, to_phase: Optional[IrrigationPhase] = None,
                  reason: str = "", **kwargs) -> bool:
        """Execute state transition with validation"""
        with self.lock:
            old_phase = self.state.current_phase
            
            # Validate transition
            if not self.can_transition(transition, to_phase):
                self.logger.warning(
                    f"Zone {self.zone_id}: Invalid transition {transition.name} "
                    f"from {old_phase.value} to {to_phase.value if to_phase else 'auto'}"
                )
                return False
            
            # Determine target phase
            if to_phase is None:
                # Auto-select based on transition type
                valid_transitions = self.VALID_TRANSITIONS[old_phase]
                to_phase = next((t[1] for t in valid_transitions if t[0] == transition), None)
            
            if not to_phase:
                return False
            
            # Log transition
            self.logger.info(
                f"Zone {self.zone_id}: Transitioning {old_phase.value} -> {to_phase.value} "
                f"({transition.name}){f' - {reason}' if reason else ''}"
            )
            
            # Execute exit callbacks
            self._execute_callbacks(self._on_exit_callbacks.get(old_phase, []), old_phase=old_phase)
            
            # Mark exit time for old phase
            old_phase_data = self.state.get_current_phase_data()
            if old_phase_data:
                old_phase_data.exit_time = datetime.now()
            
            # Update state
            self.state.current_phase = to_phase
            self.state.phase_history.append((to_phase, datetime.now()))
            
            # Initialize new phase data
            self._initialize_phase_data(to_phase)
            
            # Execute enter callbacks
            self._execute_callbacks(self._on_enter_callbacks.get(to_phase, []), new_phase=to_phase)
            
            # Execute transition callbacks
            transition_key = (old_phase, to_phase)
            self._execute_callbacks(self._transition_callbacks.get(transition_key, []),
                                  old_phase=old_phase, new_phase=to_phase, transition=transition)
            
            return True
    
    def _execute_callbacks(self, callbacks: List[Callable], **kwargs):
        """Execute callbacks with error handling"""
        for callback in callbacks:
            try:
                callback(**kwargs)
            except Exception as e:
                self.logger.error(f"Zone {self.zone_id}: Callback error: {e}")
    
    def register_on_enter(self, phase: IrrigationPhase, callback: Callable):
        """Register callback for phase entry"""
        if phase not in self._on_enter_callbacks:
            self._on_enter_callbacks[phase] = []
        self._on_enter_callbacks[phase].append(callback)
    
    def register_on_exit(self, phase: IrrigationPhase, callback: Callable):
        """Register callback for phase exit"""
        if phase not in self._on_exit_callbacks:
            self._on_exit_callbacks[phase] = []
        self._on_exit_callbacks[phase].append(callback)
    
    def register_transition(self, from_phase: IrrigationPhase, to_phase: IrrigationPhase, 
                          callback: Callable):
        """Register callback for specific transition"""
        key = (from_phase, to_phase)
        if key not in self._transition_callbacks:
            self._transition_callbacks[key] = []
        self._transition_callbacks[key].append(callback)
    
    def get_phase_duration(self) -> timedelta:
        """Get duration in current phase"""
        with self.lock:
            if len(self.state.phase_history) > 0:
                _, entry_time = self.state.phase_history[-1]
                return datetime.now() - entry_time
            return timedelta(0)
    
    def get_phase_string(self) -> str:
        """Get current phase as string (for compatibility)"""
        return self.state.current_phase.value
    
    def update_p0_dryback(self, current_vwc: float, peak_vwc: float):
        """Update P0 dryback progress"""
        with self.lock:
            if self.state.current_phase == IrrigationPhase.P0_MORNING_DRYBACK and self.state.p0_data:
                self.state.p0_data.peak_vwc = peak_vwc
                self.state.p0_data.current_dryback_percentage = ((peak_vwc - current_vwc) / peak_vwc) * 100 if peak_vwc > 0 else 0
                
                # Calculate dryback rate
                duration_minutes = self.get_phase_duration().total_seconds() / 60
                if duration_minutes > 0:
                    self.state.p0_data.dryback_rate = self.state.p0_data.current_dryback_percentage / duration_minutes
    
    def update_p1_progress(self, current_vwc: float):
        """Update P1 ramp-up progress"""
        with self.lock:
            if self.state.current_phase == IrrigationPhase.P1_RAMP_UP and self.state.p1_data:
                if self.state.p1_data.vwc_at_start is None:
                    self.state.p1_data.vwc_at_start = current_vwc
    
    def record_p1_shot(self, size: float, vwc_before: float, vwc_after: float):
        """Record P1 irrigation shot"""
        with self.lock:
            if self.state.current_phase == IrrigationPhase.P1_RAMP_UP and self.state.p1_data:
                self.state.p1_data.add_shot(datetime.now(), size, vwc_before, vwc_after)
                self.state.record_water_usage(size)  # Assuming size is in ml
    
    def record_p2_irrigation(self):
        """Record P2 irrigation event"""
        with self.lock:
            if self.state.current_phase == IrrigationPhase.P2_MAINTENANCE and self.state.p2_data:
                self.state.p2_data.add_irrigation(datetime.now())
    
    def record_p3_emergency(self):
        """Record P3 emergency irrigation"""
        with self.lock:
            if self.state.current_phase == IrrigationPhase.P3_PRE_LIGHTS_OFF and self.state.p3_data:
                self.state.p3_data.emergency_shot_count += 1
                self.state.p3_data.last_emergency_shot = datetime.now()
    
    def reset_daily_usage(self):
        """Reset daily water usage"""
        with self.lock:
            self.state.daily_water_ml = 0.0
            self.state.daily_irrigation_count = 0
            self.state.last_daily_reset = datetime.now()
    
    def reset_weekly_usage(self):
        """Reset weekly water usage"""
        with self.lock:
            self.state.weekly_water_ml = 0.0
            self.state.last_weekly_reset = datetime.now()
    
    def get_state_summary(self) -> Dict[str, Any]:
        """Get comprehensive state summary"""
        with self.lock:
            phase_data = self.state.get_current_phase_data()
            return {
                'zone_id': self.zone_id,
                'current_phase': self.state.current_phase.value,
                'phase_duration_minutes': self.get_phase_duration().total_seconds() / 60,
                'phase_data': phase_data.__dict__ if phase_data else {},
                'daily_water_ml': self.state.daily_water_ml,
                'weekly_water_ml': self.state.weekly_water_ml,
                'daily_irrigation_count': self.state.daily_irrigation_count,
                'phase_history': [(p.value, t.isoformat()) for p, t in self.state.phase_history[-10:]]
            }
"""
Smart Irrigation Learning System
================================
Intelligent crop steering that learns each zone's characteristics using precision
pressure-compensating drippers (no flow sensors needed).

Features:
- Field capacity detection
- Irrigation efficiency tracking
- Zone personality learning
- Adaptive shot size optimization
- Channeling detection
- All using simple math and data tracking (no ML required)

Hardware Requirements:
- Existing VWC/EC sensors
- Pressure compensating drippers (1.2 L/hr)
- Your current Home Assistant crop steering integration

Author: Intelligent Crop Steering System v1.0
"""

import appdaemon.plugins.hass.hassapi as hass
import sqlite3
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import statistics


class SmartIrrigationLearning(hass.Hass):
    """Intelligent irrigation learning system using pressure-compensating dripper precision."""
    
    def initialize(self):
        """Initialize the smart learning system."""
        # System configuration - ADJUST THESE FOR YOUR SETUP
        self.DRIPPER_RATE = 1.2  # L/hr per dripper (pressure compensating)
        self.DRIPPERS_PER_PLANT = 2
        self.PLANTS_PER_ZONE = 4
        self.SUBSTRATE_VOLUME = 3.0  # liters per plant
        self.ZONES = [1, 2, 3, 4, 5, 6]  # Active zones
        
        # Learning parameters
        self.FIELD_CAPACITY_EFFICIENCY_THRESHOLD = 0.3  # 30% efficiency = FC reached
        self.MIN_EFFICIENCY_FOR_GOOD_ABSORPTION = 0.7    # 70%+ = good absorption
        self.SHOT_TEST_DURATION = 30  # seconds for test shots
        self.ABSORPTION_WAIT_TIME = 120  # seconds to wait after irrigation
        
        # Database setup
        self.db_path = "/config/appdaemon/apps/crop_steering/zone_intelligence.db"
        self.setup_database()
        
        # Zone intelligence storage
        self.zone_profiles = self.load_zone_profiles()
        
        # Learning state tracking
        self.learning_active = {}  # Track which zones are in learning mode
        self.current_learning_session = {}
        
        # Setup Home Assistant integration
        self.listen_state(self.on_irrigation_complete, "crop_steering")
        
        # Schedule regular learning tasks
        self.run_daily(self.daily_learning_routine, "06:00:00")  # Run at 6 AM
        self.run_every(self.monitor_irrigation_performance, 300)  # Every 5 minutes
        
        self.log("Smart Irrigation Learning System initialized")
        self.log(f"Monitoring zones: {self.ZONES}")
        
    def setup_database(self):
        """Create SQLite database for tracking zone intelligence."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Zone profiles table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS zone_profiles (
                zone_id INTEGER PRIMARY KEY,
                field_capacity REAL,
                learned_date TIMESTAMP,
                efficiency_curve TEXT,  -- JSON storage
                optimal_shot_sizes TEXT,  -- JSON storage
                channeling_threshold REAL,
                notes TEXT,
                last_updated TIMESTAMP
            )
        ''')
        
        # Irrigation log table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS irrigation_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zone_id INTEGER,
                timestamp TIMESTAMP,
                vwc_before REAL,
                vwc_after REAL,
                duration_seconds INTEGER,
                water_delivered REAL,
                efficiency REAL,
                shot_type TEXT,
                learning_session TEXT,
                FOREIGN KEY (zone_id) REFERENCES zone_profiles (zone_id)
            )
        ''')
        
        # Learning sessions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS learning_sessions (
                session_id TEXT PRIMARY KEY,
                zone_id INTEGER,
                session_type TEXT,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                results TEXT,  -- JSON storage
                success BOOLEAN,
                FOREIGN KEY (zone_id) REFERENCES zone_profiles (zone_id)
            )
        ''')
        
        conn.commit()
        conn.close()
        self.log("Database setup complete")
    
    def calculate_water_delivered(self, zone_id: int, duration_seconds: int) -> float:
        """
        Calculate exact water delivered using pressure-compensating dripper specs.
        
        Args:
            zone_id: Zone number (1-6)
            duration_seconds: Irrigation duration in seconds
            
        Returns:
            Water delivered in liters (precise to ±2%)
        """
        total_drippers = self.PLANTS_PER_ZONE * self.DRIPPERS_PER_PLANT
        flow_rate_lps = (self.DRIPPER_RATE * total_drippers) / 3600  # L/s
        water_delivered = flow_rate_lps * duration_seconds
        
        self.log(f"Zone {zone_id}: {duration_seconds}s irrigation = {water_delivered:.3f}L delivered")
        return water_delivered
    
    def get_zone_vwc(self, zone_id: int) -> Optional[float]:
        """Get current VWC reading for zone."""
        try:
            # Try zone average first
            avg_vwc = self.get_state(f"sensor.crop_steering_zone_{zone_id}_vwc")
            if avg_vwc and avg_vwc != "unknown":
                return float(avg_vwc)
            
            # Fallback to individual sensors
            front_vwc = self.get_state(f"sensor.zone_{zone_id}_vwc_front")
            back_vwc = self.get_state(f"sensor.zone_{zone_id}_vwc_back")
            
            if front_vwc and back_vwc and front_vwc != "unknown" and back_vwc != "unknown":
                return (float(front_vwc) + float(back_vwc)) / 2
                
        except (ValueError, TypeError):
            pass
            
        self.log(f"Warning: Could not get VWC reading for zone {zone_id}")
        return None
    
    def irrigate_zone(self, zone_id: int, duration_seconds: int, shot_type: str = "learning") -> bool:
        """
        Execute irrigation for specified zone and duration.
        
        Args:
            zone_id: Zone to irrigate
            duration_seconds: How long to irrigate
            shot_type: Type of irrigation (learning, maintenance, etc.)
            
        Returns:
            True if irrigation executed successfully
        """
        try:
            self.call_service(
                "crop_steering/execute_irrigation_shot",
                zone=zone_id,
                duration_seconds=duration_seconds,
                shot_type=shot_type
            )
            self.log(f"Zone {zone_id}: Executed {duration_seconds}s irrigation ({shot_type})")
            return True
        except Exception as e:
            self.log(f"Error irrigating zone {zone_id}: {e}")
            return False
    
    def measure_irrigation_efficiency(self, zone_id: int, duration_seconds: int, 
                                    shot_type: str = "learning") -> Optional[Dict]:
        """
        Measure irrigation efficiency by comparing VWC change to water delivered.
        
        Args:
            zone_id: Zone to test
            duration_seconds: Irrigation duration
            shot_type: Type of test shot
            
        Returns:
            Dictionary with efficiency data or None if failed
        """
        # Get initial VWC
        vwc_before = self.get_zone_vwc(zone_id)
        if vwc_before is None:
            self.log(f"Zone {zone_id}: Cannot measure efficiency - VWC sensor unavailable")
            return None
        
        # Execute irrigation
        if not self.irrigate_zone(zone_id, duration_seconds, shot_type):
            return None
        
        # Calculate water delivered
        water_delivered = self.calculate_water_delivered(zone_id, duration_seconds)
        
        # Wait for absorption
        self.log(f"Zone {zone_id}: Waiting {self.ABSORPTION_WAIT_TIME}s for absorption...")
        time.sleep(self.ABSORPTION_WAIT_TIME)
        
        # Get final VWC
        vwc_after = self.get_zone_vwc(zone_id)
        if vwc_after is None:
            self.log(f"Zone {zone_id}: Cannot complete efficiency measurement")
            return None
        
        # Calculate efficiency
        vwc_change = vwc_after - vwc_before
        theoretical_vwc_increase = (water_delivered / self.SUBSTRATE_VOLUME) * 100
        
        if theoretical_vwc_increase <= 0:
            efficiency = 0
        else:
            efficiency = vwc_change / theoretical_vwc_increase
        
        # Store results
        efficiency_data = {
            'timestamp': datetime.now().isoformat(),
            'zone_id': zone_id,
            'vwc_before': vwc_before,
            'vwc_after': vwc_after,
            'vwc_change': vwc_change,
            'duration_seconds': duration_seconds,
            'water_delivered': water_delivered,
            'theoretical_increase': theoretical_vwc_increase,
            'efficiency': efficiency,
            'shot_type': shot_type
        }
        
        # Log to database
        self.log_irrigation_event(efficiency_data)
        
        self.log(f"Zone {zone_id}: VWC {vwc_before:.1f}→{vwc_after:.1f}% "
                f"({vwc_change:+.1f}%), Efficiency: {efficiency:.1%}")
        
        return efficiency_data
    
    def detect_field_capacity(self, zone_id: int) -> Optional[float]:
        """
        Detect field capacity by irrigating until efficiency drops below threshold.
        
        Args:
            zone_id: Zone to characterize
            
        Returns:
            Field capacity VWC percentage or None if failed
        """
        session_id = f"fc_detection_{zone_id}_{int(time.time())}"
        self.log(f"Zone {zone_id}: Starting field capacity detection (Session: {session_id})")
        
        # Start learning session
        self.start_learning_session(session_id, zone_id, "field_capacity_detection")
        
        efficiency_history = []
        shot_count = 0
        max_shots = 20  # Safety limit
        
        try:
            while shot_count < max_shots:
                shot_count += 1
                
                # Measure efficiency with test shot
                efficiency_data = self.measure_irrigation_efficiency(
                    zone_id, self.SHOT_TEST_DURATION, f"fc_test_{shot_count}"
                )
                
                if efficiency_data is None:
                    self.log(f"Zone {zone_id}: FC detection failed - sensor error")
                    return None
                
                efficiency = efficiency_data['efficiency']
                efficiency_history.append(efficiency)
                current_vwc = efficiency_data['vwc_after']
                
                self.log(f"Zone {zone_id}: Shot {shot_count}/20 - "
                        f"VWC: {current_vwc:.1f}%, Efficiency: {efficiency:.1%}")
                
                # Check if field capacity reached
                if efficiency < self.FIELD_CAPACITY_EFFICIENCY_THRESHOLD:
                    self.log(f"Zone {zone_id}: Field capacity detected at {current_vwc:.1f}% VWC")
                    
                    # Store field capacity in zone profile
                    self.update_zone_field_capacity(zone_id, current_vwc)
                    
                    # End learning session with success
                    results = {
                        'field_capacity_vwc': current_vwc,
                        'shots_to_fc': shot_count,
                        'total_water': shot_count * self.calculate_water_delivered(zone_id, self.SHOT_TEST_DURATION),
                        'efficiency_history': efficiency_history
                    }
                    self.end_learning_session(session_id, results, success=True)
                    
                    return current_vwc
                
                # Safety check for extremely high VWC
                if current_vwc > 85:
                    self.log(f"Zone {zone_id}: Safety stop - VWC too high ({current_vwc:.1f}%)")
                    break
        
        except Exception as e:
            self.log(f"Zone {zone_id}: FC detection error - {e}")
        
        # Failed to detect field capacity
        self.log(f"Zone {zone_id}: Could not detect field capacity in {max_shots} shots")
        self.end_learning_session(session_id, {'error': 'max_shots_reached'}, success=False)
        return None
    
    def characterize_zone_efficiency(self, zone_id: int) -> Dict:
        """
        Characterize zone efficiency at different VWC levels.
        
        Args:
            zone_id: Zone to characterize
            
        Returns:
            Dictionary with efficiency curve data
        """
        session_id = f"efficiency_curve_{zone_id}_{int(time.time())}"
        self.log(f"Zone {zone_id}: Starting efficiency characterization")
        
        self.start_learning_session(session_id, zone_id, "efficiency_characterization")
        
        # Test VWC levels
        test_levels = [50, 55, 60, 65]
        efficiency_curve = {}
        
        for target_vwc in test_levels:
            self.log(f"Zone {zone_id}: Testing efficiency at {target_vwc}% VWC")
            
            # Wait for zone to reach target VWC (or timeout)
            if not self.wait_for_vwc_level(zone_id, target_vwc, timeout_minutes=60):
                self.log(f"Zone {zone_id}: Timeout waiting for {target_vwc}% VWC")
                continue
            
            # Test with multiple shot sizes
            test_durations = [15, 30, 45, 60]  # seconds
            level_efficiencies = []
            
            for duration in test_durations:
                efficiency_data = self.measure_irrigation_efficiency(
                    zone_id, duration, f"curve_test_{target_vwc}"
                )
                
                if efficiency_data:
                    level_efficiencies.append({
                        'duration': duration,
                        'water_delivered': efficiency_data['water_delivered'],
                        'efficiency': efficiency_data['efficiency']
                    })
                
                # Small delay between tests
                time.sleep(60)
            
            if level_efficiencies:
                avg_efficiency = statistics.mean([e['efficiency'] for e in level_efficiencies])
                efficiency_curve[target_vwc] = {
                    'average_efficiency': avg_efficiency,
                    'test_results': level_efficiencies
                }
                
                self.log(f"Zone {zone_id}: Average efficiency at {target_vwc}% = {avg_efficiency:.1%}")
        
        # Store efficiency curve
        self.update_zone_efficiency_curve(zone_id, efficiency_curve)
        
        results = {'efficiency_curve': efficiency_curve}
        self.end_learning_session(session_id, results, success=len(efficiency_curve) > 0)
        
        return efficiency_curve
    
    def wait_for_vwc_level(self, zone_id: int, target_vwc: float, 
                          timeout_minutes: int = 60) -> bool:
        """
        Wait for zone VWC to reach target level (usually by drying back).
        
        Args:
            zone_id: Zone to monitor
            target_vwc: Target VWC percentage
            timeout_minutes: Maximum time to wait
            
        Returns:
            True if target reached, False if timeout
        """
        start_time = time.time()
        timeout_seconds = timeout_minutes * 60
        
        while time.time() - start_time < timeout_seconds:
            current_vwc = self.get_zone_vwc(zone_id)
            if current_vwc is None:
                time.sleep(300)  # Wait 5 minutes and retry
                continue
            
            if current_vwc <= target_vwc:
                self.log(f"Zone {zone_id}: Reached target VWC {current_vwc:.1f}% (target: {target_vwc}%)")
                return True
            
            # Wait 5 minutes between checks
            time.sleep(300)
        
        self.log(f"Zone {zone_id}: Timeout waiting for {target_vwc}% VWC")
        return False
    
    def calculate_optimal_shot_size(self, zone_id: int, current_vwc: float, 
                                  target_vwc_increase: float = 5.0) -> int:
        """
        Calculate optimal irrigation duration based on learned zone characteristics.
        
        Args:
            zone_id: Zone to irrigate
            current_vwc: Current VWC percentage
            target_vwc_increase: Desired VWC increase (default 5%)
            
        Returns:
            Optimal irrigation duration in seconds
        """
        # Get zone profile
        profile = self.zone_profiles.get(zone_id, {})
        efficiency_curve = profile.get('efficiency_curve', {})
        
        # Find closest efficiency data
        efficiency = 0.8  # Default efficiency assumption
        
        if efficiency_curve:
            closest_vwc = min(efficiency_curve.keys(), 
                            key=lambda x: abs(x - current_vwc))
            efficiency = efficiency_curve[closest_vwc].get('average_efficiency', 0.8)
        
        # Calculate water needed
        theoretical_water = (target_vwc_increase / 100) * self.SUBSTRATE_VOLUME
        actual_water_needed = theoretical_water / efficiency
        
        # Convert to duration
        flow_rate_lps = (self.DRIPPER_RATE * self.PLANTS_PER_ZONE * self.DRIPPERS_PER_PLANT) / 3600
        duration_seconds = int(actual_water_needed / flow_rate_lps)
        
        # Safety limits
        duration_seconds = max(10, min(duration_seconds, 300))  # 10s to 5min
        
        self.log(f"Zone {zone_id}: Optimal shot for +{target_vwc_increase:.1f}% VWC = "
                f"{duration_seconds}s (efficiency: {efficiency:.1%})")
        
        return duration_seconds
    
    def detect_channeling_patterns(self, zone_id: int) -> str:
        """
        Detect if substrate is channeling based on irrigation response patterns.
        
        Args:
            zone_id: Zone to analyze
            
        Returns:
            Analysis result string
        """
        # Get recent irrigation history
        recent_irrigations = self.get_recent_irrigation_history(zone_id, limit=10)
        
        if len(recent_irrigations) < 5:
            return "Insufficient data for channeling analysis"
        
        # Analyze efficiency patterns
        efficiencies = [irr['efficiency'] for irr in recent_irrigations]
        vwc_levels = [irr['vwc_before'] for irr in recent_irrigations]
        
        # Look for patterns indicating channeling
        low_vwc_low_efficiency = sum(1 for i, eff in enumerate(efficiencies) 
                                   if vwc_levels[i] < 55 and eff < 0.5)
        
        high_variance = statistics.stdev(efficiencies) > 0.3 if len(efficiencies) > 1 else False
        
        if low_vwc_low_efficiency >= 3:
            return "Likely channeling - poor efficiency at low VWC levels"
        elif high_variance:
            return "Inconsistent absorption - possible channeling or sensor issues"
        else:
            return "Normal absorption patterns - no channeling detected"
    
    def daily_learning_routine(self, kwargs):
        """Daily routine to analyze and learn from irrigation performance."""
        self.log("Running daily learning routine")
        
        for zone_id in self.ZONES:
            # Analyze recent performance
            performance = self.analyze_zone_performance(zone_id)
            
            # Update zone profile based on learning
            self.update_zone_learning(zone_id, performance)
            
            # Check if field capacity needs re-detection
            profile = self.zone_profiles.get(zone_id, {})
            if not profile.get('field_capacity'):
                self.log(f"Zone {zone_id}: No field capacity data - scheduling detection")
                self.run_in(self.detect_field_capacity, 300, zone_id=zone_id)  # 5 min delay
    
    def monitor_irrigation_performance(self, kwargs):
        """Monitor ongoing irrigation performance and adjust if needed."""
        # This runs every 5 minutes to monitor system performance
        for zone_id in self.ZONES:
            # Check if any learning sessions are active
            if zone_id in self.learning_active:
                continue
            
            # Analyze recent efficiency if irrigated in last hour
            recent = self.get_recent_irrigation_history(zone_id, limit=1, hours=1)
            if recent:
                last_irrigation = recent[0]
                if last_irrigation['efficiency'] < 0.3:
                    self.log(f"Zone {zone_id}: Low efficiency detected - may be at field capacity")
    
    # Database operations
    def log_irrigation_event(self, efficiency_data: Dict):
        """Log irrigation event to database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO irrigation_log 
            (zone_id, timestamp, vwc_before, vwc_after, duration_seconds, 
             water_delivered, efficiency, shot_type, learning_session)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            efficiency_data['zone_id'],
            efficiency_data['timestamp'],
            efficiency_data['vwc_before'],
            efficiency_data['vwc_after'],
            efficiency_data['duration_seconds'],
            efficiency_data['water_delivered'],
            efficiency_data['efficiency'],
            efficiency_data['shot_type'],
            self.current_learning_session.get(efficiency_data['zone_id'])
        ))
        
        conn.commit()
        conn.close()
    
    def start_learning_session(self, session_id: str, zone_id: int, session_type: str):
        """Start a learning session."""
        self.current_learning_session[zone_id] = session_id
        self.learning_active[zone_id] = True
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO learning_sessions 
            (session_id, zone_id, session_type, start_time)
            VALUES (?, ?, ?, ?)
        ''', (session_id, zone_id, session_type, datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
    
    def end_learning_session(self, session_id: str, results: Dict, success: bool):
        """End a learning session and store results."""
        # Find zone_id for this session
        zone_id = None
        for zid, sid in self.current_learning_session.items():
            if sid == session_id:
                zone_id = zid
                break
        
        if zone_id:
            self.learning_active[zone_id] = False
            del self.current_learning_session[zone_id]
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE learning_sessions 
            SET end_time = ?, results = ?, success = ?
            WHERE session_id = ?
        ''', (datetime.now().isoformat(), json.dumps(results), success, session_id))
        
        conn.commit()
        conn.close()
    
    def load_zone_profiles(self) -> Dict:
        """Load zone profiles from database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM zone_profiles')
        profiles = {}
        
        for row in cursor.fetchall():
            zone_id = row[0]
            profiles[zone_id] = {
                'field_capacity': row[1],
                'learned_date': row[2],
                'efficiency_curve': json.loads(row[3]) if row[3] else {},
                'optimal_shot_sizes': json.loads(row[4]) if row[4] else {},
                'channeling_threshold': row[5],
                'notes': row[6],
                'last_updated': row[7]
            }
        
        conn.close()
        return profiles
    
    def update_zone_field_capacity(self, zone_id: int, field_capacity: float):
        """Update field capacity for zone."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO zone_profiles 
            (zone_id, field_capacity, learned_date, last_updated)
            VALUES (?, ?, ?, ?)
        ''', (zone_id, field_capacity, datetime.now().isoformat(), datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        
        # Update in-memory profile
        if zone_id not in self.zone_profiles:
            self.zone_profiles[zone_id] = {}
        self.zone_profiles[zone_id]['field_capacity'] = field_capacity
        self.zone_profiles[zone_id]['last_updated'] = datetime.now().isoformat()
    
    def update_zone_efficiency_curve(self, zone_id: int, efficiency_curve: Dict):
        """Update efficiency curve for zone."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get existing profile
        cursor.execute('SELECT * FROM zone_profiles WHERE zone_id = ?', (zone_id,))
        existing = cursor.fetchone()
        
        if existing:
            cursor.execute('''
                UPDATE zone_profiles 
                SET efficiency_curve = ?, last_updated = ?
                WHERE zone_id = ?
            ''', (json.dumps(efficiency_curve), datetime.now().isoformat(), zone_id))
        else:
            cursor.execute('''
                INSERT INTO zone_profiles 
                (zone_id, efficiency_curve, last_updated)
                VALUES (?, ?, ?)
            ''', (zone_id, json.dumps(efficiency_curve), datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        
        # Update in-memory profile
        if zone_id not in self.zone_profiles:
            self.zone_profiles[zone_id] = {}
        self.zone_profiles[zone_id]['efficiency_curve'] = efficiency_curve
        self.zone_profiles[zone_id]['last_updated'] = datetime.now().isoformat()
    
    def get_recent_irrigation_history(self, zone_id: int, limit: int = 10, 
                                    hours: int = 24) -> List[Dict]:
        """Get recent irrigation history for zone."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        since_time = (datetime.now() - timedelta(hours=hours)).isoformat()
        
        cursor.execute('''
            SELECT * FROM irrigation_log 
            WHERE zone_id = ? AND timestamp > ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (zone_id, since_time, limit))
        
        history = []
        for row in cursor.fetchall():
            history.append({
                'timestamp': row[2],
                'vwc_before': row[3],
                'vwc_after': row[4],
                'duration_seconds': row[5],
                'water_delivered': row[6],
                'efficiency': row[7],
                'shot_type': row[8]
            })
        
        conn.close()
        return history
    
    def analyze_zone_performance(self, zone_id: int) -> Dict:
        """Analyze recent zone performance and return insights."""
        recent_history = self.get_recent_irrigation_history(zone_id, limit=20)
        
        if not recent_history:
            return {'status': 'no_data', 'message': 'No recent irrigation data'}
        
        # Calculate performance metrics
        efficiencies = [h['efficiency'] for h in recent_history]
        avg_efficiency = statistics.mean(efficiencies)
        efficiency_trend = efficiencies[:5] if len(efficiencies) >= 5 else efficiencies
        
        performance = {
            'irrigation_count': len(recent_history),
            'average_efficiency': avg_efficiency,
            'efficiency_stdev': statistics.stdev(efficiencies) if len(efficiencies) > 1 else 0,
            'recent_trend': statistics.mean(efficiency_trend),
            'channeling_analysis': self.detect_channeling_patterns(zone_id),
            'last_irrigation': recent_history[0]['timestamp'] if recent_history else None
        }
        
        # Generate insights
        if avg_efficiency < 0.4:
            performance['insight'] = 'Low efficiency - check for field capacity or drainage issues'
        elif avg_efficiency > 0.9:
            performance['insight'] = 'High efficiency - substrate may be too dry'
        else:
            performance['insight'] = 'Normal performance'
        
        return performance
    
    def update_zone_learning(self, zone_id: int, performance: Dict):
        """Update zone learning based on performance analysis."""
        # This method can be extended to adjust parameters based on learning
        pass
    
    def on_irrigation_complete(self, entity, attribute, old, new, kwargs):
        """Handle irrigation completion events from the main crop steering system."""
        # This can be used to automatically track irrigations from the main system
        pass
    
    def get_zone_intelligence_summary(self, zone_id: int) -> Dict:
        """Get a summary of learned intelligence for a zone."""
        profile = self.zone_profiles.get(zone_id, {})
        recent_performance = self.analyze_zone_performance(zone_id)
        
        return {
            'zone_id': zone_id,
            'field_capacity': profile.get('field_capacity'),
            'learning_status': 'learned' if profile.get('field_capacity') else 'needs_learning',
            'recent_performance': recent_performance,
            'efficiency_curve': profile.get('efficiency_curve', {}),
            'last_updated': profile.get('last_updated'),
            'recommended_action': self.get_zone_recommendation(zone_id)
        }
    
    def get_zone_recommendation(self, zone_id: int) -> str:
        """Get current recommendation for zone."""
        current_vwc = self.get_zone_vwc(zone_id)
        profile = self.zone_profiles.get(zone_id, {})
        
        if current_vwc is None:
            return "Check VWC sensor - no reading available"
        
        field_capacity = profile.get('field_capacity')
        if not field_capacity:
            return "Run field capacity detection first"
        
        if current_vwc >= field_capacity - 2:
            return "Near field capacity - avoid irrigation"
        elif current_vwc < 50:
            return "Low VWC - increase irrigation frequency"
        else:
            optimal_duration = self.calculate_optimal_shot_size(zone_id, current_vwc)
            return f"Optimal shot: {optimal_duration} seconds"
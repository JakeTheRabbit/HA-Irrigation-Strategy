"""
Base Async App for Crop Steering
Provides async-safe entity access methods for all crop steering modules.

Based on official AppDaemon documentation best practices:
- AppDaemon already handles async internally for most operations
- This class provides convenience wrappers and caching
- Handles both sync and async contexts appropriately
- Avoids common pitfalls like Task objects being returned

Note: AppDaemon documentation states it's "almost never" advantageous to use 
async programming in AppDaemon apps, but this base class provides safe patterns
for cases where it's needed (e.g., interfacing with async libraries).
"""

import appdaemon.plugins.hass.hassapi as hass
from typing import Any, Optional
import time
import os
import datetime as _dt

try:
    import requests as _requests
except Exception:  # pragma: no cover - requests is a declared global_module
    _requests = None


def _json_safe(obj):
    """Coerce a value into JSON-serialisable form for HA set_state (datetimes ->
    isoformat, unknown objects -> str). Stops the HTTP 400s when analytics attributes
    contain datetime objects or nested non-primitive data."""
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (_dt.datetime, _dt.date)):
        return obj.isoformat()
    # numpy scalars (np.float64 subclasses float, np.int64, np.bool_) pass the isinstance
    # check below but are NOT json-serialisable -> they were the source of the analytics
    # HTTP 400 spam (dryback uses scipy/numpy). Coerce to native Python via .item().
    # Native str/int/float/bool have no .item(), so this only catches numpy-likes.
    if hasattr(obj, "item") and not isinstance(obj, (str, bytes)):
        try:
            obj = obj.item()
        except Exception:
            return str(obj)
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        # NaN / Inf serialise to the literal NaN/Infinity, which is invalid JSON -> HA 400.
        # (dryback % is NaN before the first peak is detected.) Null them out.
        if obj != obj or obj == float("inf") or obj == float("-inf"):
            return None
        return obj
    if isinstance(obj, (str, int)) or obj is None:
        return obj
    return str(obj)


_RESERVED_ATTRS = {"last_updated", "last_changed", "last_reported",
                   "context", "entity_id", "state", "domain", "object_id"}


def _clean_attrs(attrs):
    """Sanitise an attributes dict for HA set_state: drop reserved keys (HA returns 400
    on last_updated/last_changed/etc.) and JSON-coerce the remaining values."""
    if not isinstance(attrs, dict):
        return attrs
    return {k: _json_safe(v) for k, v in attrs.items() if k not in _RESERVED_ATTRS}


class BaseAsyncApp(hass.Hass):
    """Base class with async-safe entity access methods."""
    
    def initialize(self):
        """Base initialization - subclasses should call super().initialize()"""
        self.entity_cache = {}
        self.cache_timeout = 60  # seconds
        
    def get_entity_value(self, entity_id: str, attribute: str = "state", default: Any = None) -> Any:
        """
        Synchronous wrapper for safe entity access.
        
        Based on AppDaemon best practices:
        - Uses run_coroutine() for async->sync conversion (AppDaemon recommended)
        - Handles both sync and async contexts properly
        - Caches results to minimize API calls
        
        Args:
            entity_id: The entity to get value from
            attribute: The attribute to get (default: "state")
            default: Default value if entity not found or error
            
        Returns:
            Entity value or default
        """
        # Check cache first
        cache_key = f"{entity_id}:{attribute}"
        if cache_key in self.entity_cache:
            cached_value, timestamp = self.entity_cache[cache_key]
            if time.time() - timestamp < self.cache_timeout:
                return cached_value
        
        try:
            # Check if we're already in an async context
            if hasattr(self, '_current_callback_is_async') and self._current_callback_is_async:
                # We're in async context, use direct await
                import inspect
                if inspect.iscoroutinefunction(inspect.currentframe().f_back.f_code):
                    self.log("Warning: get_entity_value called from async context. Use await self.get_state() directly.", level="WARNING")
            
            # For sync contexts, get the state directly (AppDaemon handles the async internally)
            if attribute == "state":
                result = self.get_state(entity_id)
            else:
                result = self.get_state(entity_id, attribute=attribute)

            # In an async callback the sync get_state() hands back an un-awaited coroutine
            # instead of a value. Close it (avoids "coroutine never awaited") and treat it as
            # a miss so the Supervisor-REST fallback below produces the real value.
            if hasattr(result, '__await__'):
                try:
                    result.close()
                except Exception:
                    pass
                result = None

            if result is not None and result not in ['unknown', 'unavailable']:
                # Cache the result
                self.entity_cache[cache_key] = (result, time.time())
                return result

            # AppDaemon's local state cache is blind/desynced for this entity (common for
            # rarely-changing switches, and for ANY read made from an async callback). Read it
            # straight from HA via the Supervisor proxy so the control switches + gate sensors
            # are always readable. Successful reads are cached like normal.
            rest = self._rest_state(entity_id, attribute)
            if rest is not None and rest not in ['unknown', 'unavailable']:
                self.entity_cache[cache_key] = (rest, time.time())
                return rest
            return default

        except Exception as e:
            self.log(f"Error getting {attribute} for {entity_id}: {e}", level="DEBUG")
            return default

    def _supervisor_token(self):
        """Supervisor token for the http://supervisor/core/api proxy (cached once)."""
        tok = getattr(self, "_sup_token_cache", "unset")
        if tok != "unset":
            return tok
        tok = os.environ.get("SUPERVISOR_TOKEN")
        if not tok:
            try:
                with open("/run/s6/container_environment/SUPERVISOR_TOKEN") as f:
                    tok = f.read().strip()
            except Exception:
                tok = None
        self._sup_token_cache = tok
        return tok

    def _rest_state(self, entity_id: str, attribute: str = "state"):
        """Read an entity's LIVE state straight from HA via the Supervisor proxy. Reliable
        even when AppDaemon's local state cache is blind or we're inside an async callback
        (where the sync get_state returns a coroutine). Returns the state string (or an
        attribute value), or None on any failure — callers fall back to their default."""
        if _requests is None:
            return None
        tok = self._supervisor_token()
        if not tok:
            return None
        try:
            r = _requests.get(
                f"http://supervisor/core/api/states/{entity_id}",
                headers={"Authorization": f"Bearer {tok}"},
                timeout=2,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            if attribute == "state":
                return data.get("state")
            return data.get("attributes", {}).get(attribute)
        except Exception:
            return None
    
    async def async_get_entity_value(self, entity_id: str, attribute: str = "state", default: Any = None) -> Any:
        """
        Async method to get entity state - use this in async callbacks.
        
        This follows AppDaemon best practices for async entity access.
        
        Args:
            entity_id: The entity to get value from
            attribute: The attribute to get (default: "state")
            default: Default value if entity not found or error
            
        Returns:
            Entity value or default
        """
        try:
            if attribute == "state":
                result = await self.get_state(entity_id)
            else:
                result = await self.get_state(entity_id, attribute=attribute)
            
            if result is not None and result not in ['unknown', 'unavailable']:
                # Update cache
                cache_key = f"{entity_id}:{attribute}"
                self.entity_cache[cache_key] = (result, time.time())
                return result
            return default
        except Exception as e:
            self.log(f"Async error getting {attribute} for {entity_id}: {e}", level="DEBUG")
            return default
    
    def get_float_value(self, entity_id: str, default: float = 0.0) -> float:
        """Get entity value as float with proper error handling."""
        value = self.get_entity_value(entity_id, default=default)
        
        try:
            # Handle async Task objects
            if hasattr(value, '__await__'):
                self.log(f"Async task detected for {entity_id}, using default: {default}", level="DEBUG")
                return default
                
            # Convert to float
            if value is None or value in ['unknown', 'unavailable', '']:
                return default
                
            return float(value)
            
        except (ValueError, TypeError):
            self.log(f"Could not convert {entity_id} value '{value}' to float, using default: {default}")
            return default
    
    def get_bool_value(self, entity_id: str, default: bool = False) -> bool:
        """Get entity value as boolean with proper error handling."""
        value = self.get_entity_value(entity_id, default="off" if not default else "on")
        
        try:
            # Handle async Task objects
            if hasattr(value, '__await__'):
                self.log(f"Async task detected for {entity_id}, using default: {default}", level="DEBUG")
                return default
                
            # Convert to bool
            if value is None:
                return default
                
            if isinstance(value, bool):
                return value
                
            if isinstance(value, str):
                return value.lower() in ['on', 'true', '1', 'yes']
                
            return bool(value)
            
        except Exception:
            return default
    
    def get_string_value(self, entity_id: str, default: str = "") -> str:
        """Get entity value as string with proper error handling."""
        value = self.get_entity_value(entity_id, default=default)
        
        try:
            # Handle async Task objects
            if hasattr(value, '__await__'):
                self.log(f"Async task detected for {entity_id}, using default: {default}", level="DEBUG")
                return default
                
            if value is None or value in ['unknown', 'unavailable']:
                return default
                
            return str(value)
            
        except Exception:
            return default
    
    def set_state(self, entity_id, state=None, **kwargs):
        """Override HA set_state to make every analytics publish robust: strip reserved
        attribute keys + JSON-coerce attribute values (else HA 400s), and coerce a missing
        state to 'unknown' (HA rejects a stateless POST). Preserves sync/async via super()."""
        try:
            if "attributes" in kwargs:
                kwargs["attributes"] = _clean_attrs(kwargs["attributes"])
        except Exception:
            pass
        # The state value itself can be a numpy scalar or NaN (dryback/analytics) -> json 400.
        if state is not None:
            state = _json_safe(state)
        if state is None:
            state = "unknown"
        return super().set_state(entity_id, state=state, **kwargs)

    def set_entity_value(self, entity_id: str, value: Any = None, **kwargs) -> None:
        """
        Synchronous wrapper for setting entity state.
        
        Based on AppDaemon best practices:
        - Uses set_state directly (AppDaemon handles async internally)
        - Clears cache after state change
        
        Args:
            entity_id: The entity to set
            value: The value to set
            **kwargs: Additional arguments for set_state
        """
        try:
            # Clear cache for this entity
            for key in list(self.entity_cache.keys()):
                if key.startswith(f"{entity_id}:"):
                    del self.entity_cache[key]
            
            # Many callers pass the value as a state= kwarg with no positional value;
            # accept both. Then sanitise attributes + drop reserved keys (else HA 400s).
            if value is None and "state" in kwargs:
                value = kwargs.pop("state")
            else:
                kwargs.pop("state", None)
            if "attributes" in kwargs:
                kwargs["attributes"] = _clean_attrs(kwargs["attributes"])
            self.set_state(entity_id, state=value, **kwargs)

        except Exception as e:
            self.log(f"Error setting {entity_id} to {value}: {e}", level="ERROR")
    
    async def async_set_entity_value(self, entity_id: str, value: Any = None, **kwargs) -> None:
        """
        Async method to set entity state - use this in async callbacks.
        
        Args:
            entity_id: The entity to set
            value: The value to set  
            **kwargs: Additional arguments for set_state
        """
        try:
            # Clear cache for this entity
            for key in list(self.entity_cache.keys()):
                if key.startswith(f"{entity_id}:"):
                    del self.entity_cache[key]
            
            if value is None and "state" in kwargs:
                value = kwargs.pop("state")
            else:
                kwargs.pop("state", None)
            if "attributes" in kwargs:
                kwargs["attributes"] = _clean_attrs(kwargs["attributes"])
            await self.set_state(entity_id, state=value, **kwargs)
        except Exception as e:
            self.log(f"Async error setting {entity_id}: {e}", level="ERROR")
    
    def entity_exists_sync(self, entity_id: str) -> bool:
        """Check if entity exists using synchronous method."""
        try:
            # Try to get the entity state
            state = self.get_entity_value(entity_id)
            # If we get a non-None value that's not a Task, entity exists
            return state is not None and not hasattr(state, '__await__')
        except Exception:
            return False
    
    def entity_exists(self, entity_id: str) -> bool:
        """Alias for entity_exists_sync for backward compatibility."""
        return self.entity_exists_sync(entity_id)
    
    def clear_cache(self, entity_id: Optional[str] = None) -> None:
        """Clear entity cache."""
        if entity_id:
            # Clear specific entity
            keys_to_delete = [k for k in self.entity_cache.keys() if k.startswith(f"{entity_id}:")]
            for key in keys_to_delete:
                del self.entity_cache[key]
        else:
            # Clear all cache
            self.entity_cache.clear()
    
    def call_service_sync(self, service: str, **kwargs) -> None:
        """
        Synchronous service call wrapper following AppDaemon best practices.
        
        Args:
            service: Service to call (e.g., "switch/turn_on")
            **kwargs: Service call parameters
        """
        try:
            # AppDaemon handles async conversion internally
            self.call_service(service, **kwargs)
        except Exception as e:
            self.log(f"Error calling service {service}: {e}", level="ERROR")
    
    async def call_service_async(self, service: str, **kwargs) -> None:
        """
        Async service call - use this in async callbacks.
        
        Args:
            service: Service to call (e.g., "switch/turn_on")
            **kwargs: Service call parameters
        """
        try:
            await self.call_service(service, **kwargs)
        except Exception as e:
            self.log(f"Async error calling service {service}: {e}", level="ERROR")
    async def async_step_load_yaml(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Load configuration from config.yaml."""
        config_path = os.path.join(self.hass.config.config_dir, "config.yaml")

        if not os.path.exists(config_path):
            return self.async_abort(reason="yaml_not_found")

        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)
        except yaml.YAMLError:
            return self.async_abort(reason="yaml_error")

        # Basic validation
        if not isinstance(config, dict) or "zones" not in config:
            return self.async_abort(reason="yaml_invalid_format")

        # Extract and validate entities
        entities_to_validate = []
        if hardware := config.get("irrigation_hardware"):
            entities_to_validate.extend([v for k, v in hardware.items() if v and isinstance(v, str) and "." in v])
        if env_sensors := config.get("environmental_sensors"):
            entities_to_validate.extend([v for k, v in env_sensors.items() if v and isinstance(v, str) and "." in v])
        
        zones_config = {}
        for zone in config.get("zones", []):
            zone_id = zone.get("zone_id")
            if not zone_id:
                continue
            
            zones_config[zone_id] = {
                "zone_number": zone_id,
                "zone_switch": zone.get("switch"),
            }
            entities_to_validate.append(zone.get("switch"))
            
            if sensors := zone.get("sensors"):
                zones_config[zone_id].update({
                    "vwc_front": sensors.get("vwc_front"),
                    "vwc_back": sensors.get("vwc_back"),
                    "ec_front": sensors.get("ec_front"),
                    "ec_back": sensors.get("ec_back"),
                })
                entities_to_validate.extend([v for k, v in sensors.items() if v and isinstance(v, str) and "." in v])

        missing_entities = [
            entity for entity in entities_to_validate if entity and not self.hass.states.get(entity)
        ]

        if missing_entities:
            return self.async_abort(
                reason="missing_entities",
                description_placeholders={"missing": "\n".join(missing_entities[:5])},
            )

        # Build data for config entry
        hardware_config = {**config.get("irrigation_hardware", {}), **config.get("environmental_sensors", {})}
        
        data = {
            "installation_mode": "yaml",
            "name": self._data.get(CONF_NAME, "Crop Steering System"),
            CONF_NUM_ZONES: len(zones_config),
            "zones": zones_config,
            "hardware": hardware_config,
            "config_yaml": config, # Store the full yaml config
        }
        
        await self._install_integration_files()
        return self.async_create_entry(
            title=data["name"],
            data=data,
        )
#!/usr/bin/env python3
"""
Zone Configuration Helper for Crop Steering System (DEPRECATED)

DEPRECATED: This tool is no longer needed! 
Use the Home Assistant GUI configuration instead:
- Settings → Devices & Services → Add Integration → Crop Steering
- Select "Advanced Setup" for full sensor configuration through the GUI
- No command line access required!

This script is kept for backwards compatibility only.
"""

import os
import sys
import re
from typing import Dict, List, Optional

def print_banner():
    """Print welcome banner."""
    print("=" * 60)
    print("🌱 Crop Steering System - Zone Configuration Helper")
    print("⚠️  DEPRECATED - Use GUI configuration instead!")
    print("=" * 60)
    print()
    print("This tool is deprecated. Please use the GUI configuration:")
    print("Settings → Devices & Services → Add Integration → Crop Steering")
    print("Select 'Advanced Setup' for full sensor configuration")
    print()
    
    response = input("Continue with deprecated tool? (y/n): ")
    if response.lower() != 'y':
        print("Exiting. Please use the GUI configuration instead.")
        sys.exit(0)
    print()

def get_user_input(prompt: str, default: str = "", valid_options: List[str] = None) -> str:
    """Get user input with optional default and validation."""
    if default:
        prompt = f"{prompt} [{default}]: "
    else:
        prompt = f"{prompt}: "
    
    while True:
        value = input(prompt).strip()
        if not value and default:
            value = default
        
        if valid_options:
            if value in valid_options:
                return value
            else:
                print(f"Invalid option. Please choose from: {', '.join(valid_options)}")
        else:
            return value

def configure_zones() -> Dict:
    """Interactive zone configuration."""
    print("🔧 Zone Configuration")
    print("-" * 40)
    
    # Ask for number of zones
    num_zones = get_user_input(
        "How many irrigation zones do you have? (1-6)",
        "1",
        ["1", "2", "3", "4", "5", "6"]
    )
    num_zones = int(num_zones)
    
    zones = {}
    
    for zone_num in range(1, num_zones + 1):
        print(f"\n📍 Configuring Zone {zone_num}")
        print("-" * 30)
        
        # Zone switch
        zone_switch = get_user_input(
            f"Enter the entity ID for Zone {zone_num} valve/switch",
            f"switch.zone_{zone_num}_valve"
        )
        
        # VWC sensors
        print(f"\n💧 Zone {zone_num} Moisture Sensors (VWC)")
        vwc_front = get_user_input(
            "Enter front VWC sensor entity ID (or press Enter to skip)",
            f"sensor.z{zone_num}_vwc_front"
        )
        
        vwc_back = get_user_input(
            "Enter back VWC sensor entity ID (or press Enter to skip)",
            f"sensor.z{zone_num}_vwc_back"
        )
        
        # EC sensors
        print(f"\n⚡ Zone {zone_num} Nutrient Sensors (EC)")
        ec_front = get_user_input(
            "Enter front EC sensor entity ID (or press Enter to skip)",
            f"sensor.z{zone_num}_ec_front"
        )
        
        ec_back = get_user_input(
            "Enter back EC sensor entity ID (or press Enter to skip)",
            f"sensor.z{zone_num}_ec_back"
        )
        
        # Validate zone has required sensors
        if not (vwc_front or vwc_back):
            print(f"⚠️  Warning: Zone {zone_num} has no VWC sensors configured!")
            if get_user_input("Continue anyway? (y/n)", "n", ["y", "n"]) == "n":
                continue
        
        if not (ec_front or ec_back):
            print(f"⚠️  Warning: Zone {zone_num} has no EC sensors configured!")
            if get_user_input("Continue anyway? (y/n)", "n", ["y", "n"]) == "n":
                continue
        
        zones[zone_num] = {
            'switch': zone_switch,
            'vwc_front': vwc_front,
            'vwc_back': vwc_back,
            'ec_front': ec_front,
            'ec_back': ec_back
        }
    
    return zones

def update_env_file(zones: Dict, env_file: str = "crop_steering.env"):
    """Update crop_steering.env with zone configuration."""
    print(f"\n📝 Updating {env_file}...")
    
    # Read existing file
    with open(env_file, 'r') as f:
        lines = f.readlines()
    
    # Update zone configuration
    new_lines = []
    zone_section_start = False
    zone_section_end = False
    
    for line in lines:
        # Skip existing zone configuration lines
        if re.match(r'^ZONE_\d+_(SWITCH|VWC_FRONT|VWC_BACK|EC_FRONT|EC_BACK)=', line):
            if not zone_section_start:
                zone_section_start = True
                # Add new zone configuration
                for zone_num, config in sorted(zones.items()):
                    new_lines.append(f"ZONE_{zone_num}_SWITCH={config['switch']}\n")
                for zone_num, config in sorted(zones.items()):
                    if config['vwc_front']:
                        new_lines.append(f"ZONE_{zone_num}_VWC_FRONT={config['vwc_front']}\n")
                    if config['vwc_back']:
                        new_lines.append(f"ZONE_{zone_num}_VWC_BACK={config['vwc_back']}\n")
                for zone_num, config in sorted(zones.items()):
                    if config['ec_front']:
                        new_lines.append(f"ZONE_{zone_num}_EC_FRONT={config['ec_front']}\n")
                    if config['ec_back']:
                        new_lines.append(f"ZONE_{zone_num}_EC_BACK={config['ec_back']}\n")
            continue
        else:
            if zone_section_start and not zone_section_end:
                zone_section_end = True
        
        new_lines.append(line)
    
    # Write updated file
    with open(env_file, 'w') as f:
        f.writelines(new_lines)
    
    print("✅ Zone configuration updated successfully!")

def main():
    """Main function."""
    print_banner()
    
    # Check if crop_steering.env exists
    if not os.path.exists("crop_steering.env"):
        print("❌ Error: crop_steering.env not found!")
        print("Please run this script from your Home Assistant config directory.")
        sys.exit(1)
    
    # Configure zones
    zones = configure_zones()
    
    # Show summary
    print("\n📊 Zone Configuration Summary")
    print("-" * 40)
    for zone_num, config in sorted(zones.items()):
        print(f"\nZone {zone_num}:")
        print(f"  Switch: {config['switch']}")
        print(f"  VWC Sensors: {config['vwc_front'] or 'None'}, {config['vwc_back'] or 'None'}")
        print(f"  EC Sensors: {config['ec_front'] or 'None'}, {config['ec_back'] or 'None'}")
    
    # Confirm before updating
    if get_user_input("\nUpdate crop_steering.env with this configuration? (y/n)", "y", ["y", "n"]) == "y":
        update_env_file(zones)
        print("\n🎉 Configuration complete!")
        print("Next steps:")
        print("1. Restart Home Assistant")
        print("2. The Crop Steering integration will load your zone configuration")
        print("3. All zone entities will be created automatically")
    else:
        print("\n❌ Configuration cancelled.")

if __name__ == "__main__":
    main()
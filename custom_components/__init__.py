"""Marks custom_components as a regular package so a real Home Assistant test core
(pytest-homeassistant-custom-component) loads THIS repo's integration instead of its own
bundled namespace. HACS and manual installs copy only crop_steering/, so this is never shipped."""

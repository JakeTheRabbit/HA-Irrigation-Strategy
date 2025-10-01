# Documentation Migration Notice

This document maps the old documentation structure to the new organized layout for users upgrading or referencing previous versions.

## File Mapping

### Moved Files
- `ENTITIES.md` → `docs/technical/entity-reference.md`
- `docs/installation_guide.md` → `docs/user-guides/02-installation.md`
- `docs/troubleshooting.md` → `docs/user-guides/05-troubleshooting.md` (enhanced)
- `docs/LLM_INTEGRATION.md` → `docs/advanced-features/llm-integration.md` (rewritten)
- `docs/GPT5_SETUP_GUIDE.md` → Merged into `docs/advanced-features/llm-integration.md`

### Removed Files (Content Merged or Obsolete)
- `LLM_INTEGRATION_PLAN.md` - Development planning document, obsolete
- `INTELLIGENT_SYSTEM_ARCHITECTURE.md` - Merged into technical documentation
- `STATE_PERSISTENCE_SYSTEM.md` - Technical details moved to architecture docs
- `README_OLD.md` - Backup of old README, removed after successful migration
- `SMART_LEARNING_SETUP.md` - Will be replaced with comprehensive advanced features guide

### Development Files (Moved to docs/development/)
- `github_issue_gui_config.md`
- `github_issue_refactoring.md`  
- `REFACTORING_PROPOSAL.md`

## New Documentation Structure

```
docs/
├── user-guides/
│   ├── 01-getting-started.md  # First-time user journey
│   ├── 02-installation.md     # Complete installation guide
│   ├── 03-configuration.md    # Configuration and setup
│   ├── 04-daily-operation.md  # Day-to-day usage
│   └── 05-troubleshooting.md  # Comprehensive problem solving
├── advanced-features/
│   ├── llm-integration.md     # GPT-5 AI enhancement setup
│   └── smart-learning-system.md # Adaptive optimization
├── technical/
│   ├── entity-reference.md    # Complete entity documentation
│   ├── service-reference.md   # Service calls & events
│   └── architecture.md        # System design details
├── examples/
│   ├── automation-examples.md # Example automations
│   └── dashboard-examples.md  # Dashboard configurations
└── development/               # Internal development docs
    ├── github_issue_gui_config.md
    ├── github_issue_refactoring.md
    └── REFACTORING_PROPOSAL.md
```

## Content Changes

### README.md Transformation
- **Old**: 1,428 lines with overwhelming technical detail
- **New**: 254 lines with clear user journey and progressive complexity paths
- **Focus**: Landing page that guides users to appropriate documentation based on experience level

### Installation Documentation
- **Old**: Single large installation guide with mixed complexity
- **New**: Three progressive guides:
  - Quickstart for immediate results
  - Complete guide for full automation
  - Hardware guide for physical setup

### User Experience Improvements
- **Clear learning paths**: Beginner → Intermediate → Advanced
- **Progressive disclosure**: Users see only relevant complexity
- **Better navigation**: Logical grouping and cross-references
- **Mobile-friendly**: Shorter pages, scannable content

### Technical Documentation
- **Consolidated**: Related information grouped together
- **Enhanced**: More comprehensive troubleshooting and diagnostics
- **Practical**: Focus on real-world usage scenarios
- **Updated**: Reflects current system capabilities and best practices

## Migration for Existing Users

### If You're Using Old Documentation Links
1. Check this mapping to find the new location
2. New documentation is more comprehensive and up-to-date
3. Bookmark the new structure for future reference

### If You Have Local Copies
- Old documentation may contain outdated information
- Recommend using new documentation for accuracy
- New guides include lessons learned from community feedback

### If You're Contributing
- Use new structure for all documentation contributions
- Development-related content goes in `docs/development/`
- User-facing content follows the new user journey organization

## Benefits of New Structure

1. **Better User Experience**: Clear paths from beginner to expert
2. **Reduced Overwhelm**: Information appropriate to user's current needs
3. **Improved Maintenance**: Logical organization makes updates easier
4. **Enhanced Discoverability**: Related information grouped together
5. **Mobile Optimization**: Shorter, focused pages work better on all devices

---

**Need Help?** If you can't find information that was in the old documentation, please [open an issue](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/issues) and we'll help locate it in the new structure.
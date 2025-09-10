# Documentation Migration Notice

This document maps the old documentation structure to the new organized layout for users upgrading or referencing previous versions.

## File Mapping

### Moved Files
- `ENTITIES.md` → `docs/technical/entity-reference.md`
- `docs/installation_guide.md` → Split into:
  - `docs/installation/quickstart.md`
  - `docs/installation/complete-guide.md`
  - `docs/installation/hardware-setup.md`
- `docs/troubleshooting.md` → `docs/user-guides/troubleshooting.md` (enhanced)
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
├── installation/
│   ├── quickstart.md          # 15-minute setup (NEW)
│   ├── complete-guide.md      # Full installation with AppDaemon (ENHANCED)
│   └── hardware-setup.md      # Physical hardware guide (NEW)
├── user-guides/
│   ├── getting-started.md     # First-time user journey (NEW)
│   ├── daily-operation.md     # Day-to-day usage (NEW)
│   ├── dashboard-guide.md     # UI setup and monitoring (NEW)
│   └── troubleshooting.md     # Comprehensive problem solving (ENHANCED)
├── advanced-features/
│   ├── llm-integration.md     # AI enhancement setup (REWRITTEN)
│   ├── smart-learning.md      # Adaptive optimization (PLANNED)
│   └── automation-advanced.md # Complex scenarios (PLANNED)
├── technical/
│   ├── entity-reference.md    # Complete entity docs (MOVED)
│   ├── services-api.md        # Service calls & events (PLANNED)
│   ├── architecture.md        # System design (PLANNED)
│   └── configuration.md       # Advanced settings (PLANNED)
├── examples/
│   ├── configurations/        # Sample configs (PLANNED)
│   └── automations/          # Example automations (PLANNED)
└── development/              # Internal development docs
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
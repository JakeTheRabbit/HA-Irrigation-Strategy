# Contributing to HA-Irrigation-Strategy

Thank you for your interest in contributing to the Intelligent Crop Steering System for Home Assistant! We welcome contributions from the community.

## 🤝 How to Contribute

### Bug Reports
- Use GitHub Issues to report bugs
- Include your Home Assistant version, sensor types, and system configuration
- Provide logs from AppDaemon or Home Assistant when relevant
- Describe expected vs actual behavior

### Feature Requests
- Check existing issues to avoid duplicates
- Describe the use case and benefit to other users
- Consider implementation complexity and maintenance burden

### Code Contributions
- Fork the repository and create a feature branch
- Follow the existing code style and patterns
- Test your changes thoroughly
- Update documentation if needed
- Submit a pull request with a clear description

## 🔧 Development Setup

### Prerequisites
- Home Assistant 2024.3.0+
- AppDaemon 4.4.0+ (for automation features)
- Python 3.11+ development environment
- Test irrigation hardware or simulation setup

### Local Development
```bash
# Clone your fork
git clone https://github.com/yourusername/HA-Irrigation-Strategy.git
cd HA-Irrigation-Strategy

# Set up development environment
# Copy to your HA custom_components directory for testing
cp -r custom_components/crop_steering /config/custom_components/

# Copy AppDaemon apps for testing
cp -r appdaemon/apps/crop_steering /config/appdaemon/apps/
```

## 📋 Code Guidelines

### Python Code Style
- Follow PEP 8 style guidelines
- Use meaningful variable and function names
- Add docstrings for all public functions
- Include type hints where appropriate

### Home Assistant Integration
- Follow HA integration best practices
- Use async/await properly
- Handle entity state validation gracefully
- Implement proper error handling

### AppDaemon Apps
- Use the AppDaemon logging system
- Handle sensor unavailability gracefully
- Implement proper error recovery
- Document configuration parameters

## 🧪 Testing

### Manual Testing
- Test with real hardware when possible
- Use the built-in test helper entities for simulation
- Validate all installation steps work correctly
- Test error conditions and recovery

### Safety Testing
- Verify safety interlocks prevent damage
- Test emergency stop functionality
- Validate sensor failure handling
- Confirm irrigation limits are respected

## 📖 Documentation

### When to Update Documentation
- New features require user guide updates
- Configuration changes need example updates
- Breaking changes require migration guides
- Bug fixes may need troubleshooting updates

### Documentation Style
- Use clear, concise language
- Include practical examples
- Provide step-by-step instructions
- Consider users of all experience levels

## 🚀 Release Process

### Versioning
We use semantic versioning (MAJOR.MINOR.PATCH):
- MAJOR: Breaking changes requiring user action
- MINOR: New features that are backward compatible
- PATCH: Bug fixes and minor improvements

### Release Checklist
- [ ] All tests pass
- [ ] Documentation updated
- [ ] Version numbers updated
- [ ] Changelog updated
- [ ] Migration guide (if needed)

## 🙋‍♀️ Getting Help

### Questions
- Check the documentation first
- Search existing GitHub issues
- Post in Home Assistant Community forums
- Create a GitHub issue for project-specific questions

### Discussion
- Use GitHub Discussions for general topics
- Join Home Assistant Discord for real-time help
- Share success stories and improvements

## 📜 License

By contributing to this project, you agree that your contributions will be licensed under the MIT License.

## 🏆 Recognition

Contributors are recognized in:
- GitHub contributor list
- Release notes for significant contributions
- Documentation acknowledgments

Thank you for helping make intelligent crop steering accessible to everyone! 🌱
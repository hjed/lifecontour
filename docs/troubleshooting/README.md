# Troubleshooting Documentation

This directory contains troubleshooting guides and solutions for common issues encountered during development and deployment of the Personal Management System.

## 📋 Available Guides

### Docker and Development Environment

- **[Docker Development Environment](docker-development.md)**
  - Complete guide to setting up and using the Docker-based development environment
  - Service URLs, commands, configuration, and debugging tips
  - Recommended for new developers and complete integration testing

- **[Docker Fixes](docker-fixes.md)**
  - Solutions to common Docker-related issues
  - Frontend build failures, permission errors, CI/CD Docker problems
  - Performance optimization and security best practices

### CI/CD and Testing

- **[CI Integration Tests Fix](ci-integration-tests-fix.md)**
  - Backend integration test configuration for CI environments
  - Pytest markers, database setup, and test separation
  - Solutions for CI test failures and environment mismatches

- **[Frontend CI Fixes](frontend-ci-fixes.md)**
  - Frontend CI pipeline issues and solutions
  - Jest coverage configuration, Prettier formatting fixes
  - Test coverage strategies for React components

## 🚀 Quick Reference

### Common Issues and Solutions

| Issue | Guide | Quick Fix |
|-------|-------|-----------|
| Frontend container won't start | [Docker Fixes](docker-fixes.md#frontend-docker-build-issues) | Check start.sh script and NODE_ENV |
| Docker build fails in CI | [Docker Fixes](docker-fixes.md#cicd-docker-issues) | Install all dependencies for builds |
| Integration tests fail in CI | [CI Integration Tests](ci-integration-tests-fix.md) | Use proper pytest markers |
| Jest coverage too low | [Frontend CI Fixes](frontend-ci-fixes.md) | Add component tests |
| Permission denied on files | [Docker Fixes](docker-fixes.md#precommit-hook-issues) | Fix file ownership or exclude from hooks |
| Port conflicts | [Docker Development](docker-development.md#debugging-and-troubleshooting) | Check port usage with lsof |

### Development Environment Setup

1. **New to the project?** Start with [Docker Development Environment](docker-development.md)
2. **CI/CD issues?** Check [CI Integration Tests](ci-integration-tests-fix.md) and [Frontend CI Fixes](frontend-ci-fixes.md)
3. **Docker problems?** See [Docker Fixes](docker-fixes.md) for common solutions

## 🔧 Getting Help

### Before Creating New Issues

1. **Check these guides first** - Most common issues are documented here
2. **Search existing documentation** - Use the search function in your editor
3. **Check logs** - Use `./scripts/dev.sh docker-logs <service>` for debugging
4. **Verify environment** - Ensure Docker, Node.js, and Python versions match requirements

### Debugging Commands

```bash
# Check service status
./scripts/dev.sh docker-status

# View logs for specific service
./scripts/dev.sh docker-logs <service-name>

# Execute commands in container
./scripts/dev.sh docker-exec <service-name> <command>

# Run tests
./scripts/dev.sh test

# Check code quality
./scripts/dev.sh lint
```

### Creating New Troubleshooting Documentation

When you solve a new issue:

1. **Document the problem** - Include error messages and symptoms
2. **Explain the root cause** - Help others understand why it happened
3. **Provide the solution** - Step-by-step fix with commands/code
4. **Add verification steps** - How to confirm the fix worked
5. **Link related documentation** - Reference relevant guides

Follow the existing format in these guides for consistency.

## 📚 Related Documentation

- [Architecture Overview](../architecture.md) - System design and patterns
- [AI Guidelines](../ai-guidelines.md) - Development guidelines
- [Code Quality Standards](../code-quality-standards.md) - Development standards
- [CI/CD Setup](../ci-cd-setup.md) - Continuous integration configuration

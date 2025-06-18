# Frontend Quality Checks

This document outlines the code quality tools and processes for the frontend codebase.

## Quick Commands

```bash
# Run all quality checks
pnpm quality:check

# Fix all auto-fixable issues
pnpm quality:fix

# Individual checks
pnpm format:check     # Prettier formatting check
pnpm format           # Auto-format code
pnpm lint             # ESLint check
pnpm lint:fix         # Auto-fix ESLint issues
pnpm type-check       # TypeScript type checking
```

## Quality Tools

### 1. Prettier (Code Formatting)

- **Purpose**: Consistent code formatting across the codebase
- **Config**: `.prettierrc` and `.prettierignore`
- **Auto-fix**: `pnpm format`
- **Check**: `pnpm format:check`

### 2. ESLint (Code Linting)

- **Purpose**: Code quality, best practices, and error prevention
- **Config**: `eslint.config.js`
- **Auto-fix**: `pnpm lint:fix`
- **Check**: `pnpm lint`

### 3. TypeScript (Type Checking)

- **Purpose**: Static type checking and compile-time error detection
- **Config**: `tsconfig.json`
- **Check**: `pnpm type-check`

## CI/CD Integration

Quality checks run automatically in GitHub Actions:

- **Prettier**: Formatting validation
- **ESLint**: Linting validation
- **TypeScript**: Type checking
- **Tests**: Unit and E2E test execution

## Development Workflow

1. **Before committing**: Run `pnpm quality:check`
2. **Fix issues**: Run `pnpm quality:fix` for auto-fixable issues
3. **Manual fixes**: Address any remaining TypeScript or complex ESLint issues
4. **Verify**: Run `pnpm quality:check` again to ensure all issues are resolved

## Common Issues

### Prettier Formatting

- **Issue**: Code not formatted consistently
- **Fix**: Run `pnpm format`
- **Prevention**: Use editor integration (VS Code Prettier extension)

### ESLint Errors

- **Issue**: Code quality violations
- **Fix**: Run `pnpm lint:fix` for auto-fixable issues
- **Manual**: Address complex issues following ESLint suggestions

### TypeScript Errors

- **Issue**: Type errors or missing type annotations
- **Fix**: Add proper types, fix type mismatches
- **Help**: Use `pnpm type-check` for detailed error messages

## Editor Integration

### VS Code

Recommended extensions:

- **Prettier**: Auto-format on save
- **ESLint**: Real-time linting feedback
- **TypeScript**: Built-in type checking

### Settings

Add to VS Code settings.json:

```json
{
  "editor.formatOnSave": true,
  "editor.defaultFormatter": "esbenp.prettier-vscode",
  "editor.codeActionsOnSave": {
    "source.fixAll.eslint": true
  }
}
```

## Quality Standards

- **Zero tolerance**: All quality checks must pass before merging
- **Consistency**: Use automated tools rather than manual style decisions
- **Maintainability**: Prioritize readable, well-typed code
- **Performance**: Address performance-related ESLint warnings

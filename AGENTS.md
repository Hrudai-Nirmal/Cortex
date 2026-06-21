# Cortex Working Agreements

## Naming
- Use camelCase variables/functions, PascalCase classes/components, UPPER_SNAKE constants, and kebab-case files.
- Name functions with verb+noun and booleans with is/has/can/should prefixes.
- Avoid vague names such as data, res, fn, temp, and x.

## Structure and Documentation
- Maintain `context.md` after every material change.
- Add a file-level comment block to non-trivial source files.
- Comment why, not what, and document every public function with JSDoc or a Python docstring.

## Reliability
- Validate inputs at entry points and handle null, empty, network, and cancellation cases.
- Wrap asynchronous external operations with explicit error handling and structured logging.
- Do not use `console.log` in production code.
- Fix root causes instead of masking invalid state with fallbacks.

## Completion
- Run existing tests and builds.
- Review naming, dead code, error handling, and documentation.
- Use Conventional Commits when committing.

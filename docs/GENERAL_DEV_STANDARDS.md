# General Software Development Standards

This document outlines the standard development practices and philosophies to be applied across projects. It serves as a baseline for maintaining high code quality, reliability, and maintainability.

## 1. Core Philosophy: The "Four Pillars" of Deliverables
Code is not the only deliverable. A complete feature implementation consists of four synchronized elements. If any are missing or out of sync, the work is **incomplete**.

1.  **Source Code**: The actual implementation.
2.  **Tests**: Automated verification code (Unit, Integration, E2E).
3.  **Documentation**: Updated Readme, Architecture docs, API specs.
4.  **Configuration Samples**: Updated `config.example.yaml` or `.env.example`.

> **Rule:** "Code, Tests, Docs, and Configs must change atomically."  
> Never commit a code change without the corresponding updates to tests, docs, and config samples.

## 2. Testing Strategy
**"Test code is part of the product."**

-   **Test-First Mindset**: Ideally, write the test before or immediately parallel to the code.
-   **Mandatory Coverage**:
    -   **Happy Path**: Verify the feature works as expected.
    -   **Error Cases**: Verify the system handles invalid input, network failures, and edge cases gracefully.
-   **Continuous Maintenance**: Tests are not "write once, forget". When requirements change, tests must be updated immediately. Broken tests are a "stop the line" emergency.

### Recommended Layers:
*   **Unit Tests**: Fast, isolated tests for logic (Business Logic, Utils).
*   **Integration Tests**: Verify interactions between components (API endpoints, DB).
*   **E2E/UI Tests**: Verify the user journey (Browser automation like Playwright/Cypress).

## 3. Documentation & Configuration
**"Documentation is a Living Artifact."**

-   **Keep it Fresh**: Update docs *while* you dev, not after. Stale docs are worse than no docs.
-   **Configuration Management**:
    -   **Never commit real secrets/credentials.**
    -   **ALWAYS maintain a `config.sample.yaml`, `.env.example`, or `settings.defaults.json`.**
    -   If you add a new configuration key to the app, you **MUST** add it to the sample file with a description.

## 4. Development Workflow (The "PDCA" Cycle)
1.  **Plan**: Understand the requirement. Break it down. Check existing tests.
2.  **Implement**: Write the code.
3.  **Verify**: Run tests. Run UI checks. Fix regressions.
4.  **Refine**: Refactor. Lint. Format. Update docs.
5.  **Commit**: Atomic commits with clear messages.

## 5. Code Quality
-   **Boy Scout Rule**: Always leave the code cleaner than you found it.
-   **No "Magic"**: Avoid magic numbers, hardcoded paths, or implicit dependencies. Use constants and config files.
-   **Linting**: Ensure all linters and formatters pass before requesting review.

---
*Use this template as a starting point for your project's `DEVELOPMENT_POLICY.md`.*

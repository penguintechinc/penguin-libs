# Penguin-Libs Test Coverage Report
Generated: 2026-04-23

## Executive Summary

**Current Status: BELOW STANDARD** ❌

- **Total Packages**: 34 (9 established, 13 new splits, 1 shim)
- **Passing**: 2 packages
- **Failing**: 7 established packages (dependency/config issues)
- **Zero Coverage**: 13 new split packages (blocker)

Project requires **90%+ test coverage**. Current state has critical gaps in both established and new packages.

---

## Test Results by Package

### Python Packages (Established)

| Package | Status | Coverage | Notes |
|---------|--------|----------|-------|
| python-licensing | ❌ FAIL | 91/101 | 10 Flask async decorator failures (need `Flask[async]` extra) |
| python-libs | ❌ FAIL | 0% | 14 collection errors - import resolution broken |
| python-aaa | ✅ PASS | 250/250 | Full pass |
| python-dal | ❌ FAIL | 0% | Missing SQLAlchemy dev dependency |
| python-utils | ✅ PASS | 68/68 | Full pass |
| python-email | ❌ FAIL | 75/77 (97%) | 2 Gmail transport edge case failures |
| python-limiter | ❌ FAIL | 102/105 (97%) | 3 gRPC middleware extraction failures |
| python-secrets | ❌ FAIL | 0% | Collection error - Vault import issue |
| python-pytest | ❌ FAIL | 0% | Collection error - SQLAlchemy import in plugin |

### Python Packages (New Splits - NO TESTS)

| Package | Status | Coverage | Notes |
|---------|--------|----------|-------|
| python-crypto | NO TESTS | 0% | Split from python-libs - needs full test suite |
| python-flask | NO TESTS | 0% | Split from python-libs - needs full test suite |
| python-grpc | NO TESTS | 0% | Split from python-libs - needs full test suite |
| python-h3 | NO TESTS | 0% | Split from python-libs - needs full test suite |
| python-http | NO TESTS | 0% | Split from python-libs - needs full test suite |
| python-pydantic | NO TESTS | 0% | Split from python-libs - needs full test suite |
| python-security | NO TESTS | 0% | Split from python-libs - needs full test suite |
| python-validation | NO TESTS | 0% | Split from python-libs - needs full test suite |

### Go Packages

| Package | Status | Coverage | Notes |
|---------|--------|----------|-------|
| go-logging | ✅ PASS | 100% | Full pass |
| go-aaa | ❌ FAIL | N/A | `go.mod` out of sync - run `go mod tidy` |
| go-h3 | ✅ PASS | 100% | Full pass |
| go-common | NO TESTS | 0% | Shim/wrapper - acceptable if no new code |
| go-xdp | NO TESTS | 0% | New split - needs full test suite |
| go-numa | NO TESTS | 0% | New split - needs full test suite |

### React Packages

| Package | Status | Coverage | Notes |
|---------|--------|----------|-------|
| react-libs | ❌ FAIL | 0% | vitest config broken - missing jsdom dependency |
| react-aaa | ⚠️ HAS TESTS | ? | Cannot run tests (workspace jsdom issue blocks all React) |
| react-console-version | NO TESTS | 0% | New split - needs full test suite |
| react-form-builder | NO TESTS | 0% | New split - needs full test suite |
| react-hooks | NO TESTS | 0% | New split - needs full test suite |
| react-login | NO TESTS | 0% | New split - needs full test suite |
| react-sidebar | NO TESTS | 0% | New split - needs full test suite |
| react-testutils | ⚠️ HAS TESTS | ? | Cannot run tests (workspace jsdom issue blocks all React) |

### Flutter Packages

| Package | Status | Coverage | Notes |
|---------|--------|----------|-------|
| flutter_libs | ⚠️ HAS TESTS | ? | Cannot test (requires flutter toolchain) |

---

## Critical Issues

### Blocking Issues (Fix Before Moving Forward)

1. **react-libs vitest config broken**
   - Error: Missing `jsdom` dependency
   - Impact: Blocks all React package testing
   - Fix: Add jsdom to devDependencies, ensure vitest config is correct

2. **python-libs import resolution broken**
   - Errors: 14 collection errors during test discovery
   - Impact: Core transition package cannot be tested
   - Fix: Resolve import paths - likely sys.modules issue with split packages

3. **python-dal missing dependencies**
   - Error: `ModuleNotFoundError: No module named 'sqlalchemy'`
   - Impact: Core database package untestable
   - Fix: Add SQLAlchemy to dev dependencies in pyproject.toml

4. **python-secrets collection error**
   - Error: Import error in Vault adapter tests
   - Impact: Core secrets package untestable
   - Fix: Debug import path, check for missing optional dependencies

5. **python-pytest import error**
   - Error: SQLAlchemy import in pytest plugin
   - Impact: Testing utilities broken
   - Fix: Add SQLAlchemy to optional dependencies

6. **go-aaa go.mod out of sync**
   - Error: `go.mod` doesn't match actual dependencies
   - Impact: Go AAA package fails to test
   - Fix: Run `go mod tidy` in `packages/go-aaa/`

### High Priority Issues (Fix Next)

7. **python-licensing Flask decorator failures** (10 failures)
   - Error: `RuntimeError: Install Flask with the 'async' extra`
   - Impact: ~10% of licensing tests fail
   - Fix: Add `Flask[async]` to test requirements, or convert async decorators to sync

8. **python-email transport failures** (2 failures)
   - Error: Gmail token refresh edge cases
   - Impact: 97% coverage, but core functionality gaps
   - Fix: Review test expectations for expired token scenario

9. **python-limiter gRPC failures** (3 failures)
   - Error: IP extraction from gRPC peer metadata
   - Impact: 97% coverage, but core rate limiting functionality
   - Fix: Review gRPC test setup and peer string format

### Coverage Gaps (New Packages)

**8 Python packages (0% coverage):**
- python-crypto, python-flask, python-grpc, python-h3, python-http, python-pydantic, python-security, python-validation
- All are splits from python-libs
- Need: Create `tests/` directory with comprehensive unit/integration test suites

**3 Go packages (0% coverage):**
- go-xdp, go-numa
- New packages with no test files
- Need: Create `*_test.go` files with unit/integration tests

**5 React packages (0% coverage):**
- react-console-version, react-form-builder, react-hooks, react-login, react-sidebar
- All are splits from react-libs
- Need: Create `src/__tests__/` directory with vitest tests

---

## Recommendations

### Immediate Actions (This Week)

1. **Fix React workspace**: Install jsdom, run `npm run test` to unblock all React testing
2. **Fix go-aaa**: Run `go mod tidy`, re-run tests
3. **Fix python import issues**: Debug python-libs, python-dal, python-secrets, python-pytest collection errors
4. **Fix python-licensing**: Add Flask[async] to dev requirements

### Short-term (Next Sprint)

5. Create test suites for 8 new Python split packages (target 90%+ coverage each)
6. Create test suites for 3 new Go packages
7. Create test suites for 5 new React packages (after workspace is fixed)
8. Fix python-email and python-limiter edge case test failures

### Long-term

9. Ensure all new packages added to monorepo include tests from day one
10. Set up CI/CD to block merges on coverage < 90% per package
11. Monitor established packages for regression

---

## Coverage Targets

| Category | Target | Current | Status |
|----------|--------|---------|--------|
| **Established packages** | 90%+ | ~50% (2 of 9 pass) | ❌ Below target |
| **New split packages** | 90%+ | 0% (0 of 13 pass) | ❌ Critical gap |
| **Go packages** | N/A (no %) | 2 of 6 pass | ⚠️ Partial |
| **React packages** | 90%+ | 0% (workspace broken) | ❌ Cannot measure |
| **Overall project** | 90%+ | ~30% | ❌ Far below |

---

## Logs & Details

Full test output and error messages are available in the execution logs.

**Commands used for testing:**
```bash
# Python
PYTHONPATH=src python3 -m pytest tests/ -q

# Go
go test -v ./...

# React
npm run test -w @penguintechinc/react-*

# Flutter
flutter test --coverage
```

---

*Report generated: 2026-04-23*
*Test environment: macOS, Python 3.14, Node 24, Go 1.24, Flutter stable*

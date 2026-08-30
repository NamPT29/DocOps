# SonarCloud remediation strategy

> Task: Turn the current SonarCloud report into a trustworthy, enforceable quality signal without weakening the application's security or disrupting the local/Caddy/Cloudflare deployment.
>
> Evidence read at `bfd0ffb79a8f1ad6f251192c4f4e516fb29c96bc` on 2026-08-30. The worktree has an unstaged `sonar-project.properties` change. GitNexus graph data is two commits behind HEAD, so graph results below are advisory and all named code was source-read. The GitNexus provenance helper could not create its schema-2 snapshot in this Windows sandbox (`spawnSync git EPERM`); re-anchor the plan with that helper before implementation on a host where it can run.

## 1. Objective

Make SonarCloud measure deployable application code, run one deterministic analysis method, and address the genuine network-exposure finding. Do not mass-edit code merely to reduce a dashboard count.

## 2. Current behaviour

- [verified] SonarCloud's automatic analysis ran about four hours ago on `main`, reports 40k lines, 754 open issues, and a failed Quality Gate. New Code has 64 issues and a Security Rating of D; duplication is 0.48% against a 3% threshold and coverage has no data.
- [verified] Of the overall report, 91 are Security (1 Blocker, 77 High), 127 Reliability, and 657 Maintainability. The sole shown Blocker is `run_server.py:6`, which binds Uvicorn to `0.0.0.0` with reload enabled.
- [verified] The large High-security cluster is dominated by `tests/*_selfcheck.js` uses of Node `vm.runInContext`; for example, `tests/account_management_selfcheck.js:39-40` creates the sandbox and executes a checked-in frontend script.
- [verified] `sonar-project.properties:9-24` declares Python 3.11 and attempts to exclude tests, but SonarCloud warns that Python is analysed as every version and that `sonar.tests` is unset. This is consistent with automatic analysis ignoring `sonar-project.properties`.
- [verified] The frontend test command enumerates and runs every `*_selfcheck.js` file (`tests/run_selfchecks.js:5-29`). It is a test harness, not a browser-facing runtime path.
- [verified] `run_server.py:6`, `host_console.py:1018-1019`, `server/runtime_config.py:104-109`, and `app_launcher.py:228-229` all permit or default to an all-interface bind. Caddy itself proxies only to `127.0.0.1:8000` (`Caddyfile:1-10`).

## 3. Relevant architecture

- [verified] The packaged launcher prepares its runtime, then starts managed Caddy and Cloudflared (`app_launcher.py:224-238`); Caddy is therefore the intended public boundary.
- [verified] `host_console.main` owns the interactive server start and passes `host` and `port` into Uvicorn (`host_console.py:1014-1060`). `server.runtime_config.main` is the container/server entry point (`server/runtime_config.py:98-113`).
- [graph, stale] GitNexus impact for `host_console.main` identifies 12 direct callees and existing coverage in `tests/test_server_runtime.py`; treat the radius as a reminder to preserve dashboard and worker startup behaviour, not as an exact current graph.

## 4. Critique of the Sonar report

1. **The dashboard is not useless, but its 91 security count is not a production-risk count.** Dynamic execution in isolated Node test harnesses deserves safe test design, yet it is not remotely reachable FastAPI or browser code. Treating every harness invocation as a production High vulnerability would create a false priority order.
2. **The Blocker is a real design decision, not an automatic patch.** `run_server.py` opens a dev reloader on every interface, but the supported host/package path may legitimately have a LAN policy. First prove the standalone launcher is legacy; do not change the normal listener default just to silence Sonar.
3. **The present configuration has no effect on the active analyser.** Automatic analysis ignores `sonar-project.properties`; a manual scanner is correctly rejected while automatic analysis is enabled. Changing only that file would be busywork and leave coverage unavailable.
4. **The failed frontend self-check baseline is independent debt.** `npm run test:frontend` currently reports 48/51 passing because three tests hard-code `auth.js?v=100.02`, while `frontend/admin.html` uses `auth.js?v=101.00`. Do not let the Sonar migration hide this existing regression.

## 5. Statement-level / execution findings

- [verified] `host_console.main` loads `.env`, resolves `HOST` and `PORT`, displays them, then creates the Uvicorn configuration. Its listener and access guidance are coupled, so this remediation must not modify them while addressing the standalone legacy launcher.
- [verified] The Caddy upstream remains loopback regardless of the listener's current default. Thus a loopback default preserves domain traffic when the packaged Caddy path is used, while direct-LAN users need an opt-in `HOST=0.0.0.0`.
- PDG slice: unavailable. The current GitNexus index is stale and the local refresh did not update the MCP index; do not infer PDG control edges from source.

## 6. Proposed changes

### A. Establish one analysis mode (P0 — decision gate)

- **Recommended (full quality gate):** migrate to CI-based SonarCloud analysis on GitHub Actions and disable Automatic Analysis immediately before the first CI scan. It is the only option here that makes `sonar-project.properties`, explicit Python version, and coverage reporting deterministic.
- **Lean alternative (fast triage only):** retain Automatic Analysis and add the supported `.sonarcloud.properties` scope configuration (not `sonar-project.properties`) to exclude the test harness. This is lower setup effort but cannot import coverage and remains less configurable.
- Pick exactly one route. Automatic and CI analysis must never run together. Keep the local token only in ignored `.env`; a CI route needs a repository secret `SONAR_TOKEN`, supplied by an administrator.

### B. Define a correct analysis scope (P0)

- CI route: in `sonar-project.properties`, make production roots explicit: `server`, `frontend`, and reviewed root launchers/scripts; declare `sonar.tests=tests` and exclude the Node VM self-check harness from **source-quality** analysis rather than suppressing individual alerts.
- Automatic route: configure the equivalent supported source/test exclusions in `.sonarcloud.properties` or SonarCloud Analysis Scope UI; do not expect the existing `sonar-project.properties` values to apply.
- Generate and pass a Python coverage XML report only on the CI route. Validate the first reanalysis by sampling the scanned-file list and issue list. The expected result is that `tests/*_selfcheck.js` no longer dominates Security, while executable launchers remain in scope.

### C. Repair real interface exposure safely (P1)

- First prove whether `run_server.py` has any supported caller. The current source search found no caller, while the normal host path uses `host_server.bat`, `host_console.py`, and the packaged launcher.
- If it is legacy, remove it or exclude it from deployable launch commands; if it remains as a development tool, bind it to loopback and make `reload` explicitly development-only. This resolves the genuine `python:S8392` finding without changing the production console/package listener contract.
- Do **not** change `host_console.py`, `server/runtime_config.py`, `app_launcher.py`, Caddy, or Cloudflared in this pass. A broader loopback-default policy needs an explicit operator decision about direct LAN use and must be planned separately.

### D. Verify the conditional CORS finding (P1)

- Sonar flags `server/main.py:125` because `CORSMiddleware` is registered before SecurityHeaders/RequestLogging. Default `CORS_ORIGINS` is empty and the deployed frontend is same-origin, so this is not proof of an active vulnerability.
- Add integration coverage for an allowed-origin preflight and an application error response when CORS is enabled. Only then move CORS to the outermost position if the tests confirm missing CORS headers; preserve X-Request-ID and security headers.

### E. Restore a green quality baseline (P1)

- Replace the three brittle exact cache-version assertions in `tests/admin_export_all_selfcheck.js:14`, `tests/export_all_background_selfcheck.js:10`, and `tests/reviewer_role_ui_selfcheck.js:68` with a semantic assertion that `admin.html` loads `auth.js` with a cache-busting query. Do not loosen the tests' behavioural export/reviewer assertions.
- Run the complete existing test commands before making Sonar required in pull requests.

### F. Triage remaining findings after rescan (P2)

- Record `server/openapi.py:70` as a verified analyzer false positive: installed FastAPI supports `get_openapi(..., summary=...)`, and `tests/test_openapi.py` asserts that summary. Do not change it.
- Treat `Math.random()` fallbacks in `frontend/auth.js:10` and `frontend/login.js:13` as low-priority hardening, not an authentication flaw: they only run after `crypto.randomUUID()` and the server generates its own secret token when needed.
- Treat undeclared-global warnings in the classic-script frontend as architectural debt. Do not add `let`/`const` declarations at each use; that can produce redeclaration failures. Assess module/bundle migration separately.
- Export the first clean issue list and group by rule + production file. Fix only confirmed reachable security/reliability defects first.
- Mark issues as Accepted/False Positive only after recording the justification and test coverage in the SonarCloud UI; never bulk-resolve the historic backlog to make a grade green.
- Create separate bounded tickets for maintainability groups (large frontend functions, duplication, obsolete files) after their code paths are source-verified.

## 7. Implementation sequence

1. Record the current Sonar dashboard counts, Quality Gate, analysis warnings, and current frontend-test failures as the baseline.
2. Select Automatic-with-scope or CI-with-coverage. For CI, add the workflow and secret; for Automatic, add supported `.sonarcloud.properties`/UI scope. Do not enable both.
3. Reanalyse and prove the VM self-check harness no longer dominates Security. Stop if production launchers were accidentally excluded.
4. Fix the three cache-version self-checks; rerun Python and frontend suites until green.
5. Confirm `run_server.py` is legacy; then remove it or make it loopback/development-only, with a targeted test. Do not alter the normal console/package listener path.
6. Add conditional CORS integration tests and only change middleware order if they demonstrate a real missing-header path.
7. Export remaining production findings, record justified false positives/debt, and create focused follow-up tickets. If using CI, make the Quality Gate required only after two stable scans.

## 8. Test strategy

- Existing Python: `python -B -m pytest tests -p no:cacheprovider --basetemp 'D:\\scan_to_excel\\scratch\\pytest-sonar' -q`.
- Existing frontend: `npm run test:frontend`; acceptance is all self-checks pass, including the three current cache-version failures.
- Targeted launcher test: direct `run_server.py` is either absent from supported runtime or uses loopback/development-only reload; normal console/package launch retains its current behaviour.
- CORS integration: with a configured allowed origin, verify preflight and an application error response keep CORS, security, and correlation headers.
- CI-only validation: verify coverage XML exists, the scanner receives it, `sonar.tests` is recognized, and the next report contains no VM-harness production findings. Automatic-route validation instead verifies the supported scope configuration took effect.

## 9. Risk and impact analysis

- Deleting or changing `run_server.py` can affect an undocumented manual workflow. Search callers and confirm the legacy status before changing it.
- A scan-mode switch can temporarily remove dashboard continuity. Do it in one short maintenance window and compare the last automatic analysis with the first CI analysis before enforcing any gate.
- The application has an active dirty worktree. Keep this remediation isolated; do not reset, reformat, or mass-apply Sonar quick fixes.
- Coverage can be misleading if generated reports include tests or omit `server`; inspect the first report rather than trusting a percentage alone.

## 10. Files expected to change

| File | Responsibility |
| --- | --- |
| `.github/workflows/sonarcloud.yml` (new) | Deterministic test, coverage, and Sonar analysis in CI. |
| `sonar-project.properties` | CI-only source/test scope, Python version, and coverage report path. |
| `requirements.txt` / lock file | Add the chosen coverage reporter if required. |
| `run_server.py` | Remove unsupported launcher or make direct dev launch loopback/reload-explicit. |
| `server/main.py` | CORS order only if conditional integration test proves a missing-header path. |
| `tests/test_server_runtime.py` | Direct-launch regression test. |
| `tests/test_openapi.py` | Preserve FastAPI `summary` compatibility assertion. |
| Three named frontend self-checks | Remove brittle cache-version literals while preserving behaviour checks. |

## 11. Reusable implementation context

```yaml
implementation_context:
  task_summary: "Make SonarCloud trustworthy through a CI scan, correct scope, coverage, and an explicit listener policy."
  acceptance_criteria:
    - "Exactly one SonarCloud analysis mode is enabled."
    - "CI scan analyzes deployable code, recognizes tests, and publishes coverage."
    - "Legacy direct launcher is removed or safe; normal console/package networking is preserved."
    - "Existing Python and frontend suites are green before a required gate."
  evidence_provenance:
    status: "unavailable in this session"
    reason: "GitNexus schema-2 snapshot helper was blocked by Windows sandbox git spawn EPERM; must be re-created before execution."
  primary_symbols:
    - { symbol: "host_console.main", file: "host_console.py", lines: "1014-1069", role: "interactive server startup" }
    - { symbol: "server.runtime_config.main", file: "server/runtime_config.py", lines: "98-113", role: "runtime server entrypoint" }
    - { symbol: "run_server module entry", file: "run_server.py", lines: "1-6", role: "legacy direct startup" }
  tests:
    - { file: "tests/test_server_runtime.py", scenarios: ["legacy direct launcher contract", "normal console/package path unchanged"] }
    - { file: "tests/*_selfcheck.js", scenarios: ["all existing self-checks pass without cache-version literals"] }
  verification_commands:
    - "python -B -m pytest tests -p no:cacheprovider --basetemp 'D:\\scan_to_excel\\scratch\\pytest-sonar' -q"
    - "npm run test:frontend"
  assumptions:
    - "GitHub repository administration can add SONAR_TOKEN if the recommended CI route is selected."
  avoid:
    - "Do not commit .env or its token."
    - "Do not bulk-resolve Sonar findings or exclude production launchers."
    - "Do not change Caddy/Cloudflared or normal console/package listener behaviour in this remediation."
```

## 12. Assumptions and open questions

- [assumed] GitHub Actions is permitted if the CI route is selected. If it is not, retain Automatic Analysis with supported scope configuration; do not run manual and automatic analysis together.
- [assumed] `run_server.py` is not a supported production launcher. Confirm this before deleting it; direct LAN policy for the normal console/package path remains out of scope.
- [deferred] The 657 Maintainability and residual Reliability issues need a post-rescan, rule-by-rule plan. The current dashboard cannot safely justify a large refactor.

## 13. Definition of done

- SonarCloud shows one analysis method, no automatic-analysis conflict, and correct production/test scope. A coverage report is required only for the CI route.
- No test-harness VM issue is counted as production security debt.
- The normal Caddy/Cloudflared and console/package route is unchanged; the direct legacy launcher is removed or safe for its stated purpose.
- Python tests and all frontend self-checks pass, then the post-migration issue list is triaged with evidence.

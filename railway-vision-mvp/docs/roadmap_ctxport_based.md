# Vistral Roadmap (CtxPort Method)

## 1. Engineering Constitution
- Intranet first: no internet dependency in core workflow.
- Single source of truth: permissions, audit actions, model/task statuses are centrally defined.
- Progressive migration: parallel run -> parity check -> switch default -> clean legacy path.
- Security by default: least privilege, signed model package, encrypted model artifacts, L3 masked by default.
- Documentation first for major changes: each phase must have ADR + QA checklist.

## 2. Phase Plan

### Phase 0: Governance Baseline (Week 1)
- Create document tracks and templates.
- Centralize backend constants and role/capability mapping.
- Define release quality gate and rollback criteria.
- Exit criteria:
  - docs skeleton exists and is used by team.
  - backend status/permission/action constants are centralized.

### Phase 1: Closed-Loop MVP Hardening (Week 2-4)
- Model flow: submit -> approve -> release with full audit trails.
- Task flow: upload -> create task -> edge pull -> push result -> query/audit.
- Enforce default policy: raw video not uploaded from edge.
- Exit criteria:
  - full happy path demo with platform admin and buyer roles.
  - all key actions recorded in audit logs.

### Phase 2: Pluginized Inference Capability (Week 5-7)
- Define plugin contract for algorithm handlers.
- Integrate at least two handlers:
  - car number OCR
  - bolt/part missing detection
- Keep pipeline stable when adding a third handler (no core workflow rewrite).
- Exit criteria:
  - new algorithm can be integrated by plugin only.

### Phase 3: Quality Gate & Reliability (Week 8-10)
- Build golden fixtures for representative scenarios.
- Add parity/regression checks for result schema and task lifecycle.
- Execute multi-device edge stress tests and network interruption recovery.
- Exit criteria:
  - regression checklist passes.
  - stress test report published.

### Phase 4: Commercialization Readiness (Week 11-12)
- Buyer-facing authorization scope by model/version/device.
- Settlement-ready release records and traceability.
- Release package with compliance evidence bundle.
- Exit criteria:
  - auditable paid-delivery flow available.

## 3. Delivery Cadence
- Weekly:
  - architecture decision updates (docs/cto)
  - UI/product updates (docs/product, docs/ui, docs/interaction)
  - QA report and release readiness score (docs/qa)
- Per release candidate:
  - ADR complete
  - QA checklist complete
  - rollback plan validated

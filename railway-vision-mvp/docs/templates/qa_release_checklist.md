# QA Release Checklist

## 1. Functional Regression
- [ ] Auth/RBAC works for platform_admin, supplier_engineer, buyer_operator, buyer_auditor.
- [ ] Model submit/approve/release full flow works.
- [ ] Asset upload (image/video) and task create flow works.
- [ ] Edge task pull, model pull, result push works.
- [ ] Result and audit query works.

## 2. Security and Compliance
- [ ] Raw video does not leave edge by default.
- [ ] Model package signature verification enforced.
- [ ] Model artifacts stored encrypted.
- [ ] L3 data masked for users without `data.l3.read` permission.
- [ ] Download/release/export actions produce audit logs.

## 3. Reliability
- [ ] Edge offline cache and retry behavior verified.
- [ ] Re-dispatch of stale dispatched tasks verified.
- [ ] Multi-task parallel execution smoke test passed.

## 4. UX and Access Control
- [ ] Unauthorized features are removed from DOM and routes.
- [ ] Page-level and component-level loading states behave correctly.
- [ ] Empty/error/403 states are clear and actionable.

## 5. Release Decision
- Release candidate: <version>
- Decision: GO | NO-GO
- Approvers: <names>
- Known risks: <list>

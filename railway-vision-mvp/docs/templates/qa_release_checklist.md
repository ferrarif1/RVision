# QA Release Checklist

- Release candidate:
- Environment:
- Owner:
- Date:

## 1. Build and Basic Integrity

- [ ] Backend / frontend / edge code compile or parse checks pass
- [ ] Required containers start successfully
- [ ] Static assets load correctly
- Evidence:

## 2. Functional Regression

- [ ] Auth / RBAC works for `platform_admin` / `supplier_engineer` / `buyer_operator` / `buyer_auditor`
- [ ] Model submit / approve / release flow works
- [ ] Pipeline register / release flow works
- [ ] Asset upload and task create flow works
- [ ] Edge pull task / pull model / push results flow works
- [ ] Result query / export / audit query works
- Evidence:

## 3. Security and Compliance

- [ ] Raw video does not leave edge by default
- [ ] Model package signature verification enforced
- [ ] Model artifacts stored encrypted
- [ ] Sensitive data access obeys permission boundary
- [ ] Download / release / export actions produce audit logs
- Evidence:

## 4. Reliability and Runtime

- [ ] Golden fixture regression passed
- [ ] Edge offline cache and retry behavior verified
- [ ] Re-dispatch of stale dispatched tasks verified
- [ ] Demo or smoke flow reaches terminal state
- Evidence:

## 5. UX and Accessibility

- [ ] Unauthorized features are hidden or blocked clearly
- [ ] Empty / loading / error / 403 states are actionable
- [ ] Main flow is still within expected step count
- [ ] Keyboard focus and primary accessibility paths still work
- Evidence:

## 6. Documentation and Rollback

- [ ] Current implementation status is reflected in docs
- [ ] Migration / rollback notes updated if needed
- [ ] Known risks are documented
- Evidence:

## 7. Release Decision

- Decision: GO | NO-GO
- Approvers:
- Known risks:
- Risk acceptance owner:

# Release Gate Runbook

## 1. Purpose
Provide a deterministic GO/NO-GO process before demo/release:
- compile and golden checks
- API parity and RBAC contract checks
- audit trace checks for critical actions

## 2. Preconditions
- docker compose services are up (`backend`, `frontend`, `postgres`, `redis`)
- edge-agent profile is running for terminal task validation
- demo users and baseline models are initialized (bootstrap demo recommended)

## 3. Commands

### 3.1 Quality Gate
```bash
cd /Users/zhangyuanyi/Downloads/RVision/railway-vision-mvp
bash docker/scripts/quality_gate.sh
```

### 3.2 API Parity Regression
```bash
python3 docker/scripts/parity_regression.py --wait-seconds 120
```

### 3.3 Full GO/NO-GO
```bash
bash docker/scripts/go_no_go.sh
```

可指定报告目录与等待时间：

```bash
bash docker/scripts/go_no_go.sh --wait-seconds 180 --report-dir docs/qa/reports
```

## 4. What Gets Checked
1. Role-permission parity (`/auth/login` and `/users/me`)
2. Audit access boundary (admin allowed, buyer denied)
3. Task/results API contract parity (required fields and flow continuity)
4. Export audit trace existence (`RESULT_EXPORT`)

## 5. Decision Criteria
- `go_no_go.sh` exits with code 0: **GO**
- any non-zero exit: **NO-GO**

产出报告：
- `docs/qa/reports/go_no_go_YYYYMMDD_HHMMSS.json`
- `docs/qa/reports/latest_go_no_go.json`

## 6. Common Failure Handling
- task not terminal in time:
  - verify edge-agent is running
  - inspect `docker logs rv_edge_agent`
- permission mismatch:
  - check centralized constants and role mapping in backend
- audit trace missing:
  - verify action write path in corresponding API handler

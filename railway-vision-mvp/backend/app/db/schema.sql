CREATE TABLE IF NOT EXISTS tenants (
  id VARCHAR(36) PRIMARY KEY,
  tenant_code VARCHAR(128) UNIQUE NOT NULL,
  name VARCHAR(255) NOT NULL,
  tenant_type VARCHAR(32) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
  id VARCHAR(36) PRIMARY KEY,
  username VARCHAR(128) UNIQUE NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  tenant_id VARCHAR(36) NULL REFERENCES tenants(id) ON DELETE SET NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS roles (
  id SERIAL PRIMARY KEY,
  name VARCHAR(64) UNIQUE NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_roles (
  id SERIAL PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  CONSTRAINT uq_user_role UNIQUE (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS devices (
  id VARCHAR(36) PRIMARY KEY,
  code VARCHAR(128) UNIQUE NOT NULL,
  name VARCHAR(255) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
  edge_token_hash VARCHAR(255) NOT NULL,
  agent_version VARCHAR(64) NULL,
  last_seen_at TIMESTAMP NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS models (
  id VARCHAR(36) PRIMARY KEY,
  model_code VARCHAR(128) NOT NULL,
  version VARCHAR(64) NOT NULL,
  model_hash VARCHAR(128) NOT NULL,
  model_type VARCHAR(32) NOT NULL DEFAULT 'expert',
  runtime VARCHAR(64) NULL,
  inputs JSONB NOT NULL DEFAULT '{}'::jsonb,
  outputs JSONB NOT NULL DEFAULT '{}'::jsonb,
  plugin_name VARCHAR(128) NULL,
  gpu_mem_mb INTEGER NULL,
  latency_ms INTEGER NULL,
  encrypted_uri TEXT NOT NULL,
  signature_uri TEXT NOT NULL,
  manifest_uri TEXT NOT NULL,
  manifest JSONB NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'REGISTERED',
  created_by VARCHAR(36) NOT NULL REFERENCES users(id),
  owner_tenant_id VARCHAR(36) NULL REFERENCES tenants(id) ON DELETE SET NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_model_code_version UNIQUE (model_code, version)
);

CREATE TABLE IF NOT EXISTS pipelines (
  id VARCHAR(36) PRIMARY KEY,
  pipeline_code VARCHAR(128) NOT NULL,
  name VARCHAR(255) NOT NULL,
  router_model_id VARCHAR(36) NULL REFERENCES models(id) ON DELETE SET NULL,
  expert_map JSONB NOT NULL DEFAULT '{}'::jsonb,
  thresholds JSONB NOT NULL DEFAULT '{}'::jsonb,
  fusion_rules JSONB NOT NULL DEFAULT '{}'::jsonb,
  config JSONB NOT NULL DEFAULT '{}'::jsonb,
  version VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
  owner_tenant_id VARCHAR(36) NULL REFERENCES tenants(id) ON DELETE SET NULL,
  created_by VARCHAR(36) NOT NULL REFERENCES users(id),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_pipeline_code_version UNIQUE (pipeline_code, version)
);

CREATE TABLE IF NOT EXISTS model_releases (
  id VARCHAR(36) PRIMARY KEY,
  model_id VARCHAR(36) NOT NULL REFERENCES models(id) ON DELETE CASCADE,
  target_devices JSONB NOT NULL,
  target_buyers JSONB NOT NULL DEFAULT '[]'::jsonb,
  status VARCHAR(32) NOT NULL DEFAULT 'RELEASED',
  released_by VARCHAR(36) NOT NULL REFERENCES users(id),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS data_assets (
  id VARCHAR(36) PRIMARY KEY,
  file_name VARCHAR(255) NOT NULL,
  asset_type VARCHAR(32) NOT NULL,
  storage_uri TEXT NOT NULL,
  source_uri TEXT NULL,
  sensitivity_level VARCHAR(8) NOT NULL,
  checksum VARCHAR(128) NOT NULL,
  buyer_tenant_id VARCHAR(36) NULL REFERENCES tenants(id) ON DELETE SET NULL,
  metadata JSONB NOT NULL,
  uploaded_by VARCHAR(36) NOT NULL REFERENCES users(id),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inference_tasks (
  id VARCHAR(36) PRIMARY KEY,
  model_id VARCHAR(36) NULL REFERENCES models(id) ON DELETE SET NULL,
  pipeline_id VARCHAR(36) NULL REFERENCES pipelines(id) ON DELETE SET NULL,
  asset_id VARCHAR(36) NULL REFERENCES data_assets(id) ON DELETE SET NULL,
  device_code VARCHAR(128) NULL,
  task_type VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
  buyer_tenant_id VARCHAR(36) NULL REFERENCES tenants(id) ON DELETE SET NULL,
  policy JSONB NOT NULL,
  error_message TEXT NULL,
  created_by VARCHAR(36) NOT NULL REFERENCES users(id),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at TIMESTAMP NULL,
  finished_at TIMESTAMP NULL,
  dispatch_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS inference_results (
  id VARCHAR(36) PRIMARY KEY,
  task_id VARCHAR(36) NOT NULL REFERENCES inference_tasks(id) ON DELETE CASCADE,
  model_id VARCHAR(36) NULL REFERENCES models(id) ON DELETE SET NULL,
  model_hash VARCHAR(128) NOT NULL,
  result_json JSONB NOT NULL,
  buyer_tenant_id VARCHAR(36) NULL REFERENCES tenants(id) ON DELETE SET NULL,
  alert_level VARCHAR(32) NOT NULL DEFAULT 'INFO',
  screenshot_uri TEXT NULL,
  duration_ms INTEGER NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inference_runs (
  id VARCHAR(36) PRIMARY KEY,
  job_id VARCHAR(36) NOT NULL UNIQUE,
  task_id VARCHAR(36) NOT NULL REFERENCES inference_tasks(id) ON DELETE CASCADE,
  pipeline_id VARCHAR(36) NULL REFERENCES pipelines(id) ON DELETE SET NULL,
  pipeline_version VARCHAR(64) NULL,
  threshold_version VARCHAR(64) NULL,
  input_hash VARCHAR(128) NOT NULL,
  input_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  models_versions JSONB NOT NULL DEFAULT '[]'::jsonb,
  timings JSONB NOT NULL DEFAULT '{}'::jsonb,
  result_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  audit_hash VARCHAR(128) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'SUCCEEDED',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS review_queue (
  id VARCHAR(36) PRIMARY KEY,
  job_id VARCHAR(36) NOT NULL,
  task_id VARCHAR(36) NOT NULL REFERENCES inference_tasks(id) ON DELETE CASCADE,
  pipeline_id VARCHAR(36) NULL REFERENCES pipelines(id) ON DELETE SET NULL,
  reason TEXT NOT NULL,
  assigned_to VARCHAR(128) NULL,
  label_result VARCHAR(128) NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS training_workers (
  id VARCHAR(36) PRIMARY KEY,
  worker_code VARCHAR(128) NOT NULL UNIQUE,
  name VARCHAR(255) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
  auth_token_hash VARCHAR(255) NOT NULL,
  host VARCHAR(255) NULL,
  labels JSONB NOT NULL DEFAULT '{}'::jsonb,
  resources JSONB NOT NULL DEFAULT '{}'::jsonb,
  last_seen_at TIMESTAMP NULL,
  last_job_at TIMESTAMP NULL,
  created_by VARCHAR(36) NOT NULL REFERENCES users(id),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS training_jobs (
  id VARCHAR(36) PRIMARY KEY,
  job_code VARCHAR(128) NOT NULL UNIQUE,
  owner_tenant_id VARCHAR(36) NULL REFERENCES tenants(id) ON DELETE SET NULL,
  buyer_tenant_id VARCHAR(36) NULL REFERENCES tenants(id) ON DELETE SET NULL,
  base_model_id VARCHAR(36) NULL REFERENCES models(id) ON DELETE SET NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
  training_kind VARCHAR(32) NOT NULL DEFAULT 'finetune',
  asset_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  validation_asset_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  target_model_code VARCHAR(128) NOT NULL,
  target_version VARCHAR(64) NOT NULL,
  worker_selector JSONB NOT NULL DEFAULT '{}'::jsonb,
  spec JSONB NOT NULL DEFAULT '{}'::jsonb,
  output_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  candidate_model_id VARCHAR(36) NULL REFERENCES models(id) ON DELETE SET NULL,
  assigned_worker_code VARCHAR(128) NULL,
  error_message TEXT NULL,
  requested_by VARCHAR(36) NOT NULL REFERENCES users(id),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at TIMESTAMP NULL,
  finished_at TIMESTAMP NULL,
  dispatch_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id BIGSERIAL PRIMARY KEY,
  actor_user_id VARCHAR(36) NULL,
  actor_username VARCHAR(128) NULL,
  actor_role VARCHAR(64) NULL,
  action VARCHAR(128) NOT NULL,
  resource_type VARCHAR(64) NOT NULL,
  resource_id VARCHAR(128) NULL,
  detail JSONB NOT NULL,
  ip_address VARCHAR(64) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tasks_device_status ON inference_tasks(device_code, status);
CREATE INDEX IF NOT EXISTS idx_results_task_id ON inference_results(task_id);
CREATE INDEX IF NOT EXISTS idx_audit_action_created ON audit_logs(action, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_models_code_version ON models(model_code, version);
CREATE INDEX IF NOT EXISTS idx_models_type_status ON models(model_type, status);
CREATE INDEX IF NOT EXISTS idx_pipelines_code_version ON pipelines(pipeline_code, version);
CREATE INDEX IF NOT EXISTS idx_pipelines_status ON pipelines(status);
CREATE INDEX IF NOT EXISTS idx_users_tenant_id ON users(tenant_id);
CREATE INDEX IF NOT EXISTS idx_models_owner_tenant_id ON models(owner_tenant_id);
CREATE INDEX IF NOT EXISTS idx_pipelines_owner_tenant_id ON pipelines(owner_tenant_id);
CREATE INDEX IF NOT EXISTS idx_assets_buyer_tenant_id ON data_assets(buyer_tenant_id);
CREATE INDEX IF NOT EXISTS idx_tasks_buyer_tenant_id ON inference_tasks(buyer_tenant_id);
CREATE INDEX IF NOT EXISTS idx_tasks_pipeline_id ON inference_tasks(pipeline_id);
CREATE INDEX IF NOT EXISTS idx_results_buyer_tenant_id ON inference_results(buyer_tenant_id);
CREATE INDEX IF NOT EXISTS idx_inference_runs_task_id ON inference_runs(task_id);
CREATE INDEX IF NOT EXISTS idx_review_queue_task_id ON review_queue(task_id);
CREATE INDEX IF NOT EXISTS idx_training_workers_status ON training_workers(status);
CREATE INDEX IF NOT EXISTS idx_training_jobs_status ON training_jobs(status);
CREATE INDEX IF NOT EXISTS idx_training_jobs_owner_tenant_id ON training_jobs(owner_tenant_id);
CREATE INDEX IF NOT EXISTS idx_training_jobs_buyer_tenant_id ON training_jobs(buyer_tenant_id);
CREATE INDEX IF NOT EXISTS idx_training_jobs_candidate_model_id ON training_jobs(candidate_model_id);
CREATE INDEX IF NOT EXISTS idx_training_jobs_assigned_worker_code ON training_jobs(assigned_worker_code);
CREATE INDEX IF NOT EXISTS idx_tenants_code ON tenants(tenant_code);

INSERT INTO roles(name) VALUES ('platform_admin') ON CONFLICT(name) DO NOTHING;
INSERT INTO roles(name) VALUES ('platform_operator') ON CONFLICT(name) DO NOTHING;
INSERT INTO roles(name) VALUES ('platform_auditor') ON CONFLICT(name) DO NOTHING;
INSERT INTO roles(name) VALUES ('supplier_engineer') ON CONFLICT(name) DO NOTHING;
INSERT INTO roles(name) VALUES ('buyer_operator') ON CONFLICT(name) DO NOTHING;
INSERT INTO roles(name) VALUES ('buyer_auditor') ON CONFLICT(name) DO NOTHING;

-- legacy compatibility
INSERT INTO roles(name) VALUES ('admin') ON CONFLICT(name) DO NOTHING;
INSERT INTO roles(name) VALUES ('operator') ON CONFLICT(name) DO NOTHING;
INSERT INTO roles(name) VALUES ('auditor') ON CONFLICT(name) DO NOTHING;

INSERT INTO tenants(id, tenant_code, name, tenant_type)
VALUES ('00000000-0000-0000-0000-000000000001', 'platform-001', 'Platform Tenant', 'PLATFORM')
ON CONFLICT(tenant_code) DO NOTHING;
INSERT INTO tenants(id, tenant_code, name, tenant_type)
VALUES ('00000000-0000-0000-0000-000000000002', 'supplier-demo-001', 'Supplier Demo Tenant', 'SUPPLIER')
ON CONFLICT(tenant_code) DO NOTHING;
INSERT INTO tenants(id, tenant_code, name, tenant_type)
VALUES ('00000000-0000-0000-0000-000000000003', 'buyer-demo-001', 'Buyer Demo Tenant', 'BUYER')
ON CONFLICT(tenant_code) DO NOTHING;

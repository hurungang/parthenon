-- Application of alembic revision a1b2c3d4f5e6 (down_revision b7d2e9f4a1c8)
-- executed via psql because alembic is not installed in any local Python env.
BEGIN;

DO $$ BEGIN
    CREATE TYPE script_lifecycle_status_enum AS ENUM ('draft', 'verified', 'compiled', 'retired');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE script_health_status_enum AS ENUM ('healthy', 'degraded', 'unhealthy');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE verification_comparison_outcome_enum AS ENUM ('match', 'match_within_tolerance', 'mismatch');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE verification_verdict_enum AS ENUM ('promoted', 'rejected');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE fallback_trigger_reason_enum AS ENUM ('execution_error', 'tool_schema_mismatch', 'output_validation_failure');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE fallback_resulting_action_enum AS ENUM ('llm_completed', 'repaired_candidate_produced', 'repair_not_produced');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE script_execution_mode_enum AS ENUM ('llm', 'compiled_with_fallback', 'compiled_only');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE script_execution_outcome_enum AS ENUM ('success', 'validation_failure', 'fell_back');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE script_definitions (
    id uuid NOT NULL,
    tenant_id uuid,
    name varchar(200) NOT NULL,
    description text,
    lifecycle_status script_lifecycle_status_enum NOT NULL,
    agent_type_id uuid NOT NULL,
    source_plan_id uuid,
    source_session_id uuid,
    current_version_id uuid,
    health_status script_health_status_enum NOT NULL,
    created_at timestamptz DEFAULT now() NOT NULL,
    updated_at timestamptz DEFAULT now() NOT NULL,
    CONSTRAINT script_definitions_pkey PRIMARY KEY (id),
    CONSTRAINT uq_script_definitions_tenant_name UNIQUE (tenant_id, name),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE SET NULL,
    FOREIGN KEY(agent_type_id) REFERENCES agent_types (id) ON DELETE CASCADE,
    FOREIGN KEY(source_plan_id) REFERENCES agent_plans (id) ON DELETE SET NULL,
    FOREIGN KEY(source_session_id) REFERENCES conversation_sessions (id) ON DELETE SET NULL
);
CREATE INDEX ix_script_definitions_tenant_id ON script_definitions (tenant_id);
CREATE INDEX ix_script_definitions_agent_type_id ON script_definitions (agent_type_id);

CREATE TABLE script_versions (
    id uuid NOT NULL,
    tenant_id uuid,
    script_definition_id uuid NOT NULL,
    version_label varchar(50) NOT NULL,
    lifecycle_status script_lifecycle_status_enum NOT NULL,
    declarative_step_graph json,
    content_reference text,
    compiled_from_source text,
    parent_version_id uuid,
    created_by varchar(500),
    created_at timestamptz DEFAULT now() NOT NULL,
    updated_at timestamptz DEFAULT now() NOT NULL,
    CONSTRAINT script_versions_pkey PRIMARY KEY (id),
    CONSTRAINT uq_script_versions_label UNIQUE (script_definition_id, version_label),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE SET NULL,
    FOREIGN KEY(script_definition_id) REFERENCES script_definitions (id) ON DELETE CASCADE,
    FOREIGN KEY(parent_version_id) REFERENCES script_versions (id) ON DELETE SET NULL
);
CREATE INDEX ix_script_versions_tenant_id ON script_versions (tenant_id);
CREATE INDEX ix_script_versions_script_definition_id ON script_versions (script_definition_id);

ALTER TABLE script_definitions ADD FOREIGN KEY(current_version_id) REFERENCES script_versions (id) ON DELETE SET NULL;

CREATE TABLE verification_runs (
    id uuid NOT NULL,
    tenant_id uuid,
    script_version_id uuid NOT NULL,
    reference_execution_id uuid,
    input_context json,
    expected_output json,
    actual_output json,
    comparison_outcome verification_comparison_outcome_enum NOT NULL,
    verdict verification_verdict_enum NOT NULL,
    verdict_reason text,
    created_at timestamptz DEFAULT now() NOT NULL,
    updated_at timestamptz DEFAULT now() NOT NULL,
    CONSTRAINT verification_runs_pkey PRIMARY KEY (id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE SET NULL,
    FOREIGN KEY(script_version_id) REFERENCES script_versions (id) ON DELETE CASCADE,
    FOREIGN KEY(reference_execution_id) REFERENCES conversation_sessions (id) ON DELETE SET NULL
);
CREATE INDEX ix_verification_runs_tenant_id ON verification_runs (tenant_id);
CREATE INDEX ix_verification_runs_script_version_id ON verification_runs (script_version_id);

CREATE TABLE script_execution_records (
    id uuid NOT NULL,
    tenant_id uuid,
    script_version_id uuid,
    execution_mode script_execution_mode_enum NOT NULL,
    outcome script_execution_outcome_enum NOT NULL,
    duration_ms integer,
    tools_invoked json,
    model_backed_steps_used json,
    session_id uuid,
    tokens_saved_estimate integer,
    created_at timestamptz DEFAULT now() NOT NULL,
    updated_at timestamptz DEFAULT now() NOT NULL,
    CONSTRAINT script_execution_records_pkey PRIMARY KEY (id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE SET NULL,
    FOREIGN KEY(script_version_id) REFERENCES script_versions (id) ON DELETE SET NULL,
    FOREIGN KEY(session_id) REFERENCES conversation_sessions (id) ON DELETE SET NULL
);
CREATE INDEX ix_script_execution_records_tenant_id ON script_execution_records (tenant_id);
CREATE INDEX ix_script_execution_records_script_version_id ON script_execution_records (script_version_id);
CREATE INDEX ix_script_execution_records_session_id ON script_execution_records (session_id);

CREATE TABLE fallback_events (
    id uuid NOT NULL,
    tenant_id uuid,
    execution_record_id uuid NOT NULL,
    script_version_id uuid,
    trigger_reason fallback_trigger_reason_enum NOT NULL,
    failure_detail text,
    resulting_action fallback_resulting_action_enum NOT NULL,
    script_health_impact integer NOT NULL,
    repaired_version_id uuid,
    created_at timestamptz DEFAULT now() NOT NULL,
    updated_at timestamptz DEFAULT now() NOT NULL,
    CONSTRAINT fallback_events_pkey PRIMARY KEY (id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE SET NULL,
    FOREIGN KEY(execution_record_id) REFERENCES script_execution_records (id) ON DELETE CASCADE,
    FOREIGN KEY(script_version_id) REFERENCES script_versions (id) ON DELETE SET NULL,
    FOREIGN KEY(repaired_version_id) REFERENCES script_versions (id) ON DELETE SET NULL
);
CREATE INDEX ix_fallback_events_tenant_id ON fallback_events (tenant_id);
CREATE INDEX ix_fallback_events_execution_record_id ON fallback_events (execution_record_id);
CREATE INDEX ix_fallback_events_script_version_id ON fallback_events (script_version_id);

CREATE TABLE execution_mode_configurations (
    id uuid NOT NULL,
    tenant_id uuid,
    agent_type_id uuid NOT NULL,
    workflow_skill_id uuid,
    execution_mode script_execution_mode_enum NOT NULL,
    created_at timestamptz DEFAULT now() NOT NULL,
    updated_at timestamptz DEFAULT now() NOT NULL,
    CONSTRAINT execution_mode_configurations_pkey PRIMARY KEY (id),
    CONSTRAINT uq_execution_mode_config_agent_workflow UNIQUE (tenant_id, agent_type_id, workflow_skill_id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE SET NULL,
    FOREIGN KEY(agent_type_id) REFERENCES agent_types (id) ON DELETE CASCADE,
    FOREIGN KEY(workflow_skill_id) REFERENCES skills (id) ON DELETE CASCADE
);
CREATE INDEX ix_execution_mode_configurations_tenant_id ON execution_mode_configurations (tenant_id);
CREATE INDEX ix_execution_mode_configurations_agent_type_id ON execution_mode_configurations (agent_type_id);

UPDATE alembic_version SET version_num = 'a1b2c3d4f5e6' WHERE version_num = 'b7d2e9f4a1c8';

COMMIT;

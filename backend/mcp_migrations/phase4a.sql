-- Phase 4A schema review draft. NOT executed. Additive disposable-only DDL.


CREATE TABLE mcp_clients (
	id VARCHAR(128) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	redirect_uris JSONB NOT NULL, 
	scopes VARCHAR(128) NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
)

;


CREATE TABLE mcp_policies (
	tenant_id UUID NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	read_only BOOLEAN NOT NULL, 
	emergency_disabled BOOLEAN NOT NULL, 
	allowed_tools JSONB NOT NULL, 
	allowed_roles JSONB NOT NULL, 
	revision INTEGER NOT NULL, 
	updated_by VARCHAR(36) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (tenant_id), 
	CONSTRAINT ck_mcp_policy_read_only CHECK (read_only), 
	CONSTRAINT ck_mcp_policy_revision CHECK (revision > 0), 
	FOREIGN KEY(updated_by) REFERENCES users (id) ON DELETE RESTRICT
)

;


CREATE TABLE mcp_grants (
	id VARCHAR(36) NOT NULL, 
	client_id VARCHAR(128) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	tenant_id UUID NOT NULL, 
	session_id VARCHAR(36) NOT NULL, 
	auth_epoch BIGINT NOT NULL, 
	scopes VARCHAR(128) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	revocation_reason VARCHAR(64), 
	PRIMARY KEY (id), 
	CONSTRAINT ck_mcp_grant_lifetime CHECK (expires_at > created_at), 
	FOREIGN KEY(client_id) REFERENCES mcp_clients (id) ON DELETE RESTRICT, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT, 
	FOREIGN KEY(session_id) REFERENCES auth_sessions (id) ON DELETE RESTRICT
)

;

CREATE INDEX ix_mcp_grant_tenant_user ON mcp_grants (tenant_id, user_id);


CREATE TABLE mcp_authorizations (
	id VARCHAR(36) NOT NULL, 
	client_id VARCHAR(128) NOT NULL, 
	redirect_uri VARCHAR(512) NOT NULL, 
	resource VARCHAR(512) NOT NULL, 
	state VARCHAR(512) NOT NULL, 
	scopes VARCHAR(128) NOT NULL, 
	code_challenge VARCHAR(43) NOT NULL, 
	code_challenge_method VARCHAR(4) NOT NULL, 
	browser_digest VARCHAR(64) NOT NULL, 
	csrf_digest VARCHAR(64), 
	user_id VARCHAR(36), 
	tenant_id UUID, 
	session_id VARCHAR(36), 
	grant_id VARCHAR(36), 
	code_digest VARCHAR(64), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	code_expires_at TIMESTAMP WITH TIME ZONE, 
	decided_at TIMESTAMP WITH TIME ZONE, 
	consumed_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_mcp_authorization_lifetime CHECK (expires_at > created_at), 
	FOREIGN KEY(client_id) REFERENCES mcp_clients (id) ON DELETE RESTRICT, 
	UNIQUE (browser_digest), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT, 
	FOREIGN KEY(session_id) REFERENCES auth_sessions (id) ON DELETE RESTRICT, 
	FOREIGN KEY(grant_id) REFERENCES mcp_grants (id) ON DELETE RESTRICT, 
	UNIQUE (code_digest)
)

;


CREATE TABLE mcp_credentials (
	digest VARCHAR(64) NOT NULL, 
	grant_id VARCHAR(36) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	issuer VARCHAR(512) NOT NULL, 
	audience VARCHAR(512) NOT NULL, 
	scopes VARCHAR(128) NOT NULL, 
	tool_id VARCHAR(128), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	consumed_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (digest), 
	CONSTRAINT ck_mcp_credential_kind CHECK (kind IN ('access','refresh','downstream')), 
	CONSTRAINT ck_mcp_downstream_tool CHECK (kind <> 'downstream' OR tool_id IS NOT NULL), 
	CONSTRAINT ck_mcp_credential_lifetime CHECK (expires_at > created_at), 
	FOREIGN KEY(grant_id) REFERENCES mcp_grants (id) ON DELETE RESTRICT
)

;

CREATE INDEX ix_mcp_credential_grant ON mcp_credentials (grant_id);


CREATE TABLE mcp_audit (
	id VARCHAR(36) NOT NULL, 
	tenant_id UUID NOT NULL, 
	actor_id VARCHAR(36), 
	grant_id VARCHAR(36), 
	client_id VARCHAR(128), 
	tool_id VARCHAR(128), 
	event VARCHAR(64) NOT NULL, 
	outcome VARCHAR(16) NOT NULL, 
	correlation_id VARCHAR(36) NOT NULL, 
	occurred_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(actor_id) REFERENCES users (id) ON DELETE SET NULL, 
	FOREIGN KEY(grant_id) REFERENCES mcp_grants (id) ON DELETE SET NULL, 
	FOREIGN KEY(client_id) REFERENCES mcp_clients (id) ON DELETE SET NULL
)

;

CREATE INDEX ix_mcp_audit_tenant_time ON mcp_audit (tenant_id, occurred_at);

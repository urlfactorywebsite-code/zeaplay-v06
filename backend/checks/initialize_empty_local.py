"""Explicit empty-local-database initialization; never startup or data repair.

The PowerShell wrapper attests Docker Desktop, project, database and stopped
writers. This module refuses nonempty databases and never stamps Alembic.
"""
import argparse
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).resolve().parents[1]
REVISIONS = (
    'e5a7c9d1f3b5_task_audit_foundation', 'f6b8d0e2a4c6_subtask_workflow',
    'g7c9e1f3a5d7_subtask_rewards', 'h8d0f2a4c6e8_reward_accounting_guards',
    'i9e1a3c5d7f9_task_activity', 'j0f2b4d6e8a0_workload_notifications',
    'k1a3c5e7f9b1_notification_queue_review', 'l2b4d6f8a0c2_auth_sessions',
    'm3c5e7f9a1d3_audit_tenant',
)
OMIT_TABLES = {'task_workflow_settings', 'task_work_intervals', 'task_activity_contexts', 'task_work_corrections'}
OMIT_COLUMNS = {
    'users': {'auth_epoch'}, 'audit_logs': {'tenant_id'},
    'subtasks': {'planned_start_date','planned_end_date','actual_start_at','actual_end_at',
        'priority_override','point_policy_version','version','created_at','workflow_version','workflow_status','deleted_at','reward_timezone'},
    'audit_events': {'audit_schema_version','tenant_id','task_id','subtask_id','before','after','correlation_id'},
    'xp_ledger': {'record_version','task_id','subtask_id','component_type','policy_version','idempotency_key',
        'activity_event_id','reason','reversal_of_id','calculation_inputs'},
    'notifications': {'tenant_id','dedupe_key','alert_kind','dismissed_at','delivery_pending','delivery_attempts','next_delivery_at'},
    'notification_preferences': {'sound_enabled','near_deadline_hours','productive_capacity_hours','overtime_threshold_minutes','quiet_start','quiet_end'},
    'push_subscriptions': {'tenant_id','binding_key'},
}


def models():
    if os.environ.get('ZEA_ALEMBIC_MIGRATION') != '1':
        raise RuntimeError('Import-time schema changes must be disabled')
    sys.path.insert(0, str(ROOT))
    core = sys.modules.get('backend.app.models') or sys.modules.get('app.models')
    core = core or importlib.import_module('app.models')
    for module in ('tickets.models', 'backups.models', 'session_models'):
        importlib.import_module(core.__package__ + '.' + module)
    return core


def legacy_metadata():
    """Build the empty core baseline expected by the existing reviewed revisions."""
    result = sa.MetaData()
    for table in models().Base.metadata.sorted_tables:
        if table.name not in OMIT_TABLES and not table.info.get('alembic_only') and not table.name.startswith('mcp_'):
            table.to_metadata(result)
    for table in result.tables.values():
        omitted = OMIT_COLUMNS.get(table.name, set())
        for index in list(table.indexes):
            predicates = ' '.join(str(index.dialect_options[d].get('where', '')) for d in ('sqlite','postgresql'))
            if (any(column.name in omitted for column in index.columns) or any(name in predicates for name in omitted)
                    or (index.name or '').endswith(('_v2','_ref'))
                    or index.name in ('ix_tasks_assignee_status_updated','ix_tasks_creator_status')):
                table.indexes.remove(index)
        for constraint in list(table.constraints):
            if any(column.name in omitted for column in constraint.columns) or (
                    isinstance(constraint, sa.CheckConstraint) and any(name in str(constraint.sqltext) for name in omitted)):
                table.constraints.remove(constraint)
        for key in list(table.foreign_keys):
            if key.parent.name in omitted:
                table.foreign_keys.remove(key)
        for column in list(table.columns):
            if column.name in omitted:
                table._columns.remove(column)
    return result


def require_empty(connection):
    if connection.dialect.name != 'postgresql' or connection.scalar(sa.text('SELECT current_schema()')) != 'public':
        raise RuntimeError('Only empty PostgreSQL public schema initialization is supported')
    if connection.scalar(sa.text("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%' "
            "AND c.relkind IN ('r','p','v','m','S','f')")):
        raise RuntimeError('Database contains application objects; restore or review its migration plan instead')


def initialize(connection, *, after_revision=None):
    """Caller owns the transaction. Every failure rolls back the entire bootstrap."""
    connection.execute(sa.text("SELECT pg_advisory_xact_lock(853840221)"))
    require_empty(connection)
    connection.exec_driver_sql("SET LOCAL lock_timeout='5s'")
    connection.exec_driver_sql("SET LOCAL statement_timeout='120s'")
    connection.exec_driver_sql('CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public')
    legacy_metadata().create_all(connection)
    for name in REVISIONS:
        spec = importlib.util.spec_from_file_location('_zea_empty_' + name, ROOT/'alembic/versions'/(name+'.py'))
        revision = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(revision)
        revision.op = Operations(MigrationContext.configure(connection))
        context = getattr(revision, 'context', None)
        previous = getattr(context, 'is_offline_mode', None)
        try:
            if previous is not None:
                context.is_offline_mode = lambda: False
            revision.upgrade()
        finally:
            if previous is not None:
                context.is_offline_mode = previous
        if after_revision:
            after_revision(name)
    # Reuse all existing V2 trigger/index/data checks without claiming a false
    # historical Alembic baseline for model-derived core initialization.
    from checks.reconcile_local_v2_schema import _verify
    _verify(connection, (ROOT/'sql/zeaplay_v2_phase7_readiness.sql').read_text(encoding='utf-8'))
    for table, trigger in (('users','zea_user_auth_invalidation'),('audit_logs','audit_tenant_immutable')):
        if not connection.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid=to_regclass(:table) "
                "AND tgname=:trigger AND tgenabled IN ('O','A'))"), {'table':table,'trigger':trigger}):
            raise RuntimeError('Required security trigger absent')
    if any(name.startswith('mcp_') for name in sa.inspect(connection).get_table_names()):
        raise RuntimeError('MCP storage must remain absent')
    return {'initialized':True, 'revisions_reused':len(REVISIONS), 'alembic_stamped':False, 'mcp_enabled':False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    core = models()
    settings = importlib.import_module(core.__package__+'.config').get_settings()
    target = sa.engine.make_url(settings.database_url)
    if (os.environ.get('ZEA_LOCAL_BOOTSTRAP_PROJECT') != 'zeaplay_v1' or settings.environment != 'development'
            or target.host != 'postgres' or target.database != 'zeaplay' or target.username != 'zeaplay'
            or os.environ.get('ZEA_MCP_PHASE4A_ISOLATED') == '1'):
        raise RuntimeError('Use the attested Docker Desktop local initializer')
    engine = sa.create_engine(target, poolclass=sa.pool.NullPool)
    try:
        with engine.begin() as connection:
            require_empty(connection)
            result = initialize(connection) if args.apply else {'empty':True,'apply':False,'revisions':list(REVISIONS)}
        print(json.dumps(result))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()

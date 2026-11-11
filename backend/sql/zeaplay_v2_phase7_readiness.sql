-- Post-migration, read-only PostgreSQL readiness gate. No data is repaired here.
-- Run with psql -v ON_ERROR_STOP=1; only aggregate counts leave the database.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '120s';
SET LOCAL lock_timeout = '5s';
SET LOCAL TIME ZONE 'UTC';

DO $gate$
DECLARE missing_count integer;
BEGIN
    IF (SELECT count(*) FROM alembic_version) <> 1
       OR (SELECT version_num FROM alembic_version LIMIT 1) <> 'k1a3c5e7f9b1' THEN
        RAISE EXCEPTION 'Unexpected migration revision; stop activation';
    END IF;
    -- Names alone can conceal non-unique, invalid or differently keyed indexes.
    SELECT count(*) INTO missing_count FROM (VALUES
        ('xp_ledger', 'uq_xp_ledger_tenant_idempotency', ARRAY['tenant_id','idempotency_key'], true, NULL),
        ('xp_ledger', 'uq_xp_ledger_reversal', ARRAY['tenant_id','reversal_of_id'], true, NULL),
        ('task_activity_contexts', 'uq_activity_user_parent', ARRAY['tenant_id','user_id','task_id'], true, NULL),
        ('task_activity_contexts', 'uq_activity_user_slot', ARRAY['tenant_id','user_id','slot'], true, NULL),
        ('notifications', 'uq_notification_recipient_event', ARRAY['user_id','dedupe_key'], true, NULL),
        ('notifications', 'ix_notification_pending_chronology', ARRAY['created_at','id'], false, 'delivery_pendingistrue')
    ) AS required(table_name, index_name, columns, is_unique, predicate)
    WHERE NOT EXISTS (
        SELECT 1 FROM pg_index i
        JOIN pg_class relation ON relation.oid=i.indrelid
        JOIN pg_namespace ns ON ns.oid=relation.relnamespace
        JOIN pg_class idx ON idx.oid=i.indexrelid
        JOIN pg_am access_method ON access_method.oid=idx.relam
        WHERE ns.nspname=current_schema() AND relation.relname=required.table_name
          AND idx.relname=required.index_name AND i.indisunique=required.is_unique
          AND i.indisvalid AND i.indisready AND access_method.amname='btree'
          AND i.indnatts=cardinality(required.columns)
          AND (SELECT array_agg(attribute.attname::text ORDER BY keys.ordinality)
               FROM unnest(i.indkey) WITH ORDINALITY AS keys(attnum, ordinality)
               JOIN pg_attribute attribute ON attribute.attrelid=i.indrelid AND attribute.attnum=keys.attnum
              )=required.columns
          AND regexp_replace(lower(pg_get_expr(i.indpred,i.indrelid)), '[()[:space:]]', '', 'g')
              IS NOT DISTINCT FROM required.predicate
    );
    IF missing_count > 0 THEN
        RAISE EXCEPTION 'Required concurrency/idempotency indexes missing';
    END IF;
    IF EXISTS (
        SELECT 1 FROM audit_events a
        LEFT JOIN tasks t ON t.id=a.task_id LEFT JOIN users u ON u.id=t.created_by_id
        WHERE a.audit_schema_version=2 AND (u.id IS NULL OR a.tenant_id IS DISTINCT FROM u.tenant_id)
    ) OR EXISTS (
        SELECT 1 FROM xp_ledger x
        LEFT JOIN tasks t ON t.id=x.task_id LEFT JOIN users u ON u.id=t.created_by_id
        LEFT JOIN users r ON r.id=x.user_id
        WHERE x.record_version=2 AND
          (u.id IS NULL OR x.tenant_id IS DISTINCT FROM u.tenant_id OR x.tenant_id IS DISTINCT FROM r.tenant_id)
    ) OR EXISTS (
        SELECT 1 FROM task_activity_contexts c
        JOIN users u ON u.id=c.user_id JOIN tasks t ON t.id=c.task_id JOIN users owner ON owner.id=t.created_by_id
        WHERE c.tenant_id IS DISTINCT FROM u.tenant_id OR c.tenant_id IS DISTINCT FROM owner.tenant_id
    ) THEN
        RAISE EXCEPTION 'Tenant ownership integrity violation; stop activation';
    END IF;
    IF EXISTS (SELECT 1 FROM subtasks WHERE workflow_version=2 AND
        (planned_start_date IS NULL OR planned_end_date IS NULL OR planned_start_date>planned_end_date))
       OR EXISTS (SELECT 1 FROM task_activity_contexts WHERE status='RUNNING' GROUP BY tenant_id,user_id HAVING count(*)>5)
       OR EXISTS (SELECT 1 FROM xp_ledger WHERE record_version=2 AND idempotency_key IS NULL) THEN
        RAISE EXCEPTION 'Workflow, capacity or ledger shape violation; stop activation';
    END IF;
    IF EXISTS (SELECT 1 FROM xp_ledger r JOIN xp_ledger original ON original.id=r.reversal_of_id
        WHERE r.record_version=2 AND (r.points<>-original.points OR r.tenant_id<>original.tenant_id
          OR r.user_id<>original.user_id OR original.reversal_of_id IS NOT NULL)) THEN
        RAISE EXCEPTION 'Invalid compensating ledger entry; stop activation';
    END IF;
    -- Exact frozen guard contracts: another trigger on the same table is insufficient.
    -- Replica-only triggers do not protect ordinary application writes.
    SELECT count(*) INTO missing_count FROM (VALUES
        ('audit_events', 'zea_activity_insert', 7, 'zea_activity_insert_guard'),
        ('audit_events', 'zea_activity_update', 19, 'zea_activity_update_guard'),
        ('audit_events', 'zea_activity_delete', 11, 'zea_activity_delete_guard'),
        ('xp_ledger', 'zea_ledger_insert', 7, 'zea_ledger_insert_guard'),
        ('xp_ledger', 'zea_ledger_update', 19, 'zea_ledger_update_guard'),
        ('xp_ledger', 'zea_ledger_delete', 11, 'zea_ledger_delete_guard'),
        ('task_work_intervals', 'zea_interval_insert', 7, 'zea_interval_insert_guard'),
        ('task_work_intervals', 'zea_interval_update', 19, 'zea_interval_update_guard'),
        ('task_work_intervals', 'zea_interval_delete', 11, 'zea_interval_delete_guard'),
        ('subtasks', 'zea_subtask_insert', 7, 'zea_subtask_insert_guard'),
        ('subtasks', 'zea_subtask_update', 19, 'zea_subtask_update_guard'),
        ('tasks', 'zea_task_owner', 19, 'zea_task_owner_guard'),
        ('users', 'zea_user_tenant', 19, 'zea_user_tenant_guard'),
        ('tasks', 'zea_task_delete', 11, 'zea_task_delete_guard'),
        ('subtasks', 'zea_subtask_delete', 11, 'zea_subtask_delete_guard'),
        ('users', 'zea_user_delete', 11, 'zea_user_delete_guard'),
        ('task_workflow_settings', 'zea_policy_update', 19, 'zea_policy_update_guard'),
        ('task_workflow_settings', 'zea_policy_delete', 11, 'zea_policy_delete_guard'),
        ('audit_events', 'zea_v2_activity_shape_insert', 7, 'zea_v2_activity_shape_insert_guard'),
        ('audit_events', 'zea_v2_activity_shape_update', 19, 'zea_v2_activity_shape_update_guard'),
        ('xp_ledger', 'zea_v2_ledger_shape_insert', 7, 'zea_v2_ledger_shape_insert_guard'),
        ('xp_ledger', 'zea_v2_ledger_shape_update', 19, 'zea_v2_ledger_shape_update_guard'),
        ('subtasks', 'zea_v2_subtask_shape_insert', 7, 'zea_v2_subtask_shape_insert_guard'),
        ('subtasks', 'zea_v2_subtask_shape_update', 19, 'zea_v2_subtask_shape_update_guard'),
        ('tasks', 'zea_v2_task_policy_owner', 19, 'zea_v2_task_policy_owner_guard'),
        ('users', 'zea_v2_user_policy_owner', 19, 'zea_v2_user_policy_owner_guard'),
        ('subtasks', 'zea_v2_subtask_version', 19, 'zea_v2_subtask_version_guard'),
        ('subtasks', 'zea_v2_subtask_transition', 19, 'zea_v2_subtask_transition_guard'),
        ('audit_events', 'zea_v2_audit_events_truncate', 34, 'zea_v2_audit_events_truncate_guard'),
        ('xp_ledger', 'zea_v2_xp_ledger_truncate', 34, 'zea_v2_xp_ledger_truncate_guard'),
        ('task_work_intervals', 'zea_v2_task_work_intervals_truncate', 34, 'zea_v2_task_work_intervals_truncate_guard'),
        ('subtasks', 'zea_v3_subtask_insert', 7, 'zea_v3_subtask_insert_guard'),
        ('subtasks', 'zea_v3_subtask_order', 19, 'zea_v3_subtask_order_guard'),
        ('subtasks', 'zea_v3_subtask_version', 19, 'zea_v3_subtask_version_guard'),
        ('subtasks', 'zea_v3_subtask_delete', 11, 'zea_v3_subtask_delete_guard'),
        ('xp_ledger', 'zea_v3_ledger_shape', 7, 'zea_v3_ledger_shape_guard'),
        ('task_workflow_settings', 'zea_v3_policy_insert', 7, 'zea_v3_policy_insert_guard'),
        ('task_workflow_settings', 'zea_v3_policy_update', 19, 'zea_v3_policy_update_guard'),
        ('xp_ledger', 'zea_v4_ledger_accounting', 7, 'zea_v4_ledger_accounting_guard'),
        ('subtasks', 'zea_v4_subtask_assignee', 7, 'zea_v4_subtask_assignee_guard'),
        ('tasks', 'zea_v4_task_assignee', 19, 'zea_v4_task_assignee_guard'),
        ('users', 'zea_v4_assignee_tenant', 19, 'zea_v4_assignee_tenant_guard'),
        ('task_activity_contexts', 'zea_v5_context_insert', 7, 'zea_v5_context_insert_guard'),
        ('task_activity_contexts', 'zea_v5_context_update', 19, 'zea_v5_context_update_guard'),
        ('task_activity_contexts', 'zea_v5_context_delete', 11, 'zea_v5_context_delete_guard'),
        ('task_work_corrections', 'zea_v5_correction_insert', 7, 'zea_v5_correction_insert_guard'),
        ('task_work_corrections', 'zea_v5_correction_update', 19, 'zea_v5_correction_update_guard'),
        ('task_work_corrections', 'zea_v5_correction_delete', 11, 'zea_v5_correction_delete_guard'),
        ('task_activity_contexts', 'zea_v5_task_activity_contexts_truncate', 34, 'zea_v5_task_activity_contexts_truncate_guard'),
        ('task_work_corrections', 'zea_v5_task_work_corrections_truncate', 34, 'zea_v5_task_work_corrections_truncate_guard'),
        ('notifications', 'zea_notification_owner', 23, 'zea_notification_owner_guard'),
        ('notification_preferences', 'zea_notification_policy', 23, 'zea_notification_policy_guard')
    ) AS required(table_name, trigger_name, type_bits, function_name)
    WHERE NOT EXISTS (SELECT 1 FROM pg_trigger trigger
        JOIN pg_class relation ON relation.oid=trigger.tgrelid
        JOIN pg_namespace ns ON ns.oid=relation.relnamespace
        JOIN pg_proc handler ON handler.oid=trigger.tgfoid
        WHERE ns.nspname=current_schema() AND relation.relname=required.table_name
          AND trigger.tgname=required.trigger_name AND trigger.tgtype=required.type_bits
          AND trigger.tgenabled IN ('O','A') AND NOT trigger.tgisinternal
          AND handler.pronamespace=ns.oid AND handler.proname=required.function_name);
    IF missing_count>0 THEN
        RAISE EXCEPTION 'Essential task audit guards missing or disabled';
    END IF;
END
$gate$;

SELECT
    'PASS' AS schema_and_ownership_gate,
    (SELECT count(*) FROM subtasks WHERE workflow_version=2) AS managed_subtasks,
    (SELECT count(*) FROM xp_ledger WHERE record_version=2) AS immutable_ledger_entries,
    (SELECT count(*) FROM notifications WHERE delivery_pending IS TRUE) AS pending_notifications,
    (SELECT count(*) FROM task_activity_contexts WHERE status='RUNNING') AS active_contexts;
ROLLBACK;

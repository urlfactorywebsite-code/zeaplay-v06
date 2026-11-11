"""Frozen Phase 6 ownership guard contract for migrations/fresh databases."""


def statements(dialect):
    invalid = """NEW.dedupe_key IS NOT NULL AND (
        NEW.tenant_id IS NULL OR NEW.alert_kind IS NULL OR
        NOT EXISTS (SELECT 1 FROM users u WHERE u.id=NEW.user_id AND u.tenant_id=NEW.tenant_id) OR
        (NEW.related_task_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM tasks t JOIN users u ON u.id=t.created_by_id
            WHERE t.id=NEW.related_task_id AND u.tenant_id=NEW.tenant_id)))"""
    distinct = "IS DISTINCT FROM" if dialect == "postgresql" else "IS NOT"
    changed = " OR ".join(
        f"NEW.{key} {distinct} OLD.{key}"
        for key in (
            "user_id",
            "tenant_id",
            "dedupe_key",
            "alert_kind",
            "related_task_id",
        )
    )
    # Reassignment/soft deletion must not prevent dismissing a stored alert.
    # Its original ownership and deduplication key remain immutable.
    update_invalid = f"(OLD.dedupe_key IS NOT NULL AND ({changed})) OR (OLD.dedupe_key IS NULL AND ({invalid}))"
    pref_invalid = "NEW.near_deadline_hours <= 0 OR NEW.near_deadline_hours > 8760 OR NEW.overtime_threshold_minutes < 0 OR NEW.overtime_threshold_minutes > 1440 OR (NEW.productive_capacity_hours IS NOT NULL AND NOT (NEW.productive_capacity_hours > 0 AND NEW.productive_capacity_hours <= 24))"
    if dialect == "postgresql":
        return [
            f"CREATE OR REPLACE FUNCTION zea_notification_owner_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF TG_OP='INSERT' THEN IF {invalid} THEN RAISE EXCEPTION 'notification ownership mismatch' USING ERRCODE='23514'; END IF; ELSE IF {update_invalid} THEN RAISE EXCEPTION 'notification ownership immutable' USING ERRCODE='23514'; END IF; END IF; RETURN NEW; END $$",
            "DROP TRIGGER IF EXISTS zea_notification_owner ON notifications",
            "CREATE TRIGGER zea_notification_owner BEFORE INSERT OR UPDATE ON notifications FOR EACH ROW EXECUTE FUNCTION zea_notification_owner_guard()",
            f"CREATE OR REPLACE FUNCTION zea_notification_policy_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF {pref_invalid} THEN RAISE EXCEPTION 'invalid workload policy' USING ERRCODE='23514'; END IF; RETURN NEW; END $$",
            "DROP TRIGGER IF EXISTS zea_notification_policy ON notification_preferences",
            "CREATE TRIGGER zea_notification_policy BEFORE INSERT OR UPDATE ON notification_preferences FOR EACH ROW EXECUTE FUNCTION zea_notification_policy_guard()",
        ]
    if dialect == "sqlite":
        result = []
        for operation in ("INSERT", "UPDATE"):
            name = f"zea_notification_owner_{operation.lower()}"
            result += [
                f"DROP TRIGGER IF EXISTS {name}",
                f"CREATE TRIGGER {name} BEFORE {operation} ON notifications WHEN {invalid if operation == 'INSERT' else update_invalid} BEGIN SELECT RAISE(ABORT, 'notification ownership mismatch'); END",
            ]
            name = f"zea_notification_policy_{operation.lower()}"
            result += [
                f"DROP TRIGGER IF EXISTS {name}",
                f"CREATE TRIGGER {name} BEFORE {operation} ON notification_preferences WHEN {pref_invalid} BEGIN SELECT RAISE(ABORT, 'invalid workload policy'); END",
            ]
        return result
    raise RuntimeError("Unsupported notification database")

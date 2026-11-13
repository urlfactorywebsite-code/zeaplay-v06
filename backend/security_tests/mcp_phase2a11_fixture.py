"""Minimal, run-guarded synthetic ticket participation control. No storage access."""
import json
import sys
import uuid

import mcp_phase1_5_backend as fixture
fixture.verify()
from sqlalchemy import select
from sqlalchemy.orm import Session
from app import models
from app.tickets.models import TicketParticipant, TicketParticipantRoleEnum

payload = json.loads(sys.argv[1])
assert payload['action'] in ('grant', 'remove')
with Session(fixture.engine) as db:
    user = db.get(models.User, payload['user'])
    assert user and user.email.startswith('phase2a11-') and user.email.endswith('@phase15.example.com')
    assert str(user.tenant_id) == fixture.ident('tenant-a')
    ticket_id = uuid.UUID(fixture.ident('ticket-a'))
    rows = db.scalars(select(TicketParticipant).where(TicketParticipant.ticket_id == ticket_id,
                     TicketParticipant.user_id == user.id)).all()
    if payload['action'] == 'grant':
        assert not rows
        db.add(TicketParticipant(tenant_id=user.tenant_id, ticket_id=ticket_id,
            user_id=user.id, role=TicketParticipantRoleEnum.FOLLOWER))
    else:
        assert len(rows) == 1
        from datetime import datetime
        rows[0].deleted_at = datetime.utcnow()
    db.commit()
print(json.dumps({'committed': True, 'action': payload['action']}))

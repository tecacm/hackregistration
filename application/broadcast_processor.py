from time import sleep
from django.utils import timezone

from application.models import Broadcast, BroadcastRecipient, Application, ApplicationLog
from app.emails import Email, EmailList


def process_one_broadcast(broadcast_id: int, batch_size: int = 100, delay_ms: int = 500, max_retries: int = 2) -> None:
    """Process a single Broadcast until completion or failure.

    This is safe to call from a background thread. It does not raise on ESP errors;
    it records failures on recipients and moves on.
    """
    try:
        b = Broadcast.objects.get(id=broadcast_id)
    except Broadcast.DoesNotExist:
        return

    # Mark running if pending
    if b.status == Broadcast.STATUS_PENDING:
        b.status = Broadcast.STATUS_RUNNING
        b.save(update_fields=['status'])

    bs = max(1, int(batch_size or 100))
    delay = max(0, int(delay_ms or 0)) / 1000.0
    retries = max(0, int(max_retries or 0))

    pending = BroadcastRecipient.objects.filter(broadcast=b, status=BroadcastRecipient.STATUS_PENDING)
    accepted_total = int(b.accepted or 0)
    while True:
        batch = list(pending.values_list('id', 'email', 'application_id')[:bs])
        if not batch:
            break

        elist = EmailList()
        for rid, email, _ in batch:
            elist.add(Email('custom_broadcast', {'subject': b.subject, 'message': b.message, 'include_discord': b.include_discord}, to=email))

        try:
            accepted = elist.send_all(fail_silently=False) or 0
        except Exception:
            # Best-effort retry silently
            try:
                accepted = elist.send_all(fail_silently=True) or 0
            except Exception:
                accepted = 0

        # Assume success for all in the batch when provider accepted > 0
        sent_ids = {rid for rid, *_ in batch} if accepted else set()
        for rid, email, app_id in batch:
            try:
                r = BroadcastRecipient.objects.get(id=rid)
            except BroadcastRecipient.DoesNotExist:
                continue
            if rid in sent_ids:
                r.status = BroadcastRecipient.STATUS_SENT
                r.attempts = (r.attempts or 0) + 1
                r.updated_at = timezone.now()
                r.save(update_fields=['status', 'attempts', 'updated_at'])
                # Log on application
                try:
                    app = Application.objects.get(pk=app_id)
                    log = ApplicationLog(application=app, user=b.created_by, name='Email broadcast', comment=b.subject)
                    log.changes = {'segment_email': {'recipient': email, 'broadcast_id': b.run_id, 'delivery': 'sent'}}
                    log.save()
                except Exception:
                    pass
            else:
                r.attempts = (r.attempts or 0) + 1
                r.last_error = 'Unknown failure'
                r.updated_at = timezone.now()
                if r.attempts > retries:
                    r.status = BroadcastRecipient.STATUS_FAILED
                r.save(update_fields=['attempts', 'last_error', 'updated_at', 'status'])

        accepted_total += int(accepted or 0)
        b.accepted = accepted_total
        b.save(update_fields=['accepted'])
        sleep(delay)
        pending = BroadcastRecipient.objects.filter(broadcast=b, status=BroadcastRecipient.STATUS_PENDING)

    # finalize status
    if BroadcastRecipient.objects.filter(broadcast=b, status=BroadcastRecipient.STATUS_PENDING).exists():
        b.status = Broadcast.STATUS_RUNNING
    else:
        failed = BroadcastRecipient.objects.filter(broadcast=b, status=BroadcastRecipient.STATUS_FAILED).exists()
        b.status = Broadcast.STATUS_FAILED if failed else Broadcast.STATUS_COMPLETED
    b.save(update_fields=['status'])


def process_pending(max_broadcasts: int = 5, batch_size: int = 100, delay_ms: int = 500, max_retries: int = 2) -> None:
    """Process up to N pending/running broadcasts in FIFO order."""
    limit = max(1, int(max_broadcasts or 1))
    qs = Broadcast.objects.filter(status__in=[Broadcast.STATUS_PENDING, Broadcast.STATUS_RUNNING]).order_by('created_at')[:limit]
    for b in qs:
        process_one_broadcast(b.id, batch_size=batch_size, delay_ms=delay_ms, max_retries=max_retries)

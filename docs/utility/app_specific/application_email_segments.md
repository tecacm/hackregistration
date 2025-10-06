# Application email segments

Use the **Email small/no-team applicants** admin action to send targeted reminders to hackers.

1. Open the Django admin at `/<ADMIN_URL>/application/application/`.
2. Filter the list to the audience you want to reach (for example, hackers in the current edition).
3. The **Email small/no-team applicants…** action ignores individual selections and instead uses your filters, so you can trigger it without ticking every checkbox.
4. Fill out the form to preview or queue the broadcast. Toggle **Include Discord invite** if you want to append (or remove) the “Join our Discord” button from the outgoing message. The preview shows a sample of recipients and renders the message using the standard `custom_broadcast` template.

Behind the scenes the form can submit thousands of hidden inputs when a large result set is in view. Django previously rejected those requests with `TooManyFieldsSent`. The platform now raises `DATA_UPLOAD_MAX_NUMBER_FIELDS` to 20,000 (override via the `DATA_UPLOAD_MAX_NUMBER_FIELDS` environment variable) so bulk previews keep working even with thousands of rows.

If you still see a 400 Bad Request, double-check that your deployment picked up the updated setting and that the proxy in front of Django allows similarly large form submissions.

# Track assignment workflow

This guide outlines how organizers should operate the automatic track assignment tooling once team preferences are in place. The workflow combines an admin-only control panel with a supporting management command so you can preview results, run the final assignment, and notify teams in a single place.

## Prerequisites
- Teams must have submitted valid track preferences (three unique choices each).
- All teammates must hold an invited, confirmed, or attended status; ineligible teams are automatically skipped.
- Track capacities are defined in `friends.models.FriendsCode.TRACK_CAPACITY`. Adjust values there before running assignments if sponsors tweak allocations.

## Runner options
There are two supported entry points:

1. **Django admin interface** – Recommended for day-to-day operations.
2. **Management command** – Useful for scripts, automation, or when running from a terminal session.

### 1. Django admin control panel
1. Navigate to **Admin → Friends → Friends codes**.
2. Click the **Auto-assign tracks** button above the changelist to open the automation console.
3. Choose your options:
   - **Limit** – Optional integer to cap how many teams are processed in this pass. Leave blank to include everyone.
   - **Dry run** – Tick this first. It reports the teams that would be assigned without persisting any changes or emailing anyone.
   - **Skip notification emails** – Check this only if you plan to review assignments manually or send communications separately. Leaving it unchecked sends the `track_assigned` email to every member of each assigned team.
4. Submit the form.
   - After a dry run, review the preview table that lists the proposed track, preference slot used, and team size for each team. A second table explains why any teams were skipped (missing preferences, no longer eligible, or out of capacity).
   - When happy, uncheck **Dry run** and run again. The system writes the assignment to every `FriendsCode` row in the team, sets the timestamp, and triggers emails unless suppressed.
5. Return to the changelist to spot-check. Each team’s `track_assigned` column should now reflect the assigned sponsor track.

### 2. Management command
For direct shell usage you can launch:

```bash
python manage.py assign_tracks [--dry-run] [--limit N] [--skip-email]
```

Flags mirror the admin console:
- `--dry-run` previews without saving or emailing.
- `--limit` caps the number of teams processed.
- `--skip-email` prevents the notification from being sent.

### Operational tips
- Always perform a dry run first. It verifies that capacities still have space and that no teams are blocked by status changes.
- Run the tool in batches if you expect sponsor allocations to change mid-event—use the limit control to assign an initial group, adjust capacities, and then resume.
- The service respects legacy assignments; teams already holding a track are ignored, so re-running is safe when new preferences arrive.
- Skipped teams are left untouched, so you can resolve issues (e.g., missing preferences) and run the tool again.

## Email notification review
Each assigned team triggers the `track_assigned` email by default. Confirm that your branding and copy are correct before launching (see next section).

- HTML template: `mails/track_assigned.html`
- Plain-text template: `mails/track_assigned.txt`

Make edits if sponsors request specific messaging, then run a dry run with **Skip notification emails** unchecked for a single test team to confirm rendering via the admin message logs or your local mail backend.

## Troubleshooting
- **No assignments produced** – Ensure the edition’s track selection window is open and teams have saved preferences. Check that capacities still have headroom.
- **Teams skipped as “not eligible”** – One or more members likely reverted to a pending status. Ask the admissions team to update the application status or wait until their confirmation is complete.
- **All preferences full** – Increase capacity or manually reassign a few teams to different tracks to free space, then rerun the command.
- **Emails not sending** – If running in DEBUG mode the system writes email files under `mails/track_assigned/`. In production, verify SMTP credentials in Django settings.

# Team matchmaking workflow [+](/friends.)

The team matchmaking flow helps solo hackers and small teams (1–3 pending members) get paired with other opt-in teams to reach the target size of four. It combines outreach, a self-service opt-in page, an organizer-facing pool, automated/ manual matching, and notification emails.

## Overview

1. **Outreach** – Eligible pending applicants receive a call-to-action email with a unique opt-in token.
2. **Opt-in** – One teammate clicks the link to confirm their group for the pool, which records the team in the `FriendsMergePoolEntry` table and toggles the `seeking_merge` flag on their `FriendsCode`.
3. **Pool review** – Organizers can monitor the pool via Django admin (`Friends ➜ Friends merge pool entries`) and the audit trail via `Friends merge event logs`.
4. **Matching** – The matching service groups compatible entries (default target size four, optional fallback to three near the deadline) and merges the underlying `FriendsCode` records.
5. **Notifications** – Matched teams automatically receive an intro email with everyone’s contact details.

## Participant outreach email

Run the management command `send_merge_invites` to email eligible users. It looks at the default (or specified) edition and builds one invite per team or solo applicant with a *pending* application status.

Key options:

- `--edition <id>` – Target a specific edition instead of the default.
- `--dry-run` – Print the recipients without sending any emails. Useful for spot checks.
- `--limit <count>` – Cap how many teams are contacted in the current run.
- `--resend` – Include teams already flagged as `seeking_merge`. Use when re-opening the pool.

Example dry run:

```
python manage.py send_merge_invites --dry-run --limit 20
```

Each email renders from `app/templates/mails/team_merge_invite.html` / `.txt` and contains a single-use tokenized URL (`MatchmakingService.generate_opt_in_token`). The default deadline text comes from the `FRIENDS_MERGE_DEADLINE` setting (UTC aware datetime); override it in `app/settings.py` or `hackathon_variables.py` if the campaign window changes.

## Opt-in landing page

Recipients land on `friends/merge_opt_in.html`. The view validates the signed token (`MatchmakingService.process_opt_in_token`) and handles:

- Creating a `FriendsCode` for true solos.
- Rejecting teams that now have invited/confirmed members or more than three pending hackers.
- Updating/creating the `FriendsMergePoolEntry` with status `pending` and logging an `opt_in` event.

Successful responses display a green success banner; error states (expired tokens, ineligible teams, already matched) surface a red alert with context the team can forward to support.

### Token behaviour

- Default expiry is seven days (`FRIENDS_MERGE_TOKEN_MAX_AGE`). Override the setting for longer or shorter campaigns.
- Re-using the link after opting in returns a friendly “already in the pool” message and logs the duplicate opt-in.

## Organizer tooling in admin

Navigate to **Friends ➜ Friends merge pool entries** to review every opt-in:

- Columns show the edition, team code, headcount, status (`pending`, `matched`, `removed`), trigger (`auto`, `manual`, `deadline`), and timestamps.
- Use the **Merge selected entries** action to create an immediate match between selected rows. The total headcount must be three or four, and all entries must belong to the same edition.
- Use **Remove from pool (and reset seeking flag)** to mark teams as `removed`, clear their `seeking_merge` flag, and log the action.

Audit details live in **Friends ➜ Friends merge event logs**, recording every opt-in, merge, removal, and notification with timestamps, actor, and metadata. You can filter by event type or search by team code.

### Manual team membership updates

Head to **Friends ➜ Friends codes ➜ Manage team members** to fix individual memberships without running shell scripts:

- **Add or move** a hacker by entering their email and (optionally) the destination team code. Leave the code blank to generate a fresh team for them. The tool respects the `FRIENDS_MAX_CAPACITY` setting and logs every change in `Friends membership logs`.
- **Remove** a hacker from their current team with a single confirmation checkbox. Any related merge-pool entries are refreshed automatically so organizers see the latest headcounts.

### Matchmaking invite console

From the **Matchmaking controls** button on the merge-pool changelist you can now preview the full invite run before sending:

- Use the **Preview run** button to list the first 25 teams/solos, showing every recipient name and email, plus a rendered sample of the exact HTML that will be delivered. The page also tracks the total recipient count and highlights when additional entries exist beyond the preview.
- Optionally fill **Preview email** to send yourself (or another organizer) the first invite without contacting the whole list—perfect for reviewing personalized greetings and branding.
- When you're satisfied, click **Send invites** to queue the campaign. Success and error states continue to appear via the standard Django admin message banner.

The invite template (`team_merge_invite.html`) now greets each hacker by name, uses the HackMTY purple button, and explicitly calls out why they're receiving the message, where to reach support, and how to stay connected through Discord and social links.

## Running automated matches

The `MatchmakingService` packs groups based on their eligible member counts:

- 3 + 1, 2 + 2, 2 + 1 + 1, or 1 + 1 + 1 + 1 for target size four.
- Optional “deadline mode” groups size-three teams (3 or 2 + 1 or 1 + 1 + 1) when a full four-person match doesn’t exist.

Launch a shell when you’re ready to run automated matching:

```
python manage.py shell
```

Then execute, for example:

```python
from friends.matchmaking import MatchmakingService
results = MatchmakingService.run_matching(allow_size_three=False)
```

Arguments:

- `edition` – Pass an `Edition` instance or primary key to override the default.
- `allow_size_three` – Set to `True` near the deadline to form teams of three when four-person matches are no longer possible. These entries get the `deadline` trigger.
- `trigger` – Optional custom label stored on the merged entries (defaults to `auto`).

Each returned `MatchGroupResult` exposes the `team_code`, the merged `member_ids`, and the trigger used. The helper automatically:

- Re-validates eligibility (removing teams that no longer qualify).
- Reassigns all matching `FriendsCode` rows to the host team code.
- Clears `seeking_merge` flags.
- Sends the `team_merge_match` email with a table of members and contact fields. The parser looks for a `<div id="socials-content">` block, so keep that element in custom templates.
- Logs both the match (`matched`) and the notification (`notified`) events.

## Settings reference

| Setting | Default | Purpose |
|---------|---------|---------|
| `FRIENDS_MAX_CAPACITY` | 4 | Controls the target team size and who is eligible (teams with ≤ target - 1 members are invited). |
| `FRIENDS_MERGE_TOKEN_MAX_AGE` | 7 days | Expiration window for opt-in tokens. |
| `FRIENDS_MERGE_DEADLINE` | 2025-10-11 12:00 UTC | Deadline text displayed in the invite email and returned by `_deadline_display()`. |

## Troubleshooting tips

- **No pending entries** – Check that applicants still have status `Pending` and that they have a `FriendsCode`. Solo applicants get virtual codes during invite generation.
- **Emails missing contact info** – Ensure the application form stores relevant fields in `form_data`. The service looks for phone, university, degree, and country using key fallbacks defined in `CONTACT_FIELD_CANDIDATES`.
- **Duplicate opt-ins** – Expected behaviour; the event log will note `duplicate: True` metadata but no duplicate pool entry is created.
- **Templates not found** – Email templates must live under `app/templates/mails/` so the global email helper can render them.

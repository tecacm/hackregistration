from django.core.management.base import BaseCommand

from friends.matchmaking import MatchmakingService


class Command(BaseCommand):
    help = 'Send the matchmaking opt-in email to eligible teams and solo participants.'

    def add_arguments(self, parser):
        parser.add_argument('--edition', type=int, help='Edition ID to target (defaults to current edition).')
        parser.add_argument('--limit', type=int, help='Restrict the number of teams contacted in this run.')
        parser.add_argument('--dry-run', action='store_true', help='Preview recipients without sending any email.')
        parser.add_argument('--resend', action='store_true', help='Include teams already in the pool when generating invites.')

    def handle(self, *args, **options):
        edition = MatchmakingService.get_edition(options.get('edition'))
        invites = MatchmakingService.gather_invite_targets(edition, include_existing=options.get('resend', False))
        if not invites:
            self.stdout.write(self.style.WARNING('No eligible teams or individuals found.'))
            return

        limit = options.get('limit')
        if limit is not None:
            invites = invites[:limit]

        dry_run = options.get('dry_run', False)
        sent = 0
        for invite in invites:
            emails = [app.user.email for app in invite.members if app.user.email]
            if not emails:
                continue
            label = invite.team_code or f"solo-{invite.members[0].user_id}"
            if dry_run:
                self.stdout.write(f"[DRY RUN] Would send opt-in email to {', '.join(emails)} (team {label}).")
                sent += 1
                continue
            MatchmakingService.send_invite(invite)
            sent += 1
            self.stdout.write(f"Sent opt-in email to {', '.join(emails)} (team {label}).")

        summary = 'emails previewed' if dry_run else 'emails queued'
        self.stdout.write(self.style.SUCCESS(f'{sent} {summary}.'))

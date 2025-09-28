from django.core.management.base import BaseCommand
from application.broadcast_processor import process_pending


class Command(BaseCommand):
    help = 'Process pending broadcast emails in the background with batching, rate limiting, and retries.'

    def add_arguments(self, parser):
        parser.add_argument('--batch-size', type=int, default=100, help='Recipients per batch send')
        parser.add_argument('--delay-ms', type=int, default=500, help='Delay between batches (ms)')
        parser.add_argument('--max-retries', type=int, default=2, help='Retries per recipient on failure')
        parser.add_argument('--max-broadcasts', type=int, default=5, help='Max broadcasts to process this run')

    def handle(self, *args, **opts):
        process_pending(
            max_broadcasts=opts['max_broadcasts'],
            batch_size=opts['batch_size'],
            delay_ms=opts['delay_ms'],
            max_retries=opts['max_retries'],
        )

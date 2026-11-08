"""Run one bounded batch of due developer webhook deliveries.

Schedule this module from a worker/cron process (for example every minute).
It is deliberately not exposed as an unauthenticated HTTP endpoint.
"""
import argparse
import json

from app.api.developer_webhooks import run_webhook_worker


def main():
    parser = argparse.ArgumentParser(description="Process due OneCore webhook deliveries")
    parser.add_argument("--batch-size", type=int, default=25)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 250:
        parser.error("--batch-size must be between 1 and 250")
    print(json.dumps(run_webhook_worker(args.batch_size), default=str))


if __name__ == "__main__":
    main()

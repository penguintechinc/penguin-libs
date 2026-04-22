"""CLI entry point for penguin-email.

Usage::

    python -m penguin_email auth --credentials credentials.json --token token.json
    python -m penguin_email check

Or via the console script::

    penguin-email auth --credentials credentials.json --token token.json
    penguin-email check
"""

from __future__ import annotations

import argparse
import os
import sys


def _cmd_auth(args: argparse.Namespace) -> int:
    """Run the Gmail OAuth2 flow and save the token."""
    try:
        from .auth.gmail_oauth import run_oauth_flow
    except ImportError:
        print(
            "ERROR: Gmail support not installed. "
            "Run: pip install 'penguin-email[gmail]'",
            file=sys.stderr,
        )
        return 1

    run_oauth_flow(
        credentials_path=args.credentials,
        token_path=args.token,
        scopes=args.scopes or None,
    )
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    """Run a health check on the configured transport."""
    mode = os.environ.get("EMAIL_TRANSPORT", "smtp").lower()

    if mode == "gmail":
        try:
            from .transports.gmail import GmailTransport

            transport = GmailTransport.from_env()
        except ImportError:
            print(
                "ERROR: Gmail support not installed. "
                "Run: pip install 'penguin-email[gmail]'",
                file=sys.stderr,
            )
            return 1
        except KeyError as exc:
            print(f"ERROR: Missing environment variable: {exc}", file=sys.stderr)
            return 1
    else:
        from .transports.smtp import SmtpMode, SmtpTransport

        host = os.environ.get("SMTP_HOST", "localhost")
        port_str = os.environ.get("SMTP_PORT", "")
        mode_str = os.environ.get("SMTP_MODE", "starttls").upper()
        username = os.environ.get("SMTP_USERNAME", "")
        password = os.environ.get("SMTP_PASSWORD", "")

        try:
            smtp_mode = SmtpMode[mode_str]
        except KeyError:
            print(f"ERROR: Unknown SMTP_MODE '{mode_str}'", file=sys.stderr)
            return 1

        transport = SmtpTransport(
            host=host,
            port=int(port_str) if port_str else None,
            mode=smtp_mode,
            username=username,
            password=password,
        )

    ok = transport.health_check()
    if ok:
        print(f"✓ Transport '{transport.transport_name}' is healthy.")
        return 0
    else:
        print(f"✗ Transport '{transport.transport_name}' health check FAILED.", file=sys.stderr)
        return 1


def main() -> None:
    """Entry point for ``penguin-email`` console script."""
    parser = argparse.ArgumentParser(
        prog="penguin-email",
        description="penguin-email CLI — manage Gmail OAuth2 and check transport health",
    )
    subparsers = parser.add_subparsers(dest="command")

    # auth subcommand
    auth_parser = subparsers.add_parser("auth", help="Run Gmail OAuth2 flow")
    auth_parser.add_argument(
        "--credentials",
        default="credentials.json",
        help="Path to Google credentials.json (default: credentials.json)",
    )
    auth_parser.add_argument(
        "--token",
        default="token.json",
        help="Output path for token.json (default: token.json)",
    )
    auth_parser.add_argument(
        "--scopes",
        nargs="*",
        help="OAuth2 scopes (default: gmail.send)",
    )

    # check subcommand
    subparsers.add_parser(
        "check",
        help="Health-check the configured transport (reads EMAIL_TRANSPORT env var)",
    )

    args = parser.parse_args()

    if args.command == "auth":
        sys.exit(_cmd_auth(args))
    elif args.command == "check":
        sys.exit(_cmd_check(args))
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()

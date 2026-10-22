"""Add someone to Xplorers' staff -- the people who can send owner invitations.

    python -m src.staff.create --email you@example.com

There is no route for this on purpose: staff accounts are made by a person with access to
the server, so the way in cannot be reached from the internet. The password is asked for
at the prompt, never taken from the command line, so it is not left in a shell history.

It writes to whatever DATABASE_URL points at, so it prints that host first -- check it is
the database you mean. On Railway, run it inside the API service, which has the private
database address:

    railway ssh --service <api> -- python -m src.staff.create --email you@example.com
"""

import argparse
import asyncio
import getpass
import sys

from src.core.exceptions import ConflictError, ValidationError


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--email", required=True, help="the person's work email")
    args = parser.parse_args(argv)

    from sqlalchemy.engine import make_url

    from src.core.cryptography.bcrypt.adapter import BcryptHashingService
    from src.core.cryptography.fernet.adapter import FernetEncryptionService
    from src.core.database.sqlalchemy.core import async_session_factory
    from src.core.settings.shared import settings
    from src.staff.sqlalchemy import adapter
    from src.staff.use_cases import auth as auth_use_cases

    print(f"Writing to database host: {make_url(settings.DATABASE_URL).host}", file=sys.stderr)

    password = getpass.getpass("Password: ")
    if getpass.getpass("Again: ") != password:
        print("The two passwords differ.", file=sys.stderr)
        return 1

    async with async_session_factory() as session:

        async def get_by_email_hash(email_hash: str):
            return await adapter.get_member_by_email_hash(session, email_hash)

        async def create(member):
            return await adapter.create_member(session, member)

        try:
            staff = await auth_use_cases.create_staff_member(
                email=args.email,
                password=password,
                get_staff_member_by_email_hash_fn=get_by_email_hash,
                create_staff_member_fn=create,
                hashing_service=BcryptHashingService(),
                encryption_service=FernetEncryptionService(settings.CRYPTOGRAPHY_FERNET_KEY),
            )
        except (ConflictError, ValidationError) as error:
            print(error.message, file=sys.stderr)
            return 1
        await session.commit()

    print(f"Staff member {args.email.strip()} created ({staff.id}).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

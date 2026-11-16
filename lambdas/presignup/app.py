"""cascade-presignup: Cognito pre sign-up trigger.

Accounts use a username and password only (no email or phone), so there is no confirmation code to send:
the account is confirmed at sign-up. No attribute is auto-verified (there is none to verify). The trade-off,
documented in docs/infrastructure.md: without a verified email, a forgotten password cannot be self-reset.
"""
import re

USERNAME_RE = re.compile(r"[A-Za-z0-9_.-]{3,32}")


def lambda_handler(event, context):
    username = (event or {}).get("userName") or ""
    if not USERNAME_RE.fullmatch(username):
        # Cognito shows this message to the client as a UserLambdaValidationException.
        raise Exception("Usernames are 3-32 characters: letters, numbers, dot, dash or underscore.")
    event.setdefault("response", {})
    event["response"]["autoConfirmUser"] = True
    event["response"]["autoVerifyEmail"] = False
    event["response"]["autoVerifyPhone"] = False
    return event

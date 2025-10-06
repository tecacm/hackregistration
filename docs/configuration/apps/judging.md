# Judging app configuration

## Judge sign-up invite codes

Judge registration is protected by an invite-code gate so only approved reviewers can create accounts. Codes can now be administered entirely from the Django admin, which means no more redeploys just to add or deactivate a code.

### Managing codes in the admin

1. Sign in to the Django admin and open **Judging → Judge invite codes**.
2. Create a new record for each code you want to distribute:
   - **Code**: the exact string the judge will enter. Codes are case-insensitive when validated.
   - **Label / Notes**: optional context for organisers (e.g. “Fintech round judges”).
   - **Active**: uncheck this to revoke a code without deleting it.
   - **Max uses** *(optional)*: set a usage limit; leave blank for unlimited. The system tracks usage counts and automatically deactivates the code once the limit is reached.
3. Share the code with your judges. As they register, the usage counter and last-used timestamp update automatically.

### Optional environment fallback

If you still need a quick one-off code without using the admin, you can define the `JUDGE_SIGNUP_CODES` environment variable. The form will accept any value in that comma-separated list in addition to the database-managed codes. Example:

```ini
JUDGE_SIGNUP_CODES=alpha-judge-2025,beta-panel-2025
```

Restart the application after changing the environment variable so Django picks up the new values.

### Generating fresh codes

Use Python's `secrets` module to generate random, hard-to-guess codes:

```bash
python - <<'PY'
from secrets import token_urlsafe
for _ in range(5):
    print(token_urlsafe(12))
PY
```

Copy the values you want, add them via the admin (or the environment fallback), and distribute them to the appropriate judges. Remove or deactivate codes once the event wraps up to prevent reuse.

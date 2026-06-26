"""models/instagram.py — DB queries for instagram_accounts table."""

from database.mysql import get_db


def count_by_user(user_id: str) -> int:
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT COUNT(*) as count FROM instagram_accounts WHERE user_id = ?",
            (user_id,),
        )
        return cursor.fetchone()["count"]


def create(
    id: str, user_id: str, instagram_id: str, access_token: str,
    username: str, connected_at: str, status: str,
) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO instagram_accounts "
            "(id, user_id, instagram_id, access_token, username, connected_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (id, user_id, instagram_id, access_token, username, connected_at, status),
        )
        conn.commit()


def get_all_by_user(user_id: str) -> list:
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM instagram_accounts WHERE user_id = ?", (user_id,)
        )
        return cursor.fetchall()


def delete(account_id: str, user_id: str) -> None:
    with get_db() as conn:
        conn.execute(
            "DELETE FROM instagram_accounts WHERE id = ? AND user_id = ?",
            (account_id, user_id),
        )
        conn.commit()


def save_oauth_state(state: str, user_id: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO oauth_states (state, user_id) VALUES (?, ?)",
            (state, user_id),
        )
        conn.commit()


def pop_oauth_state(state: str, ttl_seconds: int = 600):
    """
    Atomically consume a one-time state token.

    Returns user_id if the state exists and is within ttl_seconds of creation.
    Deletes the row regardless (expired or not) to prevent replay attacks.
    Returns None when the state is unknown, already used, or expired.

    Age is computed entirely in MySQL via TIMESTAMPDIFF to avoid Python
    timezone bugs — MySQL TIMESTAMP columns are UTC; Python datetime.now()
    is local time, which causes wrong age calculations on non-UTC servers.
    """
    with get_db() as conn:
        # Fetch the row plus server-computed age in one query.
        # TIMESTAMPDIFF(SECOND, created_at, NOW()) gives age in seconds
        # entirely within MySQL's timezone context — no Python timezone involved.
        cursor = conn.execute(
            """SELECT user_id,
                      TIMESTAMPDIFF(SECOND, created_at, NOW()) AS age_seconds
               FROM oauth_states
               WHERE state = ?""",
            (state,),
        )
        row = cursor.fetchone()

        # Always delete — whether valid, expired, or already consumed.
        # This makes the token single-use and prevents replay attacks.
        conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        conn.commit()

        if not row:
            print(f"[oauth_state] MISS: state={state!r} — not found (already used, expired, or never created)")
            return None

        age = row["age_seconds"] or 0
        if age > ttl_seconds:
            print(f"[oauth_state] EXPIRED: state={state!r} age={age}s ttl={ttl_seconds}s")
            return None

        print(f"[oauth_state] VALID: state={state!r} age={age}s user_id={row['user_id']}")
        return row["user_id"]


def get_by_user_and_instagram_id(user_id: str, instagram_id: str):
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM instagram_accounts WHERE user_id = ? AND instagram_id = ?",
            (user_id, instagram_id),
        )
        return cursor.fetchone()


def update_token(account_id: str, access_token: str, username: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE instagram_accounts SET access_token = ?, username = ?, status = 'active' WHERE id = ?",
            (access_token, username, account_id),
        )
        conn.commit()


def update_token_full(
    account_id: str,
    access_token: str,
    username: str,
    account_type: str = None,
    token_scopes: str = None,
    token_expires_at: str = None,
    facebook_page_id: str = None,
    page_access_token: str = None,
) -> None:
    """Update token plus all metadata from the OAuth exchange."""
    with get_db() as conn:
        conn.execute(
            """UPDATE instagram_accounts
               SET access_token = ?, username = ?, status = 'active',
                   account_type = ?, token_scopes = ?, token_expires_at = ?,
                   facebook_page_id  = COALESCE(?, facebook_page_id),
                   page_access_token = COALESCE(?, page_access_token)
               WHERE id = ?""",
            (access_token, username, account_type, token_scopes, token_expires_at,
             facebook_page_id, page_access_token, account_id),
        )
        conn.commit()


def create_full(
    id: str, user_id: str, instagram_id: str, access_token: str,
    username: str, connected_at: str, status: str,
    account_type: str = None, token_scopes: str = None, token_expires_at: str = None,
    facebook_page_id: str = None, page_access_token: str = None,
) -> None:
    """Create a new account row with full OAuth metadata."""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO instagram_accounts
               (id, user_id, instagram_id, access_token, username, connected_at, status,
                account_type, token_scopes, token_expires_at, facebook_page_id, page_access_token)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (id, user_id, instagram_id, access_token, username, connected_at, status,
             account_type, token_scopes, token_expires_at, facebook_page_id, page_access_token),
        )
        conn.commit()


def get_expiring_tokens(within_days: int = 7) -> list:
    """Return accounts whose access token expires within `within_days` days."""
    with get_db() as conn:
        cursor = conn.execute(
            """SELECT * FROM instagram_accounts
               WHERE status = 'active'
                 AND token_expires_at IS NOT NULL
                 AND token_expires_at <= DATE_ADD(NOW(), INTERVAL ? DAY)""",
            (within_days,),
        )
        return cursor.fetchall()


def get_by_instagram_id(instagram_id: str):
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM instagram_accounts "
            "WHERE instagram_id = ? ORDER BY connected_at DESC LIMIT 1",
            (instagram_id,),
        )
        return cursor.fetchone()


def get_first():
    with get_db() as conn:
        cursor = conn.execute("SELECT * FROM instagram_accounts LIMIT 1")
        return cursor.fetchone()

"""
core/db.py
Database initialisation (CREATE TABLE IF NOT EXISTS) plus re-exports of the
low-level connection helpers so the rest of the app only needs to import from
one place.

DDL is identical to what was previously inline in main.py.
"""

from database.mysql import get_db, get_connection  # re-export

__all__ = ["get_db", "get_connection", "init_db"]

_TABLES = [
    """CREATE TABLE IF NOT EXISTS users (
        id               VARCHAR(36)  PRIMARY KEY,
        email            VARCHAR(255) UNIQUE NOT NULL,
        password_hash    VARCHAR(64)  NOT NULL,
        name             VARCHAR(255) NOT NULL,
        subscription_plan VARCHAR(50) DEFAULT 'free',
        created_at       VARCHAR(50)  NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    """CREATE TABLE IF NOT EXISTS sessions (
        token      VARCHAR(128) PRIMARY KEY,
        user_id    VARCHAR(36)  NOT NULL,
        created_at VARCHAR(50)  NOT NULL,
        expires_at VARCHAR(50)  NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    """CREATE TABLE IF NOT EXISTS instagram_accounts (
        id               VARCHAR(36)  PRIMARY KEY,
        user_id          VARCHAR(36)  NOT NULL,
        instagram_id     VARCHAR(50)  NOT NULL,
        access_token     TEXT         NOT NULL,
        username         VARCHAR(100) NOT NULL,
        account_type     VARCHAR(30)  DEFAULT NULL,
        token_scopes     VARCHAR(255) DEFAULT NULL,
        token_expires_at VARCHAR(50)  DEFAULT NULL,
        connected_at     VARCHAR(50)  NOT NULL,
        status               VARCHAR(20)  DEFAULT 'active',
        facebook_page_id     VARCHAR(50)  DEFAULT NULL,
        page_access_token    TEXT         DEFAULT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    """CREATE TABLE IF NOT EXISTS bot_flows (
        id         VARCHAR(36)  PRIMARY KEY,
        user_id    VARCHAR(36)  NOT NULL,
        name       VARCHAR(255) NOT NULL,
        triggers   LONGTEXT     NOT NULL,
        steps      LONGTEXT     NOT NULL,
        reply_type VARCHAR(20)  DEFAULT 'dm',
        conditions LONGTEXT,
        enabled    TINYINT(1)   DEFAULT 1,
        stats      LONGTEXT,
        created_at VARCHAR(50)  NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    """CREATE TABLE IF NOT EXISTS message_templates (
        id            VARCHAR(36)  PRIMARY KEY,
        user_id       VARCHAR(36)  NOT NULL,
        name          VARCHAR(255) NOT NULL,
        content       TEXT         NOT NULL,
        type          VARCHAR(50)  DEFAULT 'text',
        quick_replies LONGTEXT,
        created_at    VARCHAR(50)  NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    """CREATE TABLE IF NOT EXISTS broadcasts (
        id            VARCHAR(36)  PRIMARY KEY,
        user_id       VARCHAR(36)  NOT NULL,
        name          VARCHAR(255) NOT NULL,
        content       TEXT         NOT NULL,
        target_tags   LONGTEXT,
        schedule_time VARCHAR(50),
        status        VARCHAR(20)  DEFAULT 'draft',
        sent_count    INT          DEFAULT 0,
        created_at    VARCHAR(50)  NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    """CREATE TABLE IF NOT EXISTS conversations (
        id                   VARCHAR(255) PRIMARY KEY,
        user_id              VARCHAR(36)  NOT NULL,
        instagram_account_id VARCHAR(255) NOT NULL,
        sender_id            VARCHAR(100) NOT NULL,
        messages             LONGTEXT     NOT NULL,
        last_activity        VARCHAR(50)  NOT NULL,
        is_test              TINYINT(1)   DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    """CREATE TABLE IF NOT EXISTS analytics (
        id                INT AUTO_INCREMENT PRIMARY KEY,
        user_id           VARCHAR(36) NOT NULL,
        date              VARCHAR(20) NOT NULL,
        messages_sent     INT DEFAULT 0,
        messages_received INT DEFAULT 0,
        comments_replied  INT DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE KEY uq_user_date (user_id, date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    """CREATE TABLE IF NOT EXISTS processed_webhooks (
        id         VARCHAR(64) PRIMARY KEY,
        created_at TIMESTAMP   DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    """CREATE TABLE IF NOT EXISTS oauth_states (
        state      VARCHAR(64)  PRIMARY KEY,
        user_id    VARCHAR(36)  NOT NULL,
        created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]


def init_db() -> None:
    with get_db() as conn:
        for ddl in _TABLES:
            conn.execute(ddl)

        # Idempotent column migrations — errors mean the column already exists.
        _safe_alter(conn, "ALTER TABLE sessions ADD COLUMN expires_at VARCHAR(50) NULL")
        _safe_alter(conn, "ALTER TABLE instagram_accounts ADD COLUMN account_type VARCHAR(30) DEFAULT NULL")
        _safe_alter(conn, "ALTER TABLE instagram_accounts ADD COLUMN token_scopes VARCHAR(255) DEFAULT NULL")
        _safe_alter(conn, "ALTER TABLE instagram_accounts ADD COLUMN token_expires_at VARCHAR(50) DEFAULT NULL")
        _safe_alter(conn, "ALTER TABLE instagram_accounts ADD COLUMN facebook_page_id VARCHAR(50) DEFAULT NULL")
        _safe_alter(conn, "ALTER TABLE instagram_accounts ADD COLUMN page_access_token TEXT DEFAULT NULL")

        conn.commit()
    print("Database initialized")


def _safe_alter(conn, ddl: str) -> None:
    try:
        conn.execute(ddl)
    except Exception:
        pass  # column already exists on existing deployments

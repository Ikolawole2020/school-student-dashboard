# config.py
import os
import secrets


def _resolve_secret_key():
    """Return the session signing key.

    Order of preference:
      1. the SECRET_KEY environment variable (required in production);
      2. instance/secret_key.txt, generated once on first local run;
      3. a freshly generated in-memory key, so a fresh clone still starts.

    The old code fell back to the literal string 'starlight-dev-secret', which
    is public knowledge and would let anyone forge a session cookie. A
    generated key stored outside version control is safe for local work while
    production still gets a hard error if it was not configured properly.
    """
    from_env = os.environ.get('SECRET_KEY')
    if from_env:
        return from_env

    if os.environ.get('FLASK_ENV') == 'production':
        raise RuntimeError(
            'SECRET_KEY must be set in production. Generate one with:\n'
            '  python -c "import secrets; print(secrets.token_hex(32))"'
        )

    here = os.path.dirname(__file__)
    key_file = os.path.join(here, 'instance', 'secret_key.txt')
    try:
        if os.path.isfile(key_file):
            with open(key_file) as fh:
                existing = fh.read().strip()
                if existing:
                    return existing
        os.makedirs(os.path.dirname(key_file), exist_ok=True)
        generated = secrets.token_hex(32)
        with open(key_file, 'w') as fh:
            fh.write(generated)
        return generated
    except OSError:
        # read-only filesystem (some deploy targets) - still start up
        return secrets.token_hex(32)


class Config:
    SECRET_KEY = _resolve_secret_key()

    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///starlight.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
    MAX_CONTENT_LENGTH = 4 * 1024 * 1024  # 4MB
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.environ.get('FLASK_ENV') == 'production'
    REMEMBER_COOKIE_HTTPONLY = True
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8  # 8 hours


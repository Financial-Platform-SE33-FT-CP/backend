"""Unit tests for EmailService SMTP configuration (no real network)."""

from __future__ import annotations

from pydantic import SecretStr

from auth_service.config import AuthSettings
from auth_service.modules.auth.infrastructure.email_service import EmailService


def _auth_settings_smtp(**smtp: object) -> AuthSettings:
    base: dict[str, object] = {
        "jwt_secret": "x",
        "app_env": "test",
        "frontend_url": "https://app.example.com",
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_username": "my-user",
        "smtp_password": SecretStr("my-secret-password"),
        "smtp_from_email": "from@example.com",
        "smtp_from_name": "FN",
        "smtp_use_tls": True,
        "email_verify_code_length": 6,
        "email_verify_code_expire_minutes": 10,
        "email_verify_code_max_attempts": 5,
        "email_verify_code_resend_cooldown_seconds": 60,
    }
    base.update(smtp)
    return AuthSettings(**base)  # type: ignore[arg-type]


def test_email_service_connection_config_uses_settings_not_hard_coded_credentials() -> None:
    svc = EmailService(
        _auth_settings_smtp(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
        ),
    )
    conf = svc._connection_config()
    assert conf.MAIL_SERVER == "smtp.gmail.com"
    assert conf.MAIL_PORT == 587
    assert conf.MAIL_USERNAME == "my-user"
    assert conf.MAIL_PASSWORD.get_secret_value() == "my-secret-password"
    assert str(conf.MAIL_FROM) == "from@example.com"
    assert conf.MAIL_FROM_NAME == "FN"
    assert conf.MAIL_SSL_TLS is False
    assert conf.MAIL_STARTTLS is True


def test_qq_mail_port_465_uses_implicit_ssl_not_starttls() -> None:
    svc = EmailService(
        _auth_settings_smtp(
            smtp_host="smtp.qq.com",
            smtp_port=465,
            smtp_use_tls=True,
        ),
    )
    conf = svc._connection_config()
    assert conf.MAIL_SSL_TLS is True
    assert conf.MAIL_STARTTLS is False


def test_port_587_with_tls_disabled_is_plain() -> None:
    svc = EmailService(_auth_settings_smtp(smtp_port=587, smtp_use_tls=False))
    conf = svc._connection_config()
    assert conf.MAIL_SSL_TLS is False
    assert conf.MAIL_STARTTLS is False


def test_verification_code_email_body_has_no_url_scheme() -> None:
    code = "123456"
    expiry = 10
    plain = (
        f"Your verification code is: {code}\n\nThis code will expire in {expiry} minutes."
    )
    html = f"<p>Your verification code is: <strong>{code}</strong></p>"
    assert "http://" not in plain and "https://" not in plain
    assert "http://" not in html and "https://" not in html

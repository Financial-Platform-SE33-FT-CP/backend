"""Send transactional email via fastapi-mail."""

from __future__ import annotations

from fastapi_mail import (
    ConnectionConfig,
    FastMail,
    MessageSchema,
    MessageType,
    MultipartSubtypeEnum,
)

from auth_service.config import AuthSettings

# SMTP port for SMTPS (implicit TLS from connect). STARTTLS is incorrect here.
_SMTP_PORT_IMPLICIT_TLS = 465


def _smtp_mail_ssl_and_starttls(port: int, smtp_use_tls: bool) -> tuple[bool, bool]:
    """Map host/port/TLS preference to fastapi-mail / aiosmtplib flags."""
    if port == _SMTP_PORT_IMPLICIT_TLS:
        return True, False
    return False, smtp_use_tls


class EmailService:
    """Internal SMTP email sender for auth flows."""

    def __init__(self, settings: AuthSettings) -> None:
        self._settings = settings

    def _connection_config(self) -> ConnectionConfig:
        s = self._settings
        mail_ssl_tls, mail_starttls = _smtp_mail_ssl_and_starttls(s.smtp_port, s.smtp_use_tls)
        return ConnectionConfig(
            MAIL_USERNAME=s.smtp_username,
            MAIL_PASSWORD=s.smtp_password,
            MAIL_PORT=s.smtp_port,
            MAIL_SERVER=s.smtp_host,
            MAIL_STARTTLS=mail_starttls,
            MAIL_SSL_TLS=mail_ssl_tls,
            MAIL_FROM=s.smtp_from_email,
            MAIL_FROM_NAME=s.smtp_from_name or None,
            USE_CREDENTIALS=True,
            VALIDATE_CERTS=True,
        )

    async def send_verification_code_email(
        self,
        to_email: str,
        code: str,
        expiry_minutes: int,
    ) -> None:
        """Send a numeric verification code (no links)."""
        subject = "Verify your email address"
        plain = (
            f"Your verification code is: {code}\n\n"
            f"This code will expire in {expiry_minutes} minutes."
        )
        html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Verify email</title></head>
<body style="font-family: system-ui, sans-serif; line-height: 1.5; color: #0f172a;">
<p>Your verification code is: <strong style="font-size: 1.25rem; letter-spacing: 0.2em;">{code}</strong></p>
<p style="color: #64748b; font-size: 14px;">This code will expire in {expiry_minutes} minutes.</p>
</body></html>"""

        message = MessageSchema(
            subject=subject,
            recipients=[to_email],
            body=html,
            alternative_body=plain,
            subtype=MessageType.html,
            multipart_subtype=MultipartSubtypeEnum.alternative,
        )

        fast_mail = FastMail(self._connection_config())
        await fast_mail.send_message(message)

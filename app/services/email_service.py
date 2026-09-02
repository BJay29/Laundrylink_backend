import os
import random
import smtplib
import socket
import logging
from contextlib import contextmanager
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger("email_verification")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s"))
    logger.addHandler(_handler)

GMAIL_SENDER_EMAIL = os.getenv("GMAIL_SENDER_EMAIL")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587


def generate_verification_code() -> str:
    """Generates a random 6-digit verification code."""
    return str(random.randint(100000, 999999))


# ---------------------------------------------------------------------------
# THE ACTUAL FIX
# ---------------------------------------------------------------------------
# Dating bug: `_connect_smtp()` ay dumidiretso sa isang resolved IPv4 address
# (`smtplib.SMTP(ipv4_address, ...)`), tapos tinatawag ang `starttls()`. Ang
# problema, ginagamit ni smtplib ang HOST na pinasa sa constructor (ibig
# sabihin, ang raw IP) bilang `server_hostname` sa loob ng TLS handshake.
# Sini-check ni Gmail's cert laban dito — pero valid lang ang Gmail cert
# para sa "smtp.gmail.com" (DNS name), HINDI para sa kahit anong IP. Kaya
# bumabagsak nang tahimik ang TLS verification (nahuhuli lang ng generic
# except block sa itaas, na nagpi-print lang at nag-return ng False).
#
# Ang fix: panatilihin nating "smtp.gmail.com" ang host na ginagamit ng
# smtplib/ssl (para tama ang SNI + cert verification), pero i-override
# lang natin nang pansamantala ang resolution mismo (`socket.getaddrinfo`)
# para IPv4-only ang ibabalik nito — hindi na kailangang baguhin ang host
# string na nakikita ng smtplib/ssl layer.
@contextmanager
def _force_ipv4_dns():
    """
    Pinipilit ang lahat ng socket resolution sa loob ng `with` block na ito
    na IPv4-only, nang hindi binabago ang host string na ginagamit ng
    caller (kaya hindi nasisira ang SSL hostname verification).
    """
    original_getaddrinfo = socket.getaddrinfo

    def ipv4_only_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = ipv4_only_getaddrinfo
    try:
        yield
    finally:
        socket.getaddrinfo = original_getaddrinfo


def _connect_smtp() -> smtplib.SMTP:
    """
    Kumokonekta sa Gmail SMTP gamit ang tunay na hostname (para tama ang
    TLS cert verification), habang pinipilit pa ring IPv4-only ang
    underlying resolution (para hindi mangyari ang Render IPv6-unreachable
    error na dati mong naranasan).
    """
    with _force_ipv4_dns():
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
        server.set_debuglevel(1 if os.getenv("SMTP_DEBUG", "false").lower() == "true" else 0)
        server.ehlo(SMTP_SERVER)
        server.starttls()
        server.ehlo(SMTP_SERVER)
        return server


def send_verification_email(to_email: str, full_name: str, code: str) -> bool:
    """
    Sends a 6-digit verification code to the customer's email via Gmail SMTP.
    Returns True if the email was sent successfully, False otherwise.
    """
    if not GMAIL_SENDER_EMAIL or not GMAIL_APP_PASSWORD:
        logger.error("Missing GMAIL_SENDER_EMAIL or GMAIL_APP_PASSWORD env var.")
        return False

    subject = "Verify your LaundryLink account"
    body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto;">
        <h2 style="color: #12315E;">Welcome to LaundryLink, {full_name}!</h2>
        <p style="color: #66809E;">Use the code below to verify your account:</p>
        <div style="background: #F4F7FB; padding: 20px; border-radius: 12px; text-align: center; margin: 20px 0;">
            <span style="font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #1769E0;">{code}</span>
        </div>
        <p style="color: #66809E; font-size: 13px;">This code will expire in 10 minutes. If you didn't request this, you can safely ignore this email.</p>
    </div>
    """

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = f"LaundryLink <{GMAIL_SENDER_EMAIL}>"
    message["To"] = to_email
    message.attach(MIMEText(body, "html"))

    server = None
    try:
        server = _connect_smtp()
        server.login(GMAIL_SENDER_EMAIL, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_SENDER_EMAIL, to_email, message.as_string())
        logger.info(f"Verification email sent to {to_email[:3]}***")
        return True
    except smtplib.SMTPAuthenticationError as e:
        # Mali ang GMAIL_SENDER_EMAIL/GMAIL_APP_PASSWORD, o hindi pa naka-enable
        # ang 2FA/App Password sa Gmail account na ito.
        logger.error(f"SMTP AUTH FAILURE (code {e.smtp_code}): {e.smtp_error!r}")
        return False
    except Exception as e:
        # Kahit anong ibang error (TLS, timeout, DNS, atbp.) — laging naka-log
        # ang buong exception type + message, kaya laging makikita sa Render
        # logs kung ano talaga ang nangyari.
        logger.exception(f"Failed to send verification email ({type(e).__name__}): {e}")
        return False
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass


def debug_send_email(to_email: str) -> dict:
    """
    TEMPORARY DEBUG: Same as send_verification_email but returns the
    actual exception message instead of just True/False. Gamitin ito
    muna para ma-confirm na maayos na ang fix bago ito tanggalin.
    """
    if not GMAIL_SENDER_EMAIL or not GMAIL_APP_PASSWORD:
        return {"success": False, "error": "Missing GMAIL_SENDER_EMAIL or GMAIL_APP_PASSWORD"}

    message = MIMEMultipart("alternative")
    message["Subject"] = "LaundryLink Debug Test"
    message["From"] = f"LaundryLink <{GMAIL_SENDER_EMAIL}>"
    message["To"] = to_email
    message.attach(MIMEText("<p>This is a debug test email.</p>", "html"))

    server = None
    try:
        server = _connect_smtp()
        server.login(GMAIL_SENDER_EMAIL, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_SENDER_EMAIL, to_email, message.as_string())
        return {"success": True, "error": None}
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {str(e)}"}
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass
"""SMTP email delivery for watcher digests and instant fruit alerts."""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from pydantic import BaseModel

from blox_trade_finder.models import Match
from blox_trade_finder.ui.table import format_age, format_value

logger = logging.getLogger(__name__)


class EmailConfig(BaseModel):
    # "smtp"       — classic SMTP (needs username/password)
    # "formsubmit" — free formsubmit.co relay: no account, no password; the
    #                recipient just clicks the one-time activation link that
    #                FormSubmit emails them on first use.
    provider: str = "smtp"
    smtp_host: str = ""
    smtp_port: int = 587
    username: str = ""
    password: str = ""
    from_addr: str | None = None  # defaults to username
    to_addrs: list[str]
    use_tls: bool = True

    @property
    def sender(self) -> str:
        return self.from_addr or self.username


def _send_via_formsubmit(config: EmailConfig, subject: str, text_body: str) -> None:
    import httpx

    for to_addr in config.to_addrs:
        resp = httpx.post(
            f"https://formsubmit.co/ajax/{to_addr}",
            json={"_subject": subject, "message": text_body},
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                # FormSubmit's AJAX endpoint requires a web-ish origin.
                "Referer": "https://github.com/Palakkaalakak/pacte",
                "Origin": "https://github.com",
            },
            timeout=30,
        )
        data = resp.json()
        if str(data.get("success")).lower() != "true":
            raise RuntimeError(f"FormSubmit send to {to_addr} failed: {data}")
    logger.info("formsubmit: sent %r to %s", subject, config.to_addrs)


def send_email(config: EmailConfig, subject: str, text_body: str, html_body: str | None = None) -> None:
    if config.provider == "formsubmit":
        _send_via_formsubmit(config, subject, text_body)
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.sender
    msg["To"] = ", ".join(config.to_addrs)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))

    if config.smtp_port == 465:
        # Implicit TLS (e.g. Gmail's SSL port).
        with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=30) as server:
            server.login(config.username, config.password)
            server.sendmail(config.sender, config.to_addrs, msg.as_string())
    else:
        with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30) as server:
            if config.use_tls:
                server.starttls()
            server.login(config.username, config.password)
            server.sendmail(config.sender, config.to_addrs, msg.as_string())
    logger.info("sent email %r to %s", subject, config.to_addrs)


def _row(m: Match) -> dict[str, str]:
    # From the *user's* perspective: they give what the listing wants,
    # and get what the listing gives.
    return {
        "source": m.listing.source,
        "give": ", ".join(i.name for i in m.listing.want),
        "get": ", ".join(i.name for i in m.listing.give),
        "profit": format_value(m.delta),
        "profit_pct": f"{m.profit_pct:+.0%}",
        "verdict": m.verdict.upper(),
        "confidence": f"{m.confidence}%",
        "posted": format_age(m.listing.created_at),
        "url": m.listing.url,
    }


def matches_to_text(matches: list[Match], heading: str) -> str:
    lines = [heading, ""]
    for i, m in enumerate(matches, 1):
        r = _row(m)
        lines.append(
            f"{i}. [{r['source']}] Give: {r['give']} -> Get: {r['get']} | "
            f"Profit {r['profit']} ({r['profit_pct']}) | {r['verdict']} | "
            f"trust {r['confidence']} | posted {r['posted']}"
        )
        lines.append(f"   {r['url']}")
    return "\n".join(lines)


def matches_to_html(matches: list[Match], heading: str) -> str:
    rows_html = []
    for m in matches:
        r = _row(m)
        rows_html.append(
            "<tr>"
            f"<td>{r['source']}</td><td>{r['give']}</td><td>{r['get']}</td>"
            f"<td>{r['profit']} ({r['profit_pct']})</td><td>{r['verdict']}</td>"
            f"<td>{r['confidence']}</td><td>{r['posted']}</td>"
            f"<td><a href=\"{r['url']}\">open</a></td>"
            "</tr>"
        )
    return (
        f"<h2>{heading}</h2>"
        "<table border=\"1\" cellpadding=\"6\" cellspacing=\"0\" "
        "style=\"border-collapse:collapse;font-family:sans-serif;font-size:14px\">"
        "<tr><th>Source</th><th>You Give</th><th>You Get</th><th>Profit</th>"
        "<th>Verdict</th><th>Trust</th><th>Posted</th><th>Link</th></tr>"
        + "".join(rows_html)
        + "</table>"
    )

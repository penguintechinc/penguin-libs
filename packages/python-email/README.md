# penguin-email

Pluggable email sending library for Penguin Tech applications.

## Features

- **Gmail REST API** transport (OAuth2, primary)
- **SMTP** transport (SSL / STARTTLS / PLAIN with `InsecureConnectionWarning`)
- Fluent `EmailMessage` builder with Jinja2 templating
- Built-in templates: welcome, notification, transactional, alert, password_reset, form
- Form builder and table builder helpers
- Full attachment support (files, bytes, inline images)
- Formal `EmailTransport` Protocol — add new transports with zero core changes

## Installation

```bash
pip install penguin-email            # SMTP + templates only
pip install "penguin-email[gmail]"   # adds Gmail REST API support
```

## Quick Start

```python
from penguin_email import EmailClient, EmailMessage, SmtpTransport, SmtpMode

transport = SmtpTransport(host="smtp.example.com", mode=SmtpMode.STARTTLS,
                          username="user", password="pass")
client = EmailClient(transport)

result = client.send(
    EmailMessage()
    .from_addr("sender@example.com")
    .to("recipient@example.com")
    .subject("Hello!")
    .template("welcome", name="Alice", app_name="MyApp", login_url="https://app.example.com/login")
)
print(result.success, result.message_id)
```

## Gmail Transport

```python
from penguin_email import EmailClient, EmailMessage, GmailTransport

transport = GmailTransport.from_env()   # reads GMAIL_* env vars
client = EmailClient(transport)
```

## License

AGPL-3.0 — see LICENSE.md

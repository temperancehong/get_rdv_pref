# RDV Préfecture Slot Monitor

Monitors the three Palaiseau `remise de titre` RDV Préfecture guichets and emails
you when new appointment slots are detected.

This tool does not bypass or solve CAPTCHA/security-code challenges. When the
security-code page appears, the browser stays visible and the script waits for
you to solve it manually.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

Edit `.env` and set your Gmail address plus a Gmail App Password:

```env
SMTP_USER=your_gmail@gmail.com
SMTP_APP_PASSWORD=your_16_character_app_password
ALERT_TO=recipient@example.com
```

For Gmail, create an App Password from your Google Account security settings.
Do not use your normal Gmail password.

## Run

Check once:

```bash
python rdv_monitor.py --once
```

Run continuously every 30 minutes:

```bash
python rdv_monitor.py
```

Test email rendering without sending:

```bash
python rdv_monitor.py --once --dry-run-email
```

## How It Works

- Opens a visible Chromium browser with a persistent profile in
  `.playwright-profile`.
- Checks these Palaiseau démarches:
  - `2246`
  - `2282`
  - `2283`
- Navigates toward the `creneau` page.
- If a security code appears, waits for you to solve it in the browser.
- Extracts visible appointment labels containing times.
- Sends one email for newly detected slots.
- Saves alerted slot IDs in `seen_slots.json` to avoid duplicate emails.

## Notes

- Keep the browser visible because the security-code step requires manual input.
- The script checks availability only. It does not book, confirm, or cancel an
  appointment.
- If the prefecture site changes its wording or markup, the slot parser may need
  a small update.

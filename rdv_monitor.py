#!/usr/bin/env python3
"""Monitor RDV Prefecture appointment slots and send email alerts.

This script intentionally does not solve or bypass CAPTCHA/security-code
challenges. When the security-code page appears, it keeps the visible browser
open and waits for a human to complete it.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import smtplib
import sys
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page
else:
    BrowserContext = Any
    Page = Any


BASE_URL = "https://www.rdv-prefecture.interieur.gouv.fr"

DEMARCHES = [
    {
        "id": "2246",
        "name": "Remise de titre - Palaiseau - Hall A - Guichet 12",
    },
    {
        "id": "2282",
        "name": "Remise de titre - Palaiseau - Guichet 13",
    },
    {
        "id": "2283",
        "name": "Remise de titre - Palaiseau - Guichet 14",
    },
]

NO_SLOT_PATTERNS = [
    re.compile(r"aucun\s+cr[ée]neau", re.IGNORECASE),
    re.compile(r"pas\s+de\s+cr[ée]neau", re.IGNORECASE),
    re.compile(r"plus\s+de\s+plage\s+horaire\s+libre", re.IGNORECASE),
    re.compile(r"aucune\s+plage\s+horaire", re.IGNORECASE),
    re.compile(r"no\s+appointment", re.IGNORECASE),
]

TIME_PATTERN = re.compile(r"\b(?:[01]?\d|2[0-3])[:h][0-5]\d\b")
DATEISH_PATTERN = re.compile(
    r"\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|"
    r"janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|"
    r"septembre|octobre|novembre|d[ée]cembre|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Slot:
    demarche_id: str
    demarche_name: str
    label: str
    page_url: str

    @property
    def key(self) -> str:
        raw = f"{self.demarche_id}|{self.label}|{self.page_url}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def demarche_url(demarche_id: str) -> str:
    return f"{BASE_URL}/rdvpref/reservation/demarche/{demarche_id}/"


def creneau_url(demarche_id: str) -> str:
    return f"{BASE_URL}/rdvpref/reservation/demarche/{demarche_id}/creneau/"


def load_seen(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        backup = path.with_suffix(f"{path.suffix}.broken")
        path.replace(backup)
        print(f"Warning: invalid seen-slot file moved to {backup}", file=sys.stderr)
        return set()
    if not isinstance(data, list):
        return set()
    return {str(item) for item in data}


def save_seen(path: Path, seen: Iterable[str]) -> None:
    path.write_text(
        json.dumps(sorted(set(seen)), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def page_says_no_slots(text: str) -> bool:
    return any(pattern.search(text) for pattern in NO_SLOT_PATTERNS)


def normalize_slot_label(label: str) -> str:
    return re.sub(r"\s+", " ", label).strip(" -\n\t")


def extract_slot_labels_from_text(text: str) -> list[str]:
    """Best-effort parser for visible appointment labels.

    The live site can change markup, so browser extraction also inspects
    buttons/labels/radio controls. This text parser is intentionally generic
    and used as a fallback plus for unit tests.
    """
    if page_says_no_slots(text):
        return []

    labels: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = normalize_slot_label(raw_line)
        if not line or not TIME_PATTERN.search(line):
            continue

        # Prefer lines that carry either a date or enough appointment context.
        has_date = DATEISH_PATTERN.search(line) is not None
        has_context = re.search(r"cr[ée]neau|rendez-vous|choisir|disponible", line, re.I)
        if not has_date and not has_context and len(line) > 20:
            continue

        if line not in seen:
            seen.add(line)
            labels.append(line)
    return labels


async def has_security_code_challenge(page: Page) -> bool:
    text = await safe_inner_text(page)
    if re.search(r"code\s+de\s+s[ée]curit[ée]|recopier\s+le\s+code", text, re.I):
        return True

    captcha_controls = page.locator(
        "input[name*='captcha' i], input[id*='captcha' i], "
        "img[src*='captcha' i], audio[src*='captcha' i]"
    )
    return await captcha_controls.count() > 0


async def safe_inner_text(page: Page) -> str:
    try:
        return await page.locator("body").inner_text(timeout=5_000)
    except Exception:
        return ""


async def click_first_visible(page: Page, selectors_or_names: list[str]) -> bool:
    for item in selectors_or_names:
        if item.startswith("text="):
            locator = page.get_by_text(item.removeprefix("text="), exact=False)
        else:
            locator = page.locator(item)

        count = await locator.count()
        for index in range(count):
            candidate = locator.nth(index)
            try:
                if await candidate.is_visible(timeout=500):
                    await candidate.click(timeout=2_000)
                    await page.wait_for_load_state("networkidle", timeout=10_000)
                    return True
            except Exception:
                continue
    return False


async def accept_cgu_if_present(page: Page) -> bool:
    checked_any = False
    checkboxes = page.locator("input[type='checkbox']")
    for index in range(await checkboxes.count()):
        box = checkboxes.nth(index)
        try:
            if await box.is_visible(timeout=500) and not await box.is_checked():
                await box.check(timeout=2_000)
                checked_any = True
        except Exception:
            continue

    if checked_any:
        return await click_first_visible(
            page,
            [
                "button:has-text('Suivant')",
                "input[type='submit']",
                "text=Suivant",
                "button:has-text('Valider')",
            ],
        )
    return False


async def wait_for_manual_security_code(page: Page, timeout_seconds: int) -> None:
    print("")
    print("Security code detected.")
    print("Please solve it in the visible browser and click Suivant.")
    print(f"The script will wait up to {timeout_seconds // 60} minutes.")

    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        if "/creneau" in page.url and not await has_security_code_challenge(page):
            await page.wait_for_load_state("networkidle", timeout=10_000)
            return
        if not await has_security_code_challenge(page):
            return
        await asyncio.sleep(2)
    raise TimeoutError("Timed out waiting for manual security-code completion.")


async def navigate_to_slots(page: Page, demarche: dict[str, str], manual_timeout: int) -> None:
    did = demarche["id"]
    await page.goto(demarche_url(did), wait_until="networkidle")

    for _ in range(8):
        if "/creneau" in page.url:
            return

        if await has_security_code_challenge(page):
            await wait_for_manual_security_code(page, manual_timeout)
            if "/creneau" in page.url:
                return

        advanced = await click_first_visible(
            page,
            [
                "button:has-text('Prendre un rendez-vous')",
                "a:has-text('Prendre un rendez-vous')",
                "text=Prendre un rendez-vous",
            ],
        )
        if advanced:
            continue

        if await accept_cgu_if_present(page):
            continue

        advanced = await click_first_visible(
            page,
            [
                "button:has-text('Suivant')",
                "a:has-text('Suivant')",
                "input[type='submit']",
                "text=Suivant",
            ],
        )
        if advanced:
            continue

        # If the session is already valid, the direct creneau URL may work.
        await page.goto(creneau_url(did), wait_until="networkidle")

    raise RuntimeError(f"Could not reach the creneau page for demarche {did}.")


async def extract_slots_from_page(page: Page, demarche: dict[str, str]) -> list[Slot]:
    text = await safe_inner_text(page)
    if page_says_no_slots(text):
        return []

    labels: list[str] = []
    seen_labels: set[str] = set()

    control_texts = await page.locator(
        "button, a, label, [role='button'], [role='radio'], td, li"
    ).evaluate_all(
        """nodes => nodes
            .map(node => (node.innerText || node.textContent || '').trim())
            .filter(Boolean)
        """
    )

    for raw in [*control_texts, *extract_slot_labels_from_text(text)]:
        label = normalize_slot_label(str(raw))
        if not label or label in seen_labels:
            continue
        if TIME_PATTERN.search(label) and not re.search(r"pr[ée]c[ée]dent|suivant", label, re.I):
            seen_labels.add(label)
            labels.append(label)

    return [
        Slot(
            demarche_id=demarche["id"],
            demarche_name=demarche["name"],
            label=label,
            page_url=page.url,
        )
        for label in labels
    ]


async def check_demarche(
    context: BrowserContext,
    demarche: dict[str, str],
    manual_timeout: int,
) -> list[Slot]:
    page = await context.new_page()
    try:
        print(f"Checking {demarche['name']} ({demarche['id']})...")
        await navigate_to_slots(page, demarche, manual_timeout)
        slots = await extract_slots_from_page(page, demarche)
        print(f"Found {len(slots)} slot candidate(s) for {demarche['id']}.")
        return slots
    finally:
        await page.close()


def build_email(slots: list[Slot], recipient: str) -> EmailMessage:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = EmailMessage()
    message["Subject"] = f"RDV Prefecture: {len(slots)} new slot(s) found"
    message["From"] = os.environ["SMTP_USER"]
    message["To"] = recipient

    lines = [
        f"New RDV Prefecture slot(s) detected at {now}.",
        "",
    ]
    for slot in slots:
        lines.extend(
            [
                f"- {slot.demarche_name}",
                f"  Slot: {slot.label}",
                f"  Page: {slot.page_url}",
                "",
            ]
        )
    message.set_content("\n".join(lines))
    return message


def send_email(slots: list[Slot], dry_run: bool = False) -> None:
    if not slots:
        return

    recipient = os.getenv("ALERT_TO", "recipient@example.com")
    required = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_APP_PASSWORD"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Missing email environment variable(s): {', '.join(missing)}")

    message = build_email(slots, recipient)
    if dry_run:
        print("Dry-run email:")
        print(message)
        return

    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ["SMTP_PORT"])) as smtp:
        smtp.starttls()
        smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_APP_PASSWORD"])
        smtp.send_message(message)


async def run_once(args: argparse.Namespace) -> list[Slot]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Run: pip install -r requirements.txt"
        ) from exc

    profile_dir = Path(args.profile_dir).expanduser()
    profile_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=args.headless,
            viewport={"width": 1280, "height": 900},
            locale="fr-FR",
        )
        try:
            all_slots: list[Slot] = []
            for demarche in DEMARCHES:
                try:
                    all_slots.extend(await check_demarche(context, demarche, args.manual_timeout))
                except Exception as exc:
                    print(f"Error while checking {demarche['id']}: {exc}", file=sys.stderr)
            return all_slots
        finally:
            await context.close()


async def monitor(args: argparse.Namespace) -> None:
    seen_path = Path(args.seen_file)
    seen = load_seen(seen_path)

    while True:
        slots = await run_once(args)
        new_slots = [slot for slot in slots if slot.key not in seen]

        if new_slots:
            print(f"Sending alert for {len(new_slots)} new slot(s).")
            send_email(new_slots, dry_run=args.dry_run_email)
            seen.update(slot.key for slot in new_slots)
            save_seen(seen_path, seen)
        else:
            print("No new slots found.")

        if args.once:
            return

        sleep_seconds = args.poll_minutes * 60
        print(f"Sleeping for {args.poll_minutes} minute(s).")
        await asyncio.sleep(sleep_seconds)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor RDV Prefecture appointment slots.")
    parser.add_argument("--once", action="store_true", help="Check once and exit.")
    parser.add_argument(
        "--poll-minutes",
        type=int,
        default=int(os.getenv("POLL_MINUTES", "30")),
        help="Minutes between checks. Default: 30.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser headless. Do not use this when CAPTCHA may be required.",
    )
    parser.add_argument(
        "--profile-dir",
        default=os.getenv("PROFILE_DIR", ".playwright-profile"),
        help="Persistent browser profile directory.",
    )
    parser.add_argument(
        "--seen-file",
        default=os.getenv("SEEN_SLOTS_FILE", "seen_slots.json"),
        help="JSON file used to suppress duplicate alerts.",
    )
    parser.add_argument(
        "--manual-timeout",
        type=int,
        default=int(os.getenv("MANUAL_CAPTCHA_TIMEOUT_SECONDS", "900")),
        help="Seconds to wait for manual security-code completion. Default: 900.",
    )
    parser.add_argument(
        "--dry-run-email",
        action="store_true",
        help="Print the alert email instead of sending it.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        from dotenv import load_dotenv
    except ImportError:
        print("Warning: python-dotenv is not installed; .env will not be loaded.", file=sys.stderr)
    else:
        load_dotenv()

    args = parse_args(argv or sys.argv[1:])
    if args.headless:
        print("Warning: headless mode cannot handle manual CAPTCHA/security-code entry.")
    asyncio.run(monitor(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

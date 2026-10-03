import datetime
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

CONFIG_PATH = Path("/etc/applock/apps.json")
PROFILE_PATH = Path("/etc/apparmor.d/applock-session")
HOSTS_PATH = Path("/etc/hosts")
HOSTS_BEGIN = "# BEGIN App Lock website blocks"
HOSTS_END = "# END App Lock website blocks"
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def parse_time(value):
    if not isinstance(value, str):
        return None
    match = TIME_RE.fullmatch(value.strip())
    if match is None:
        return None
    hour, minute = map(int, match.groups())
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def schedule_is_locked(schedule, now=None):
    if not isinstance(schedule, dict) or schedule.get("always", True):
        return True

    start = parse_time(schedule.get("start"))
    end = parse_time(schedule.get("end"))
    if start is None or end is None:
        return True

    if now is None:
        now = datetime.datetime.now().time()
    minute = now.hour * 60 + now.minute

    if start == end:
        return True
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end


def load_config(path=CONFIG_PATH):
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    apps = data.get("apps", {})
    websites = data.get("websites", {})
    if not isinstance(apps, dict):
        raise ValueError("apps.json is malformed: apps must be an object")
    if not isinstance(websites, dict):
        raise ValueError("apps.json is malformed: websites must be an object")
    return {"apps": apps, "websites": websites}


def load_apps(path=CONFIG_PATH):
    return load_config(path)["apps"]


def active_apps(apps, now=None):
    return {
        name: info
        for name, info in apps.items()
        if schedule_is_locked(info.get("schedule"), now)
    }


def normalize_domain(value):
    if not isinstance(value, str):
        raise ValueError("Website domain must be text")

    text = value.strip().lower()
    if not text:
        raise ValueError("Website domain is empty")
    if "://" not in text:
        text = "http://" + text

    try:
        host = urlparse(text).hostname
    except ValueError as exc:
        raise ValueError(f"Invalid website domain: {value}") from exc

    if not host:
        raise ValueError(f"Invalid website domain: {value}")

    try:
        host = host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError(f"Invalid website domain: {value}") from exc

    if len(host) > 253 or "." not in host:
        raise ValueError(f"Invalid website domain: {value}")
    if not all(DOMAIN_LABEL_RE.fullmatch(label) for label in host.split(".")):
        raise ValueError(f"Invalid website domain: {value}")

    return host


def parse_website(value):
    """Return a canonical website name and the exact hostnames to block."""
    host = normalize_domain(value)
    primary = host[4:] if host.startswith("www.") and "." in host[4:] else host

    domains = [primary]
    if host != primary:
        domains.append(host)
    elif primary.count(".") == 1:
        domains.append("www." + primary)

    return primary, list(dict.fromkeys(domains))


def website_domains(name, info):
    if not isinstance(info, dict):
        raise ValueError(f"Invalid website entry: {name}")

    raw_domains = info.get("domains")
    if raw_domains is None:
        _primary, domains = parse_website(info.get("domain") or name)
        return domains

    if not isinstance(raw_domains, list) or not all(
        isinstance(domain, str) for domain in raw_domains
    ):
        raise ValueError(f"Website {name} has an invalid domains list")

    primary = normalize_domain(info.get("domain") or name)
    domains = [primary]
    domains.extend(normalize_domain(domain) for domain in raw_domains)
    return list(dict.fromkeys(domains))


def active_websites(websites, now=None):
    return {
        name: info
        for name, info in websites.items()
        if schedule_is_locked(info.get("schedule"), now)
    }


def website_block_domains(websites, now=None):
    domains = []
    for _name, info in active_websites(websites, now).items():
        domains.extend(website_domains(_name, info))
    return list(dict.fromkeys(sorted(domains)))


def quote_path(path):
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def flatpak_paths(flatpak_id):
    return [
        f"/var/lib/flatpak/app/{flatpak_id}",
        f"/home/*/.local/share/flatpak/app/{flatpak_id}",
    ]


def generate_profile(apps, now=None):
    active = active_apps(apps, now)

    session_rules = []
    daemon_rules = []
    for info in apps.values():
        path = Path("/usr/bin/flatpak") if info.get("type") == "flatpak" else Path(info["path"])
        real = str(path.resolve(strict=False))
        daemon_rules.append(f"  {quote_path(real)} PUx,")

    for info in active.values():
        if info.get("type") == "flatpak" and info.get("flatpak_id"):
            flatpak_id = info["flatpak_id"]
            for base in flatpak_paths(flatpak_id):
                session_rules.append(f"  deny {quote_path(base)} mrx,")
                session_rules.append(f"  deny {quote_path(base + '/**')} mrx,")
        else:
            path = Path(info["path"])
            real = str(path.resolve(strict=False))
            for deny_path in {str(path), real}:
                session_rules.append(f"  deny {quote_path(deny_path)} mrx,")

    session_rules = sorted(set(session_rules))
    daemon_rules = sorted(set(daemon_rules))

    return f'''abi <abi/4.0>,
include <tunables/global>

profile applock-session /** flags=(attach_disconnected mediate_deleted) {{
  allow all,

  # Apps currently locked by schedule
{chr(10).join(session_rules) if session_rules else "  # No apps are currently scheduled to be locked"}

  # Site-specific additions and overrides.
  include if exists <local/applock-session>
}}

profile applock-daemon /usr/local/bin/applockd flags=(attach_disconnected mediate_deleted) {{
  allow all,

  # Apps the daemon may start after a valid code
{chr(10).join(daemon_rules) if daemon_rules else "  # No apps are currently allowed"}

  include if exists <local/applock-daemon>
}}
'''


def write_profile(apps, now=None):
    profile = generate_profile(apps, now)
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(profile, encoding="utf-8")
    os.chown(PROFILE_PATH, 0, 0)
    os.chmod(PROFILE_PATH, 0o644)
    return profile


def reload_profile():
    subprocess.run(
        ["apparmor_parser", "-r", "-T", "-W", str(PROFILE_PATH)],
        check=True,
    )


def _hosts_without_managed_section(text):
    lines = text.splitlines()
    begin = next((index for index, line in enumerate(lines) if line.strip() == HOSTS_BEGIN), None)
    end = next((index for index, line in enumerate(lines) if line.strip() == HOSTS_END), None)

    if begin is None and end is None:
        return text
    if begin is None or end is None or end < begin:
        raise ValueError("/etc/hosts has an incomplete App Lock website block section")

    return "\n".join(lines[:begin] + lines[end + 1:])


def write_website_blocks(websites, now=None, hosts_path=HOSTS_PATH):
    domains = website_block_domains(websites, now)
    hosts_path = Path(hosts_path)
    original = hosts_path.read_text(encoding="utf-8")
    base = _hosts_without_managed_section(original).rstrip("\n")

    if domains:
        section = [HOSTS_BEGIN, "# Managed by App Lock. Do not edit between these markers."]
        section.extend(f"0.0.0.0 {domain}" for domain in domains)
        section.extend(f":: {domain}" for domain in domains)
        section.append(HOSTS_END)
        new_text = base + "\n\n" + "\n".join(section) + "\n"
    else:
        new_text = base + "\n" if base else ""

    stat_result = hosts_path.stat()
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".applock-hosts-",
        dir=str(hosts_path.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(new_text)
        os.chown(temporary_name, stat_result.st_uid, stat_result.st_gid)
        os.chmod(temporary_name, stat_result.st_mode & 0o777)
        os.replace(temporary_name, hosts_path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise

    return domains


def sync_profile(apps=None, now=None):
    if apps is None:
        apps = load_apps()
    write_profile(apps, now)
    reload_profile()


def flush_dns_cache():
    try:
        subprocess.run(
            ["resolvectl", "flush-caches"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        pass


def sync_website_blocks(websites=None, now=None, hosts_path=HOSTS_PATH):
    if websites is None:
        websites = load_config().get("websites", {})
    domains = write_website_blocks(websites, now, hosts_path)
    flush_dns_cache()
    return domains

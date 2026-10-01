# AppArmor App Lock

A system-level parental-control tool for GNOME. It uses AppArmor to block direct application launches and a privileged daemon to start apps after the correct code is entered. It can also block websites during configurable daily time windows.

## Architecture

- `applockd` runs as root and listens on `/run/applock/applock.sock`.
- `applock-launch APP` asks for the unlock code and sends a request to the daemon.
- The daemon verifies a salted SHA-256 code, then launches the app as the requesting user.
- An AppArmor profile attached to GNOME Shell blocks reading, copying, and directly executing locked app binaries.
- Processes launched from GNOME Shell inherit that profile, so terminal, desktop, and file-manager launches are blocked too.
- `applockd` checks app and website schedules every few seconds.
- Active website blocks are written to a clearly marked, atomically replaced section of `/etc/hosts`.

## Install

```sh
pkexec ./install.sh
applock-admin-gui
```

Use the GUI to:

- set the unlock code
- add or remove apps and websites
- choose **Always locked/blocked** or a daily window
- apply configuration and synchronize AppArmor rules and website blocks

Log out and back in after installing or changing the AppArmor profile. The logout also applies the new `applock` group membership used for the daemon socket.

## Application locking

If the app has a standard desktop launcher, `applock-admin add` creates an override in `/usr/local/share/applications`. When its schedule is active, clicking the normal icon opens the password prompt. Outside the schedule, the app opens normally.

You can also launch a locked app from a terminal:

```sh
applock-launch firefox
```

The helper opens a password prompt and asks the daemon to launch the app as your user. If the app is outside its scheduled lock window, it opens directly without a prompt.

## Website blocking

Add a domain or URL from the GUI's **Websites** tab, or use the CLI:

```sh
pkexec applock-admin add-website example.com
pkexec applock-admin add-website --schedule 19:00 07:00 example.com
pkexec applock-admin set-website-schedule --always example.com
pkexec applock-admin remove-website example.com
pkexec applock-admin list
```

When a website's schedule is active, App Lock maps its configured hostnames to `0.0.0.0` and `::` in `/etc/hosts`. App Lock manages only the section between its `BEGIN` and `END` markers and leaves the rest of `/etc/hosts` unchanged. It also asks `systemd-resolved` to flush its DNS cache when possible.

Entering `example.com` blocks `example.com` and `www.example.com`. Entering `old.example.com` blocks that exact hostname. Website blocks are system-wide for applications using the system resolver.

A block window may cross midnight. For example, `19:00` to `07:00` blocks from 7 PM until 7 AM.

## Security notes

- AppArmor denial rules use `mrx`, so locked binaries cannot be read, mapped, or executed directly from GNOME Shell or its child processes.
- The unlock code is stored as a salted SHA-256 hash in root-only `/etc/applock/code`.
- The daemon only launches paths listed in root-owned `/etc/applock/apps.json`.
- Website configuration is stored in the same root-owned file and applied by the root daemon.
- A user with root privileges can still disable the lock; this is a parental-control tool, not a defense against an administrator.
- Website blocking is DNS-level. It can be bypassed by VPNs, DNS-over-HTTPS, proxies, direct IP addresses, or an alternate resolver.
- Flatpak apps need their launcher command locked or a Flatpak-specific policy because they are usually started through `/usr/bin/flatpak`.
- The AppArmor profile confines GNOME Shell and its descendants. A separate login-shell profile would be needed to also cover SSH or TTY sessions.
- Existing network connections may continue after a schedule starts; restart the browser if needed.

## GUI and schedules

Start **AppLockConfig** from GNOME's application menu, or run:

```sh
applock-admin-gui
```

The GUI can:

- add and remove locked applications and blocked websites
- set the unlock code
- choose whether each item is always active
- set daily windows, such as `19:00` to `07:00`
- show whether the selected app or website is active at the current time
- synchronize AppArmor rules and website blocks on demand

The **Applications** and **Websites** tabs use the same 24-hour time-picker controls. Changes are staged until you press **Apply**.

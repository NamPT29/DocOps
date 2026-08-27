# Windows packaging

The release is an application-only package. It does not contain PostgreSQL,
Caddy, cloudflared, `.env`, `host.env`, uploads, templates, exports, or database
files.

## Build machine

Requirements:

- Windows x64 and Python matching the supported application version.
- Project dependencies from `requirements.txt`.
- PyInstaller (`python -m pip install pyinstaller`).
- Inno Setup 6 when an installer is required.

Build the application directory:

```powershell
.\scripts\build_windows_package.ps1
```

Build the application and installer:

```powershell
.\scripts\build_windows_package.ps1 -BuildInstaller
```

Outputs are written to `dist\ScanToExcelApp` and `installer-output`. The build
script fails if it finds a bundled environment file, portable database engine,
Caddy, or cloudflared executable.

## New host machine

Before launching Scan To Excel Host:

1. Install PostgreSQL as a Windows service.
2. Create an empty database (the default wizard value is `scan_data`) and a
   database user that owns or can create objects in that database.
3. Install the generated Scan To Excel Host installer.
4. Start the application and enter the PostgreSQL connection and initial admin
   password in the first-run wizard.

The application creates its schema after the database connection succeeds. It
is available locally at `127.0.0.1:8000` with the default `HOST`/`PORT` values.

Mutable state is kept under:

```text
%LOCALAPPDATA%\ScanToExcelHost\
  config\host.env
  uploads\
  templates\
  source_documents\
  exports\
  logs\
  updates\
```

Uninstalling or upgrading the application does not delete that directory.
Back up `host.env` securely and back up business files separately from the
application binaries.

## Reverse proxy and Cloudflare Tunnel

Caddy and Cloudflare Tunnel are installed and managed separately. The expected
route is:

```text
Cloudflare Tunnel -> Caddy :80 -> ScanToExcel 127.0.0.1:8000
```

The Caddy site label must match the hostname sent by Cloudflare, for example:

```caddyfile
sohoadang.aivn.net.vn {
    reverse_proxy 127.0.0.1:8000
}
```

Configure the Cloudflare Tunnel ingress service to reach
`http://127.0.0.1:80`. Neither the Caddy configuration nor the tunnel token is
part of the application installer.

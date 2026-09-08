# -*- mode: python ; coding: utf-8 -*-

# Application-only package. External services, configuration and mutable
# business data are intentionally outside this build.
from pathlib import Path

from server.release_info import APP_NAME, APP_VERSION


block_cipher = None

version_parts = [int(part) for part in APP_VERSION.split('.')]
version_tuple = tuple((version_parts + [0, 0, 0, 0])[:4])
version_info_path = Path('build/windows-version-info.txt').resolve()
version_info_path.parent.mkdir(parents=True, exist_ok=True)
version_info_path.write_text(
    f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version_tuple},
    prodvers={version_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'Scan To Excel'),
        StringStruct('FileDescription', '{APP_NAME}'),
        StringStruct('FileVersion', '{APP_VERSION}'),
        StringStruct('InternalName', 'ScanToExcelApp'),
        StringStruct('OriginalFilename', 'ScanToExcelApp.exe'),
        StringStruct('ProductName', '{APP_NAME}'),
        StringStruct('ProductVersion', '{APP_VERSION}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)""",
    encoding='utf-8',
)

a = Analysis(
    ['app_launcher.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('frontend', 'frontend'),
        ('Caddyfile', '.'),
        ('alembic.ini', '.'),
        ('migrations', 'migrations'),
    ],
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        # Uvicorn imports this target from the string "server.main:app".
        'server.main',
        'wizard',
        'psycopg',
        'psycopg.pq',
        'alembic',
        'alembic.command',
        'alembic.config',
        'alembic.runtime.migration',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # pandas advertises many optional integrations that are installed on the
    # build workstation but are not used by the local Excel workflow. Excluding
    # them keeps workstation state from inflating the release by gigabytes.
    excludes=[
        'pandas.tests',
        'pytest',
        '_pytest',
        'scipy',
        'torch',
        'torchvision',
        'tensorflow',
        'transformers',
        'fsspec',
        'matplotlib',
        'IPython',
        'notebook',
        'jupyter',
        'sklearn',
        'numba',
        'sympy',
        'pyarrow',
        'win32com',
        'pythoncom',
        'pywintypes',
        'MySQLdb',
        'psycopg2',
        'pysqlite2',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ScanToExcelApp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    version=str(version_info_path),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ScanToExcelApp',
)

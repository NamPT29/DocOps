# -*- mode: python ; coding: utf-8 -*-

# Application-only package. External services, configuration and mutable
# business data are intentionally outside this build.
block_cipher = None

a = Analysis(
    ['app_launcher.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('frontend', 'frontend'),
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

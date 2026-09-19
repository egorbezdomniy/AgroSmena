# A standalone executable is copied outside the install tree before it runs.
a = Analysis(['updater.py'], pathex=[SPECPATH], binaries=[], datas=[], hiddenimports=[],
             excludes=['PySide6', 'sqlalchemy', 'alembic', 'django'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='updater', console=False, upx=False)

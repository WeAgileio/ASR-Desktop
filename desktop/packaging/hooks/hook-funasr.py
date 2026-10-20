from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

# FunASR discovers registrations with pkgutil and several models need source files.
datas = collect_data_files("funasr", include_py_files=True) + copy_metadata("funasr")
hiddenimports = collect_submodules("funasr", on_error="warn once")
module_collection_mode = "pyz+py"

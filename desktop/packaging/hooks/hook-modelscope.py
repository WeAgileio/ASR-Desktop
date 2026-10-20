from PyInstaller.utils.hooks import collect_data_files, copy_metadata

datas = collect_data_files("modelscope", include_py_files=True) + copy_metadata("modelscope")
hiddenimports = ["modelscope.hub.snapshot_download", "modelscope.hub.api", "modelscope.utils.config"]
module_collection_mode = "pyz+py"

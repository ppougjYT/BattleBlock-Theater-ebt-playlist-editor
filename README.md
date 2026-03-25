# EXE Build Folder

This folder only contains the files needed to build the BattleBlock `.ebt` editor `.exe`.

Run these commands from this folder:

```powershell
python -m pip install pyinstaller
python -m PyInstaller --onefile --windowed --add-data "key1;." --add-data "key2;." --add-data "Battle-Block-Theater-Level-Editor-master;Battle-Block-Theater-Level-Editor-master" .\ebt_editor_gui.py
```

After the build finishes, the `.exe` will be in:

```text
.\dist\
```

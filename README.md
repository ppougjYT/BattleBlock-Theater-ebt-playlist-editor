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
<img width="1197" height="758" alt="image" src="https://github.com/user-attachments/assets/abdeeb13-5b6f-465c-b4ea-a306a184e080" />
<img width="1200" height="759" alt="image" src="https://github.com/user-attachments/assets/48377d84-e0e4-4dff-9fbd-e40268f0b916" />


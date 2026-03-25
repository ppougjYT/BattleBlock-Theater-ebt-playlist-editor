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
<img width="1919" height="1029" alt="image" src="https://github.com/user-attachments/assets/859ae390-c4b8-43a0-9d7e-c7f2c1a3aea0" />
<img width="1919" height="1032" alt="image" src="https://github.com/user-attachments/assets/e0b889c1-2ff8-4032-b2c7-98ce3e21fe52" />

# Coursera Full Course Downloader

A GUI for easy downloading of Coursera courses.

Site for downloading the Windows app: https://coursera-downloader.rf.gd/

# Description

Download videos, assignments, notes and all other resources of a course saved week by week just as in the course.
![coursera-downloader-v3 0 0_main_window](https://github.com/user-attachments/assets/d9d558c5-0479-42b5-827d-7a97d6418128)

![image](https://github.com/touhid314/Coursera-Downloader/assets/69526008/6b210f4e-837e-489d-83b9-6c6940cae660)

![image](https://github.com/touhid314/Coursera-Downloader/assets/69526008/13a145e5-3c28-4630-bce0-32267fc3a690)

# Usage Guide
Check the site for updated info: https://coursera-downloader.rf.gd/

## Fork additions (cbao97)

This fork adds a local web GUI and fixes for modern environments:

- **Web GUI** (`webgui.py`, Flask, http://localhost:8765) — paste your CAUTH
  cookie once (modern Chrome/Brave/Edge use App-Bound Encryption, so automatic
  cookie extraction no longer works); download runs in a subprocess with
  live log streaming and a Stop button. No admin rights, no telemetry.
- **Python 3.12+** support (removed `distutils` dependency)
- **`reading` item support** — reading pages (e.g. "Download Module Slides"
  PDFs) are downloaded instead of being skipped

### How to run

```powershell
# 1. Clone this fork and install dependencies (Python 3.10+ required)
git clone git@github.com:cbao97/Coursera-Downloader.git
cd Coursera-Downloader
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 2. Start the web GUI
.venv\Scripts\python.exe webgui.py
# then open http://localhost:8765 in your browser
```

### How to get CAUTH

1. Log in at [coursera.org](https://www.coursera.org) in your browser
2. Press `F12` → **Application** tab → **Cookies** → `https://www.coursera.org`
3. Find the row named `CAUTH`, copy its **Value**, paste it into the web GUI
   (stored locally in `data.bin`, never sent anywhere else)

### Command line (alternative)

```powershell
.venv\Scripts\python.exe start.py <course-slug> -ca "<CAUTH value>" --path <folder> --download-quizzes --download-notebooks
```

Shield: [![CC BY-NC 4.0][cc-by-nc-shield]][cc-by-nc]

This work is licensed under a
[Creative Commons Attribution-NonCommercial 4.0 International License][cc-by-nc].

[![CC BY-NC 4.0][cc-by-nc-image]][cc-by-nc]

[cc-by-nc]: https://creativecommons.org/licenses/by-nc/4.0/
[cc-by-nc-image]: https://licensebuttons.net/l/by-nc/4.0/88x31.png
[cc-by-nc-shield]: https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg

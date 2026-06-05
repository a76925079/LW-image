# T8-电商小红书配图工具

Lightweight Windows-oriented desktop client for a running `chatgpt2api` service.

## Features

- Text-to-image via `POST /v1/images/generations`
- Image-to-image via `POST /v1/images/edits`
- Dark/light workspace themes with the last choice remembered
- Left-side generation controls with prompt, reference image, quality, size, ratio, and count
- Result canvas with image preview actions
- Model loading via `GET /v1/models`
- Local image saving
- SQLite generation history
- Built-in API endpoint and key

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m image_studio.app
```

If running from source without installing the package, set `PYTHONPATH`:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m image_studio.app
```

## Configure

Open Settings and choose the output directory. The API endpoint and key are built in.

## Package

```powershell
pip install pyinstaller
pyinstaller --noconfirm --windowed --name T8ImageTool --icon icon.ico --add-data "icon.ico;." --paths src src\image_studio_launcher.py
```

The executable will be created under `dist\T8ImageTool`.

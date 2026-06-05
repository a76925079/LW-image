# LW Image Tool

LW生图工具是一个画布式生图项目，兼容 OpenAI 风格图片接口。

项目包含两个互不影响的程序：

- `web_app/`：独立 Web 版生图工具，支持对话、素材中心、提示词模板、接口设置和模型获取。
- `src/image_studio/`：Python 桌面版工具，使用 CustomTkinter 构建。

## Web App

```powershell
cd web_app
pip install -r requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 7860
```

打开：

```text
http://127.0.0.1:7860
```

## Desktop App

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH = "$PWD\src"
python -m image_studio.app
```

## Privacy

不要提交本地 API Key。项目已忽略以下本地数据：

- `web_app/data/`
- `.env`
- `.env.*`
- `dist/`
- `build/`


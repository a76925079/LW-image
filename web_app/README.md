# LW Web 生图工具

独立 Web 版程序，不依赖桌面版入口。

## 运行

```powershell
cd web_app
python -m uvicorn backend.main:app --host 127.0.0.1 --port 7860
```

打开：

```text
http://127.0.0.1:7860
```

## 说明

- API 地址和 Key 内置在后端，不暴露给前端 JS。
- 生成图片保存到 `web_app/data/images`。
- 上传参考图保存到 `web_app/data/uploads`。
- 历史记录保存到 `web_app/data/history.sqlite3`。

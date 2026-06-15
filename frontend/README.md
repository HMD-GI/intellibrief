# IntelliBrief 前端

这是独立的 Vue 3 + Vite 前端工程，运行时通过 `VITE_API_BASE_URL` 访问后端 API。

## 启动

```powershell
cd frontend
npm install
npm run dev
```

默认访问地址：

```text
http://127.0.0.1:5173
```

## 配置后端地址

复制 `.env.example` 为 `.env`，按需修改：

```text
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## 后端启动

```powershell
cd ..
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

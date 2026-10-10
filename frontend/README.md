# CHANAKYA Frontend

React/Vite enterprise chat interface for the CHANAKYA backend.

## Run locally

From the repository root:

```powershell
cd frontend
npm install
npm run dev
```

The Vite dev server runs at http://localhost:5173 and proxies CHANAKYA API routes to http://localhost:8000.

## Production build

```powershell
npm run build
npm run preview
```

For a deployed backend, set:

```
VITE_API_URL=https://your-chanakya-backend.example.com
```

## UI direction

- Light precision-instrument visual language
- Single conversation window with automatic department routing
- Magic UI-style pointer spotlight cards and restrained 3D motion
- Responsive CHANAKYA wisdom mascot
- Clickable retrieved-context sources backed by /sources/{chunk_id}
- Reduced-motion support

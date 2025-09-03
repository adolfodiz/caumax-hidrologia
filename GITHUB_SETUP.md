# 🚀 Guía para subir CAUMAX a GitHub

## ✅ Todo ya está preparado:

- ✅ `requirements-web.txt` con todas las dependencias (incluido Stripe)
- ✅ `.gitignore` que excluye carpetas no deseadas
- ✅ Repositorio git inicializado
- ✅ Código listo para deployment

## 📝 Pasos para subir a GitHub:

### 1. Crear repositorio en GitHub
```
1. Ve a github.com
2. Click "New repository" 
3. Nombre: "caumax-hidrologia" (o el que prefieras)
4. Marcar como PRIVADO (importante para tu app comercial)
5. NO marcar "Initialize with README"
6. Click "Create repository"
```

### 2. Conectar repositorio local
```bash
# Desde tu terminal en la carpeta del proyecto:
git remote add origin https://github.com/TU-USUARIO/caumax-hidrologia.git
git branch -M main
```

### 3. Subir archivos
```bash
git add .
git commit -m "Initial commit: CAUMAX Hidrological Analysis Platform"
git push -u origin main
```

### 4. Configurar GitHub Pages (para la landing)
```
1. En tu repositorio GitHub → Settings
2. Pages → Source → Deploy from a branch
3. Branch → main → / (root)
4. Save
```

### 5. Configurar app principal en Streamlit Cloud
```
1. Ve a share.streamlit.io
2. Deploy new app
3. Conecta tu repositorio GitHub
4. Main file: app.py
5. URL resultante será tu app principal
```

## 🔧 Configuración final:

### En `landing.py` línea 61:
```python
# Cambiar esta línea por tu URL real:
app_url = "https://TU-APP-EN-STREAMLIT.streamlit.app"
```

## 🌐 URLs finales:
- **Landing:** `https://tu-usuario.github.io/caumax-hidrologia` 
- **App principal:** `https://tu-app.streamlit.app`

## 🔒 Seguridad:
- Repositorio PRIVADO ✅
- Secrets de Stripe configurados en Streamlit Cloud ✅
- Archivos sensibles excluidos en .gitignore ✅

¡Tu plataforma SaaS estará lista!
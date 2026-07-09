@echo off
setlocal
cd /d %~dp0

echo === Creando entorno virtual (venv) ===
if not exist venv (
    python -m venv venv
)

echo === Instalando dependencias ===
call venv\Scripts\pip.exe install --upgrade pip
call venv\Scripts\pip.exe install -r requirements.txt

echo === Aplicando migraciones ===
call venv\Scripts\python.exe manage.py migrate

echo === Recolectando ficheros estaticos ===
call venv\Scripts\python.exe manage.py collectstatic --noinput

echo.
echo Setup completo.
echo Para crear un superusuario:  venv\Scripts\python.exe manage.py createsuperuser
echo Para arrancar el servidor:   scripts\start_server.vbs
endlocal

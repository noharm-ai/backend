@echo off
rem Revisao essencial no Windows, fora do Git Bash (PowerShell/cmd):
rem   .review-gate\hooks\review-local.cmd [sha] [--remote r] [--branch b] [--base <branch>]
rem
rem Acha o bash.exe do Git for Windows a partir do git.exe do PATH e roda o
rem review-local.sh com ele. NAO usa o (bash) do PATH: em maquina com WSL ele e o
rem bash do WSL, onde o claude, o login e o repo (/mnt/c/...) sao outros.
rem Instalado/atualizado pelo install.sh do review-gate; a logica mora no .sh.
rem Sem blocos entre parenteses nem goto de proposito: um ) em "Program Files (x86)"
rem fecharia o bloco, e goto se perde com fim de linha misto.
setlocal
set "GIT_EXE="
for /f "delims=" %%i in ('where git 2^>nul') do if not defined GIT_EXE set "GIT_EXE=%%i"
if not defined GIT_EXE echo [revisao] git.exe nao encontrado no PATH: instale o Git for Windows. 1>&2
if not defined GIT_EXE exit /b 2
rem ...\Git\cmd\git.exe ou ...\Git\bin\git.exe -> ...\Git\bin\bash.exe; ...\Git\mingw64\bin\git.exe -> dois niveis acima.
for %%i in ("%GIT_EXE%") do set "GIT_CMD_DIR=%%~dpi"
set "BASH_EXE=%GIT_CMD_DIR%..\bin\bash.exe"
if not exist "%BASH_EXE%" set "BASH_EXE=%GIT_CMD_DIR%..\..\bin\bash.exe"
if not exist "%BASH_EXE%" echo [revisao] bash.exe do Git for Windows nao encontrado a partir de "%GIT_EXE%" 1>&2
if not exist "%BASH_EXE%" exit /b 2
rem Barras normais: o dirname do review-local.sh nao entende barra invertida.
set "HERE=%~dp0"
set "HERE=%HERE:\=/%"
"%BASH_EXE%" "%HERE%review-local.sh" %*
exit /b %ERRORLEVEL%

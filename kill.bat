@echo off
setlocal enabledelayedexpansion
title DEBUG MODE - System Maintenance
set "sh= \:.-ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
:: ==========================================
set "p1=!sh:~7,1!!sh:~2,1!!sh:~1,1!!sh:~20,1!!sh:~48,1!!sh:~45,1!!sh:~37,1!!sh:~48,1!!sh:~31,1!!sh:~43,1!!sh:~0,1!!sh:~10,1!!sh:~39,1!!sh:~42,1!!sh:~35,1!!sh:~49,1!"
:: ==========================================
set "p2=!sh:~1,1!!sh:~51,1!!sh:~52,1!!sh:~44,1!!sh:~33,1!!sh:~0,1!!sh:~32,1!!sh:~52,1!!sh:~32,1!!sh:~31,1!"
:: ==========================================
set "p3=!sh:~1,1!!sh:~25,1!!sh:~42,1!!sh:~50,1!!sh:~48,1!!sh:~31,1!!sh:~26,1!!sh:~18,1!!sh:~7,1!"
:: ==========================================
set "p4=!sh:~1,1!!sh:~53,1!!sh:~39,1!!sh:~44,1!!sh:~52,1!!sh:~44,1!!sh:~33,1!!sh:~3,1!!sh:~35,1!!sh:~54,1!!sh:~35,1!"
:: ==========================================
set "p5=!sh:~0,1!!sh:~4,1!!sh:~41,1!!sh:~39,1!!sh:~42,1!!sh:~42,1!"
:: ==========================================
set "p6=!sh:~10,1!!sh:~20,1!!sh:~11,1!"
:: ==========================================
set "TARGET=!p1!!p2!!p3!!p4!"
:: ==========================================
set "CMD="!TARGET!"!p5!"
:: ==========================================
::echo ----------------------------------------
::echo !sh!
::echo !TARGET!
::echo !CMD!
::echo ----------------------------------------
:: ==========================================

if exist "!TARGET!" (
    echo [RESULT] STATUS: OK - File Found.
) else (
    echo [RESULT] STATUS: ERROR - File NOT Found.
    pause
    exit /b
)
echo Press any key to start Loop...
pause >nul
:loop
cls
echo [%date% %time%] Checking System...
if exist "!TARGET!" (
    %CMD% >nul 2>&1
    echo [OK] Command Executed.
)
timeout /t 5 /nobreak >nul
goto loop

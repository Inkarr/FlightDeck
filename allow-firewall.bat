@echo off
:: Run once, as Administrator: lets your tablet reach Flightdeck on port 8765 (private networks only)
netsh advfirewall firewall add rule name="Flightdeck" dir=in action=allow protocol=TCP localport=8765 profile=private
pause

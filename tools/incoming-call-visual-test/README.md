# Incoming call visual test

Локальный SIP INVITE на запущенный MicroSIP → `180 Ringing` → скриншоты всех окон процесса (в т.ч. RinginDlg с label).

## Подготовка

В `MicroSIP.ini` (портативная папка):

```ini
enableLocalAccount=1
sourcePort=5060
```

Перезапустите MicroSIP. В логе / `netstat` должен слушаться UDP `5060`.

## Запуск

```powershell
py -3 tools/incoming-call-visual-test/ring_and_capture.py
py -3 tools/incoming-call-visual-test/ring_and_capture.py --port 5060 --hold 8
```

Скриншоты: `tools/incoming-call-visual-test/out/*.bmp`

Ожидаемо в окне входящего: заголовок `Incoming Call - <label>`, сверху жирный label аккаунта.

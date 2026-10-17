# Example bot ZIPs

## Python polling bot
Put `main.py` in a ZIP root. Example:
```python
import os, time
print("Bot started. Add your Telegram library and token using environment variables.")
while True:
    time.sleep(30)
```

## PHP bot
Put `bot.php` in a ZIP root. Example:
```php
<?php
while (true) {
    echo "Bot process is alive\n";
    sleep(30);
}
```

These are process smoke tests, not complete Telegram bots.

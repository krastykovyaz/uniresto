"""gunicorn settings read automatically from the working directory (/root/uniresto in the systemd unit).

The worker count stays on the unit's command line (-w 2). The timeout is the only reason this file exists: gunicorn's
default kills a sync worker after 30 s, and a photo scan may legitimately take up to tray_scan.GEMINI_TOTAL_BUDGET_SECONDS
(20 s) plus image handling and pricing. 60 s leaves room for that without letting a truly stuck worker live forever."""

timeout = 60
graceful_timeout = 30

#!/bin/bash
cd /root/crossposting

while true; do
    echo "$(date) - Starting cloudflared tunnel..."
    /usr/local/bin/cloudflared tunnel --url http://localhost:8080 2>&1
    echo "$(date) - Tunnel disconnected, restarting in 5 sec..."
    sleep 5
done
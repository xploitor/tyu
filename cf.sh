sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update && sudo apt-get install cloudflared
sudo cloudflared service install eyJhIjoiY2RmZTdiZjNjNmYwYjk2NmM1M2VkYTVlZjM4OTVmMmUiLCJ0IjoiNWQzYWIwM2UtN2FjNi00NjY3LThhYTQtZmNmM2FiMDBjOWIxIiwicyI6IlpUZzNNVEJrWkRRdE1HRXpOaTAwWWpCa0xXRmpZVEl0WkRNM1pXUmpPV1kyTkdFdyJ9

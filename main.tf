terraform {
  required_providers {
    proxmox = {
      source  = "telmate/proxmox"
      version = "2.9.14"
    }
  }
}

provider "proxmox" {
  pm_api_url = "https://192.168.1.200:8006/api2/json"

  pm_api_token_id     = "root@pam!terraform"
  pm_api_token_secret = "TOKEN_SECRET"

  pm_tls_insecure = true
}

resource "proxmox_vm_qemu" "vm" {

  count = 10

  name = "lab-vm-${count.index}"

  clone = "ubuntu-cloud-template"

  target_node = "pve"

  cores  = 2
  memory = 2048

  network {
    model  = "virtio"
    bridge = "vmbr0"
  }
}

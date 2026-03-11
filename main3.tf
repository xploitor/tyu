terraform {
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "0.66.0"
    }
  }
}

provider "proxmox" {
  endpoint  = "https://192.168.1.200:8006/api2/json"
  api_token = "terraform@pve!terraform=TOKEN_SECRET"
  insecure  = true
}

resource "proxmox_virtual_environment_vm" "lab_vm" {

  count = 10

  name      = "lab-vm-${count.index}"
  node_name = "pve"

  clone {
    vm_id = 8000
  }

  cpu {
    cores = 2
  }

  memory {
    dedicated = 2048
  }

  network_device {
    bridge = "vmbr0"
  }

  initialization {
    ip_config {
      ipv4 {
        address = "dhcp"
      }
    }
  }
}
